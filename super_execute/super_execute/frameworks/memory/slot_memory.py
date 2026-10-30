"""作用域内存的实现（D2 的 Phase A：槽位式）。

一个作用域对应一块 64 KiB 的虚拟区域，变量按 ``sizeof``/``alignof`` 顺序落位，
地址就是"作用域 id + 字节偏移"。这一轮槽里放的是 Python 对象，但它已经带来了
真实语义：

* **指针算术有意义**：``p + 1`` 真的跳过 ``sizeof(*p)`` 个字节；
* **越界可见**：落在任何对象之外的偏移直接报错，不再静默读到邻居；
* **悬空可见**：作用域销毁后，属于它的地址一律报错（D3 的前半句）；
* **成员地址可算**：``&s.m`` 就是 ``&s + offsetof(m)``（D5），不必再用
  ``('member', 对象, 字段)`` 这种符号引用。

Phase A 的两处约定（Phase B 换成字节后自然消失）：

1. 复合值用 ``dict[str, Any]`` 表示——成员名到值的映射；
2. 联合体的所有成员都在偏移 0，因此 ``&u.m == &u``（与 C 一致），
   读回来的是整个联合体对象，不是单个成员。
"""

from __future__ import annotations

import copy

from typing import Any

from super_execute.domain.entities.c_types import (
    ArrayType,
    CType,
    StructType,
    UnionType,
    align_up,
)
from super_execute.domain.exceptions import (
    AllocationError,
    IncompleteTypeError,
    MemoryAccessError,
    OutOfBoundsError,
    RegionNotImplementedError,
    ScopeDestroyedError,
)
from super_execute.domain.services.builtin_types import CHAR
from super_execute.domain.services.defaults import default_value
from super_execute.domain.value_objects import (
    HEAP_REGION_SIZE,
    SCOPE_ID_MAX,
    SCOPE_ID_MIN,
    SCOPE_REGION_SIZE,
    Address,
    AddressRegion,
)


class RawBuffer:
    """``malloc`` 出来的原始存储：**没有声明类型**。

    普通槽位有声明类型（"这是一块 int"），所以按别的类型读写要报"类型双关"。
    但 ``malloc`` 返回的是裸内存，调用方随后把它当 ``struct Point *`` 用是天经地义的：

        struct Point *p = malloc(sizeof(struct Point));
        p->x = 1;          /* 往裸内存里写一个 int */

    所以原始存储按"访问时的类型"存值：``(偏移, 类型名) -> 值``。复合类型会**拆开**
    存（结构体按成员偏移、数组按下标），这样 ``*p = pt`` 与 ``p->x`` 看到的是同一份
    数据，而不是两个互不相干的槽。

    这不是字节级存储（Phase A 本来也不做宽度截断），但足以支撑 ``malloc`` 的常见用法。
    """

    __slots__ = ("size", "values")

    def __init__(self, size: int) -> None:
        self.size = size
        self.values: dict[tuple[int, str], Any] = {}

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"RawBuffer(size={self.size}, {len(self.values)} 个已写槽)"


class _Chunk:
    """一块已分配的存储：偏移、大小、类型、值。"""

    __slots__ = ("offset", "size", "ctype", "value")

    def __init__(self, offset: int, size: int, ctype: CType) -> None:
        self.offset = offset
        self.size = size
        self.ctype = ctype
        self.value: Any = None

    def contains(self, offset: int) -> bool:
        if self.size == 0:  # 零尺寸对象（如只含弹性数组的结构体）只能精确命中
            return self.offset == offset
        return self.offset <= offset < self.offset + self.size

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"_Chunk({self.offset}, size={self.size}, {self.ctype.name})"


class _ScopeRegion:
    """一个作用域的存储区：顺序游标 + 已分配块。"""

    __slots__ = ("scope_id", "cursor", "chunks")

    def __init__(self, scope_id: int) -> None:
        self.scope_id = scope_id
        self.cursor = 0
        self.chunks: list[_Chunk] = []

    def find(self, offset: int) -> _Chunk | None:
        for chunk in self.chunks:
            if chunk.contains(offset):
                return chunk
        return None


