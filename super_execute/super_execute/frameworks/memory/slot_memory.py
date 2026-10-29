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
from super_execute.domain.value_objects import (
    SCOPE_ID_MAX,
    SCOPE_ID_MIN,
    SCOPE_REGION_SIZE,
    Address,
    AddressRegion,
)


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

    # ==================== 读写 ====================

    def read(self, address: Address, ctype: CType) -> Any:
        chunk, delta = self._locate(address)
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
        if delta == 0 and ctype is chunk.ctype:
            chunk.value = value
            return
        _reject_scalar_alias(chunk, delta, ctype)
        container, key, actual = _resolve(chunk.value, chunk.ctype, delta, ctype)
        _check_access_type(actual, ctype, delta)
        try:
            container[key] = value
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
        if address.region is not AddressRegion.SCOPE:
            raise RegionNotImplementedError(
                f"{address.region.name} 区本轮尚未实现（heap 留给下一轮）"
            )
        region = self._require_region(address.scope_id)
        chunk = region.find(address.offset)
        if chunk is None:
            raise OutOfBoundsError(
                f"地址 {address!r} 不在作用域 #{address.scope_id} 的任何对象里"
            )
        return chunk, address.offset - chunk.offset


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
        if rest == 0:
            return value, index, ctype.element
        return _resolve(value[index], ctype.element, rest, want)

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
        if rest == 0:
            if not isinstance(value, dict):
                raise OutOfBoundsError(f"{ctype.name} 的值不是 dict，无法解析成员")
            return value, member.name, member.ctype
        if not isinstance(value, dict) or member.name not in value:
            raise OutOfBoundsError(
                f"{ctype.name} 的成员 '{member.name}' 没有值（复合值应为 dict）"
            )
        return _resolve(value[member.name], member.ctype, rest, want)

    raise OutOfBoundsError(f"{ctype.name} 是标量，偏移 {delta} 已经越过它自身")


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
