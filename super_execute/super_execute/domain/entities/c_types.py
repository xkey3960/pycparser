"""C 的类型（最小集）。

这一层要回答的问题只有一个：**一个类型占几个字节、对齐到几**。内存分配、
指针算术的步长、结构体成员的偏移、`sizeof`/`offsetof`，全都从这两个数字出发。

范围（本轮刻意不做）：

* 位域——成员模型里保留了 ``bit_width`` 字段，但传了非 None 会直接报
  ``UnsupportedTypeError``，等单独一轮再实现（它要把成员模型从"偏移"扩成
  "偏移 + 位偏移 + 位宽"）。
* 类型限定符 ``const`` / ``volatile`` / ``restrict`` —— 等"赋值合法性检查"
  那一轮再加，现在解析阶段就应该把它们剥掉。
* ``long double`` —— 没有对应的基础类型条目，解析会报未知类型。

关于指针大小：本项目以 **4 字节地址**为准（TASK.md 的编址方案），因此
``sizeof(void *) == 4``，与常见的 x86-64 目标（8）不同。这是建模选择而非笔误——
只有指针宽度和 :class:`~super_execute.domain.value_objects.Address` 的宽度一致，
"指针就是一个地址、地址就是一个 4 字节整数"这条主线才闭合。凡是结构体里出现
指针的布局，都与宿主 ABI 不同，测试里的黄金值因此只用标量成员。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable, Sequence

from super_execute.domain.exceptions import (
    IncompleteTypeError,
    InvalidTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.value_objects import ADDRESS_SIZE

#: 指针 = 地址，宽度必须与 Address 一致。
POINTER_SIZE = ADDRESS_SIZE
POINTER_ALIGN = ADDRESS_SIZE

#: 枚举常量按 int 存储。
ENUM_SIZE = 4
ENUM_ALIGN = 4


class CType(ABC):
    """所有 C 类型的基类。

    实体 vs 值对象：标量/指针/数组/函数类型按结构判等（值对象语义），
    struct/union/enum 按"标签实例"判等（实体语义）——C 里两个成员完全相同
    的 ``struct P`` 也是不同类型，判等必须靠身份。
    """

    __slots__ = ()

    @property
    @abstractmethod
    def name(self) -> str:
        """C 源码里的写法，如 ``int`` / ``char *`` / ``struct Point``。"""

    @abstractmethod
    def sizeof(self) -> int:
        """占多少字节；对不完整类型抛 :class:`IncompleteTypeError`。"""

    @abstractmethod
    def alignof(self) -> int:
        """对齐要求（字节）。"""

    @property
    def is_complete(self) -> bool:
        """类型是否已经完整（能求大小）。"""
        return True

    def describe(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name


class BasicType(CType):
    """基础类型：``int`` / ``char`` / ``double`` / ``void`` …

    ``void`` 用 ``size=None`` 表示：它是"不完整"的，``sizeof(void)`` 非法。
    """

    __slots__ = ("_name", "_size", "_align", "_signed", "_is_float")

    def __init__(
        self,
        name: str,
        size: int | None,
        align: int | None,
        *,
        signed: bool = True,
        is_float: bool = False,
    ) -> None:
        if not name:
            raise InvalidTypeError("基础类型必须有名字")
        if size is not None and size <= 0:
            raise InvalidTypeError(f"{name} 的大小必须为正: {size}")
        if align is not None and align <= 0:
            raise InvalidTypeError(f"{name} 的对齐必须为正: {align}")
        self._name = name
        self._size = size
        self._align = align
        self._signed = signed
        self._is_float = is_float

    @property
    def name(self) -> str:
        return self._name

    @property
    def is_complete(self) -> bool:
        return self._size is not None

    @property
    def is_signed(self) -> bool:
        return self._signed

    @property
    def is_float(self) -> bool:
        return self._is_float

    def sizeof(self) -> int:
        if self._size is None:
            raise IncompleteTypeError(f"{self._name} 是不完整类型，没有大小")
        return self._size

    def alignof(self) -> int:
        if self._align is None:
            raise IncompleteTypeError(f"{self._name} 是不完整类型，没有对齐要求")
        return self._align

    def __eq__(self, other: object) -> bool:
        return isinstance(other, BasicType) and other._name == self._name

    def __hash__(self) -> int:
        return hash((BasicType, self._name))

    def __repr__(self) -> str:
        return f"BasicType({self._name!r}, {self._size}, {self._align})"


class PointerType(CType):
    """指针：大小固定等于地址宽度。"""

    __slots__ = ("target",)

    def __init__(self, target: CType) -> None:
        if not isinstance(target, CType):
            raise InvalidTypeError(f"指针目标必须是 CType，收到 {type(target).__name__}")
        self.target = target

    @property
    def name(self) -> str:
        return f"{self.target.name} *"

    def sizeof(self) -> int:
        return POINTER_SIZE

    def alignof(self) -> int:
        return POINTER_ALIGN

    def __eq__(self, other: object) -> bool:
        return isinstance(other, PointerType) and other.target == self.target

    def __hash__(self) -> int:
        return hash((PointerType, self.target))

    def __repr__(self) -> str:
        return f"PointerType({self.target!r})"


class ArrayType(CType):
    """数组。

    ``count=None`` 表示不完整数组（``int a[];``），它有两种合法归宿：
    补上长度，或者作为结构体的**最后一个**成员（弹性数组成员，C99）。
    """

    __slots__ = ("element", "count")

    def __init__(self, element: CType, count: int | None = None) -> None:
        if not isinstance(element, CType):
            raise InvalidTypeError(f"数组元素必须是 CType，收到 {type(element).__name__}")
        if count is not None and count < 0:
            raise InvalidTypeError(f"数组长度不能为负: {count}")
        self.element = element
        self.count = count

    @property
    def name(self) -> str:
        size = "" if self.count is None else str(self.count)
        return f"{self.element.name}[{size}]"

    @property
    def is_complete(self) -> bool:
        return self.count is not None

    def sizeof(self) -> int:
        if self.count is None:
            raise IncompleteTypeError("不完整数组（缺长度）没有大小")
        return self.element.sizeof() * self.count

    def alignof(self) -> int:
        # C 规定：数组的对齐要求等于元素的对齐要求。
        return self.element.alignof()

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, ArrayType)
                and other.element == self.element
                and other.count == self.count)

    def __hash__(self) -> int:
        return hash((ArrayType, self.element, self.count))

    def __repr__(self) -> str:
        return f"ArrayType({self.element!r}, {self.count})"


class FunctionType(CType):
    """函数类型。

    C 里 ``sizeof`` 不能作用于函数类型，所以大小相关的方法直接报错——
    这也解释了为什么"函数指针"要有自己的一层 ``PointerType``。
    """

    __slots__ = ("ret", "param_types", "variadic")

    def __init__(
        self,
        ret: CType,
        param_types: Sequence[CType] = (),
        variadic: bool = False,
    ) -> None:
        if not isinstance(ret, CType):
            raise InvalidTypeError(f"返回类型必须是 CType，收到 {type(ret).__name__}")
        params = tuple(param_types)
        for param in params:
            if not isinstance(param, CType):
                raise InvalidTypeError(
                    f"参数类型必须是 CType，收到 {type(param).__name__}")
        self.ret = ret
        self.param_types = params
        self.variadic = variadic

    @property
    def name(self) -> str:
        params = ", ".join(p.name for p in self.param_types)
        if self.variadic:
            params = f"{params}, ..." if params else "..."
        return f"{self.ret.name} ({params})"

    def sizeof(self) -> int:
        raise UnsupportedTypeError("C 不允许 sizeof 作用于函数类型")

    def alignof(self) -> int:
        raise UnsupportedTypeError("C 不允许对函数类型取对齐")

    def __eq__(self, other: object) -> bool:
        return (isinstance(other, FunctionType)
                and other.ret == self.ret
                and other.param_types == self.param_types
                and other.variadic == self.variadic)

    def __hash__(self) -> int:
        return hash((FunctionType, self.ret, self.param_types, self.variadic))

    def __repr__(self) -> str:
        return f"FunctionType({self.ret!r}, {self.param_types!r}, variadic={self.variadic})"


class EnumType(CType):
    """枚举：``enum Color { RED, GREEN };``

    ``constants=None`` 表示只有前置声明（``enum Color;``），仍是不完整类型。
    常量按 ``int`` 存储，所以大小/对齐固定。
    """

    __slots__ = ("tag", "_constants")

    def __init__(self, tag: str | None = None,
                 constants: dict[str, int] | None = None) -> None:
        self.tag = tag
        self._constants = dict(constants) if constants is not None else None

    @property
    def name(self) -> str:
        return f"enum {self.tag}" if self.tag else "enum <anonymous>"

    @property
    def is_complete(self) -> bool:
        return self._constants is not None

    @property
    def constants(self) -> dict[str, int]:
        if self._constants is None:
            raise IncompleteTypeError(f"{self.name} 尚未定义枚举常量")
        return dict(self._constants)

    def define(self, constants: dict[str, int]) -> None:
        if self._constants is not None:
            raise InvalidTypeError(f"{self.name} 已经定义过了")
        self._constants = dict(constants)

    def sizeof(self) -> int:
        if self._constants is None:
            raise IncompleteTypeError(f"{self.name} 是不完整类型")
        return ENUM_SIZE

    def alignof(self) -> int:
        if self._constants is None:
            raise IncompleteTypeError(f"{self.name} 是不完整类型")
        return ENUM_ALIGN

    def __repr__(self) -> str:
        return f"EnumType({self.tag!r}, {self._constants!r})"


@dataclass(frozen=True)
class Member:
    """结构体/联合体的一个成员：名字 + 类型（+ 位宽，暂不支持）。"""

    name: str
    ctype: CType
    bit_width: int | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise InvalidTypeError("成员名不能为空")
        if not isinstance(self.ctype, CType):
            raise InvalidTypeError(f"成员类型必须是 CType，收到 {type(self.ctype).__name__}")
        if self.bit_width is not None:
            raise UnsupportedTypeError(
                "位域（bit-field）尚未实现：请先按普通成员声明，"
                "或等位域那一轮再做（见 tasks/20261017-122900/TASK.md）")


def align_up(value: int, alignment: int) -> int:
    """把 value 向上对齐到 alignment 的整数倍。"""
    if alignment <= 0:
        raise InvalidTypeError(f"对齐值必须为正: {alignment}")
    remainder = value % alignment
    return value if remainder == 0 else value + (alignment - remainder)


class _CompoundType(CType):
    """struct / union 的公共部分：定义前不完整、定义后冻结布局。"""

    __slots__ = ("tag", "_members", "_offsets", "_size", "_align")

    def __init__(self, tag: str | None = None) -> None:
        self.tag = tag
        self._members: tuple[Member, ...] | None = None
        self._offsets: dict[str, int] = {}
        self._size: int | None = None
        self._align: int | None = None

    # ---- 定义 ----

    def define(self, members: Iterable[Member]) -> None:
        if self._members is not None:
            raise InvalidTypeError(f"{self.name} 已经定义过了")
        members = tuple(members)
        seen: set[str] = set()
        for member in members:
            if not isinstance(member, Member):
                raise InvalidTypeError(f"成员必须是 Member，收到 {type(member).__name__}")
            if member.name in seen:
                raise InvalidTypeError(f"{self.name} 里成员 '{member.name}' 重复")
            seen.add(member.name)
        size, align, offsets = self._layout(members)
        self._members = members
        self._offsets = offsets
        self._size = size
        self._align = align

    def _layout(self, members: tuple[Member, ...]) -> tuple[int, int, dict[str, int]]:
        raise NotImplementedError

    # ---- 查询 ----

    @property
    def is_complete(self) -> bool:
        return self._members is not None

    @property
    def members(self) -> tuple[Member, ...]:
        if self._members is None:
            raise IncompleteTypeError(f"{self.name} 尚未定义成员")
        return self._members

    def member(self, name: str) -> Member:
        for member in self.members:
            if member.name == name:
                return member
        raise InvalidTypeError(f"{self.name} 没有成员 '{name}'")

    def offsetof(self, name: str) -> int:
        """成员偏移——`&obj.field` 就是"对象基地址 + 这个数"（裁决 D5）。"""
        self.members                       # 不完整则先报错
        try:
            return self._offsets[name]
        except KeyError as exc:
            raise InvalidTypeError(f"{self.name} 没有成员 '{name}'") from exc

    def sizeof(self) -> int:
        if self._size is None:
            raise IncompleteTypeError(
                f"{self.name} 是不完整类型（只有前置声明），不能求大小")
        return self._size

    def alignof(self) -> int:
        if self._align is None:
            raise IncompleteTypeError(
                f"{self.name} 是不完整类型（只有前置声明），没有对齐要求")
        return self._align

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.tag!r}, complete={self.is_complete})"


class StructType(_CompoundType):
    """结构体：成员依次落位，各自按自身对齐要求填补 padding。"""

    __slots__ = ()

    @property
    def name(self) -> str:
        return f"struct {self.tag}" if self.tag else "struct <anonymous>"

    def _layout(self, members: tuple[Member, ...]) -> tuple[int, int, dict[str, int]]:
        offsets: dict[str, int] = {}
        cursor = 0
        align = 1
        last = len(members) - 1
        for index, member in enumerate(members):
            member_align = member.ctype.alignof()
            align = max(align, member_align)
            cursor = align_up(cursor, member_align)
            offsets[member.name] = cursor
            # 弹性数组成员不占 sizeof（C99 6.7.2.1p18）
            if index == last and _is_flexible_array(member.ctype):
                continue
            cursor += member.ctype.sizeof()
        return align_up(cursor, align), align, offsets


class UnionType(_CompoundType):
    """联合体：所有成员从偏移 0 开始，大小取最大成员并向上对齐。"""

    __slots__ = ()

    @property
    def name(self) -> str:
        return f"union {self.tag}" if self.tag else "union <anonymous>"

    def _layout(self, members: tuple[Member, ...]) -> tuple[int, int, dict[str, int]]:
        offsets = {member.name: 0 for member in members}
        align = 1
        size = 0
        for member in members:
            align = max(align, member.ctype.alignof())
            if _is_flexible_array(member.ctype):
                continue
            size = max(size, member.ctype.sizeof())
        return align_up(size, align), align, offsets


def _is_flexible_array(ctype: CType) -> bool:
    """是否是弹性数组成员（长度未定的数组）。"""
    return isinstance(ctype, ArrayType) and ctype.count is None