class SlotMemory:
    """``MemoryPort`` 的 Phase A 实现（只支持 scope 区）。"""

    def __init__(self) -> None:
        self._regions: dict[int, _ScopeRegion] = {}
        self._destroyed: set[int] = set()
        # 堆区：没有 scope_id，一条单调向前的游标 + 若干块
        self._heap_chunks: list[_Chunk] = []
        self._heap_cursor = 0

    # ==================== 生命周期 ====================

    def create_scope(self, scope_id: int) -> None:
        if not isinstance(scope_id, int) or isinstance(scope_id, bool):
            raise AllocationError(
                f"scope_id 必须是整数，收到 {type(scope_id).__name__}"
            )
        if not SCOPE_ID_MIN <= scope_id <= SCOPE_ID_MAX:
            raise AllocationError(f"scope_id 越界: {scope_id}")
        if scope_id in self._regions:
            raise AllocationError(f"作用域 #{scope_id} 的存储已经存在")
        # id 被复用：清掉"已销毁"标记，否则新作用域会一创建就报悬空
        self._destroyed.discard(scope_id)
        self._regions[scope_id] = _ScopeRegion(scope_id)

    def destroy_scope(self, scope_id: int) -> None:
        if scope_id not in self._regions:
            raise MemoryAccessError(f"作用域 #{scope_id} 的存储不存在，无法销毁")
        del self._regions[scope_id]
        self._destroyed.add(scope_id)

    def is_live(self, scope_id: int) -> bool:
        return scope_id in self._regions

    # ==================== 分配 ====================

    def allocate(self, scope_id: int, ctype: CType) -> Address:
        region = self._require_region(scope_id, action="再分配")
        if not isinstance(ctype, CType):
            raise AllocationError(f"分配需要 CType，收到 {type(ctype).__name__}")

        size = ctype.sizeof()  # 不完整类型在这里抛 IncompleteTypeError
        align = ctype.alignof()
        offset = align_up(region.cursor, align)
        if offset + size > SCOPE_REGION_SIZE:
            raise AllocationError(
                f"作用域 #{scope_id} 的存储不够：需要 {size} 字节，"
                f"剩余 {SCOPE_REGION_SIZE - offset}"
            )

        chunk = _Chunk(offset, size, ctype)
        region.chunks.append(chunk)
        region.cursor = offset + size
        return Address(AddressRegion.SCOPE, scope_id, offset)

    def allocate_heap(self, ctype: CType, value: Any) -> Address:
        """在堆区分配一块并写入初值（字符串字面量、后续的 malloc 都走这里）。

        堆区没有 ``scope_id``——地址是 ``region:8 | offset:24``，所以整个程序
        共用一条单调向前的游标。Phase A 不回收（没有 free 语义）。
        """
        if not isinstance(ctype, CType):
            raise AllocationError(f"分配需要 CType，收到 {type(ctype).__name__}")
        size = ctype.sizeof()
        align = ctype.alignof()
        offset = align_up(self._heap_cursor, align)
        if offset + size > HEAP_REGION_SIZE:
            raise AllocationError(f"堆区存储不够：需要 {size} 字节")

        chunk = _Chunk(offset, size, ctype)
        chunk.value = value
        self._heap_chunks.append(chunk)
        self._heap_cursor = offset + size
        return Address(AddressRegion.HEAP, 0, offset)

    def allocate_raw(self, size: int) -> Address:
        """在堆区分配 ``size`` 字节**原始存储**（``malloc`` / ``calloc`` 用）。

        它没有声明类型：调用方随后想当什么用就按什么类型访问（见 ``RawBuffer``）。
        """
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise AllocationError(f"原始分配需要非负整数大小，收到 {size!r}")
        payload = max(size, 1)  # 零长度也要占一个可寻址的槽
        offset = self._heap_cursor
        if offset + payload > HEAP_REGION_SIZE:
            raise AllocationError(f"堆区存储不够：需要 {size} 字节")

        chunk = _Chunk(offset, payload, ArrayType(CHAR, payload))
        chunk.value = RawBuffer(size)
        self._heap_chunks.append(chunk)
        self._heap_cursor = offset + payload
        return Address(AddressRegion.HEAP, 0, offset)

    # ==================== 读写 ====================

    def read(self, address: Address, ctype: CType) -> Any:
        chunk, delta = self._locate(address)
        if isinstance(chunk.value, RawBuffer):
            return _raw_read(chunk.value, delta, ctype)
        if delta == 0 and ctype is chunk.ctype:
            return chunk.value
        _reject_scalar_alias(chunk, delta, ctype)
        container, key, actual = _resolve(chunk.value, chunk.ctype, delta, ctype)
        _check_access_type(actual, ctype, delta)
        try:
            return container[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise OutOfBoundsError(f"偏移 {delta} 上没有可取的值: {exc!r}") from exc

    def write(self, address: Address, value: Any, ctype: CType) -> None:
        chunk, delta = self._locate(address)
        if isinstance(chunk.value, RawBuffer):
            _raw_write(chunk.value, delta, ctype, value)
            return
        if delta == 0 and ctype is chunk.ctype:
            chunk.value = _detach(value)
            return
        _reject_scalar_alias(chunk, delta, ctype)
        container, key, actual = _resolve(chunk.value, chunk.ctype, delta, ctype)
        _check_access_type(actual, ctype, delta)
        try:
            container[key] = _detach(value)
        except (IndexError, TypeError) as exc:
            raise OutOfBoundsError(f"偏移 {delta} 上不能写入: {exc!r}") from exc

    # ==================== 内部 ====================

    def _require_region(
        self, scope_id: int, action: str = "访问该地址"
    ) -> _ScopeRegion:
        if scope_id in self._destroyed:
            raise ScopeDestroyedError(
                f"作用域 #{scope_id} 已经销毁：不能{action}（D3 悬空检测）"
            )
        region = self._regions.get(scope_id)
        if region is None:
            raise MemoryAccessError(f"作用域 #{scope_id} 的存储尚未创建")
        return region

    def _locate(self, address: Address) -> tuple[_Chunk, int]:
        if not isinstance(address, Address):
            raise MemoryAccessError(f"需要 Address，收到 {type(address).__name__}")
        if address.region is AddressRegion.HEAP:
            return self._locate_heap(address)
        if address.region is not AddressRegion.SCOPE:
            raise RegionNotImplementedError(
                f"{address.region.name} 区尚未实现（只做 scope 与 heap）"
            )
        region = self._require_region(address.scope_id)
        chunk = region.find(address.offset)
        if chunk is None:
            raise OutOfBoundsError(
                f"地址 {address!r} 不在作用域 #{address.scope_id} 的任何对象里"
            )
        return chunk, address.offset - chunk.offset

    def _locate_heap(self, address: Address) -> tuple[_Chunk, int]:
        for chunk in self._heap_chunks:
            if chunk.contains(address.offset):
                return chunk, address.offset - chunk.offset
        raise OutOfBoundsError(f"地址 {address!r} 不在堆区的任何对象里")


def _raw_read(raw: RawBuffer, delta: int, ctype: CType) -> Any:
    """从原始存储里按 ``ctype`` 读。复合类型按成员/元素**拼**出来。"""
    _check_raw_bounds(raw, delta, ctype)

    if isinstance(ctype, (StructType, UnionType)):
        return {
            member.name: _raw_read(
                raw, delta + ctype.offsetof(member.name), member.ctype
            )
            for member in ctype.members
        }
    if isinstance(ctype, ArrayType) and ctype.count is not None:
        step = ctype.element.sizeof()
        return [
            _raw_read(raw, delta + index * step, ctype.element)
            for index in range(ctype.count)
        ]

    return raw.values.get((delta, ctype.name), default_value(ctype))


def _raw_write(raw: RawBuffer, delta: int, ctype: CType, value: Any) -> None:
    """往原始存储里按 ``ctype`` 写。复合类型**拆开**写，好和逐成员访问对齐。"""
    _check_raw_bounds(raw, delta, ctype)

    if isinstance(ctype, (StructType, UnionType)):
        for member in ctype.members:
            if isinstance(value, dict) and member.name in value:
                _raw_write(
                    raw,
                    delta + ctype.offsetof(member.name),
                    member.ctype,
                    value[member.name],
                )
        return
    if isinstance(ctype, ArrayType) and ctype.count is not None:
        step = ctype.element.sizeof()
        for index in range(ctype.count):
            if isinstance(value, (list, tuple)) and index < len(value):
                _raw_write(raw, delta + index * step, ctype.element, value[index])
        return

    raw.values[(delta, ctype.name)] = value


def _check_raw_bounds(raw: RawBuffer, delta: int, ctype: CType) -> None:
    if delta < 0:
        raise OutOfBoundsError(f"原始存储的偏移不能为负: {delta}")
    try:
        size = ctype.sizeof()
    except Exception:  # 不完整类型：交给上层按常规路径报错
        return
    if delta + size > raw.size:
        raise OutOfBoundsError(
            f"偏移 {delta} 上放不下 {ctype.name}（{size} 字节），"
            f"这块原始存储只有 {raw.size} 字节"
        )


def _needs_descent(element: CType, want: CType) -> bool:
    """偏移正好落在元素/成员的起点，但调用方要的是它**内部**的东西时，还得往下走。

    典型场景：`m[i][j]` 里 i=0，delta 落在 `int[3]` 的起点；此时 want 是
    `int`，不能就地返回 `int[3]`。少了这一条，二维数组永远读第 0 行就炸。
    """
    if not isinstance(element, (ArrayType, StructType, UnionType)):
        return False
    return not _compatible(element, want)


def _resolve(
    value: Any, ctype: CType, delta: int, want: CType
) -> tuple[Any, str | int, CType]:
    """把"对象内偏移 delta"解析成 (容器, 键, 实际类型)。

    支持任意嵌套：``&arr[1].b`` 的 delta 会一层层剥成
    ``(arr[1] 这个 dict, 'b', int)``。读和写共用同一套寻址，不会出现
    "读得到、写不进"这种不对称。

    ``want`` 用来在同址成员之间消歧——联合体的所有成员都在偏移 0，
    只有访问类型能指出调用方要的是哪一个。
    """
    if isinstance(ctype, ArrayType):
        step = ctype.element.sizeof()
        if step <= 0:
            raise OutOfBoundsError(f"{ctype.name} 的元素大小非法: {step}")
        index = delta // step
        if not isinstance(value, list) or not 0 <= index < len(value):
            raise OutOfBoundsError(
                f"{ctype.name} 的元素下标越界: {index}（值不是 list 或长度不足）"
            )
        rest = delta - index * step
        element = ctype.element
        if rest == 0 and not _needs_descent(element, want):
            return value, index, element
        return _resolve(value[index], element, rest, want)

    if isinstance(ctype, (StructType, UnionType)):
        candidates: list[tuple[Any, int]] = []
        for member in ctype.members:
            base = ctype.offsetof(member.name)
            try:
                size = member.ctype.sizeof()
            except IncompleteTypeError:
                size = 0  # 弹性数组成员没有静态大小
            if size == 0:
                if base == delta:
                    candidates.append((member, 0))
                continue
            if base <= delta < base + size:
                candidates.append((member, delta - base))
        if not candidates:
            raise OutOfBoundsError(f"偏移 {delta} 不在 {ctype.name} 的任何成员上")

        member, rest = next(
            ((m, r) for m, r in candidates if _compatible(m.ctype, want)),
            candidates[0],
        )
        if rest == 0 and not _needs_descent(member.ctype, want):
            if not isinstance(value, dict):
                raise OutOfBoundsError(f"{ctype.name} 的值不是 dict，无法解析成员")
            return value, member.name, member.ctype
        if not isinstance(value, dict) or member.name not in value:
            raise OutOfBoundsError(
                f"{ctype.name} 的成员 '{member.name}' 没有值（复合值应为 dict）"
            )
        return _resolve(value[member.name], member.ctype, rest, want)

    raise OutOfBoundsError(f"{ctype.name} 是标量，偏移 {delta} 已经越过它自身")


def _detach(value: Any) -> Any:
    """写入前把复合值**拷贝**一份。

    C 的赋值是值语义：``Point q = p;`` 之后 ``q.x = 100`` 不能影响 ``p``。
    Phase A 的复合值是 dict/list，直接存进去就成了引用共享——这正是最早那次
    review 里发现的 P0（"struct 赋值不拷贝，产生别名"）。
    """
    if isinstance(value, (dict, list)):
        return copy.deepcopy(value)
    return value


def _reject_scalar_alias(chunk: _Chunk, delta: int, want: CType) -> None:
    """标量块在偏移 0 上换类型访问 = 类型双关，Phase A 做不到。"""
    if delta != 0:
        return
    if isinstance(chunk.ctype, (StructType, UnionType, ArrayType)):
        return  # 复合块可以在偏移 0 上投影到首成员 / 首元素
    raise MemoryAccessError(
        f"这里是标量 {chunk.ctype.name}，不能用 {want.name} 访问"
        "（Phase A 的槽位存储不支持类型双关）"
    )


def _compatible(actual: CType, want: CType) -> bool:
    """访问类型与目标类型是否相容。

    复合类型按**身份**比较（两个成员相同的 struct 也是不同类型）；
    标量 / 指针 / 数组按结构比较。
    """
    if actual is want:
        return True
    if isinstance(actual, (StructType, UnionType)) or isinstance(
        want, (StructType, UnionType)
    ):
        return actual is want
    return actual == want


def _check_access_type(actual: CType, want: CType, delta: int) -> None:
    if _compatible(actual, want):
        return
    raise MemoryAccessError(
        f"偏移 {delta} 上是 {actual.name}，不能用 {want.name} 访问"
        "（Phase A 的槽位存储不支持类型双关）"
    )
