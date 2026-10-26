"""符号（符号表里的一条绑定）。

一个作用域干两件事：把**名字**绑定到**某种东西**，以及沿父链把名字找回来。
C 里"某种东西"只有五类（TASK.md 的符号表清单），它们的差别不是装饰性的：

    ┌──────────────┬──────────────┬──────────┬────────┐
    │ 绑定          │ 命名空间      │ 有存储？  │ 已实现  │
    ├──────────────┼──────────────┼──────────┼────────┤
    │ 变量          │ ordinary     │ 是(地址)  │ ObjectSymbol→VariableSymbol │
    │ 函数          │ ordinary     │ 是(地址)  │ ObjectSymbol→FunctionSymbol │
    │ typedef 名    │ ordinary     │ 否       │ TypedefSymbol  │
    │ 枚举常量      │ ordinary     │ 否       │ ConstantSymbol │
    │ struct/union/enum 标签 │ tags │ 否       │ TagSymbol      │
    └──────────────┴──────────────┴──────────┴────────┘

"有存储"这一列是关键：它决定 `&` 能不能作用在这个名字上（UC-08）。
C 里 `&T`（T 是 typedef）和 `&ENUM_CONST` 都是非法的，所以这件事不该靠
调用方到处 isinstance 去猜，而应该由符号自己回答。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from super_execute.domain.exceptions import InvalidSymbolError
from super_execute.domain.value_objects import (
    Address,
    AddressRegion,
    Linkage,
    NamespaceKind,
    SymbolKind,
    TagKind,
)


class Symbol(ABC):
    """所有绑定的基类：一个名字 + 它属于哪个命名空间。

    用 __slots__ 而不是 dataclass：子类字段各不相同、而且很多是"没有"的
    （无地址、无类型），dataclass 会逼着每个子类都声明一堆 None 字段。
    """

    __slots__ = ("name",)

    #: 子类固定，用于日志与按种类分派。
    kind: SymbolKind

    def __init__(self, name: str) -> None:
        if not isinstance(name, str) or not name:
            raise InvalidSymbolError(f"符号名必须是非空字符串，收到 {name!r}")
        self.name = name

    # ---- 子类必须回答的 ----

    @property
    @abstractmethod
    def namespace(self) -> NamespaceKind:
        """这个符号绑在哪个命名空间上。"""

    # ---- 默认：没有存储 ----

    @property
    def has_storage(self) -> bool:
        """名字是否对应一块可以取地址的内存。"""
        return False

    @property
    def address(self) -> Address | None:
        """名字的地址；没有存储的绑定返回 None。"""
        return None

    # ---- 表达 ----

    def _describe(self) -> tuple[str, ...]:
        return ()

    def __repr__(self) -> str:
        parts = (f"name={self.name!r}", *self._describe())
        return f"{type(self).__name__}({', '.join(parts)})"


class ObjectSymbol(Symbol):
    """有存储的符号：变量与函数。`&` 的合法作用对象。

    变量和函数唯一的区别是地址落在哪个区，因此共用一个基类，
    由子类在构造时校验区号——这样 `&x` / `&f` 走同一条"有没有地址"的判断。
    """

    __slots__ = ("ctype", "linkage", "_address")

    #: 该子类的地址必须落在哪个内存区。
    address_region: AddressRegion

    def __init__(
        self,
        name: str,
        address: Address,
        ctype: Any = None,
        linkage: Linkage = Linkage.NONE,
    ) -> None:
        super().__init__(name)
        if not isinstance(address, Address):
            raise InvalidSymbolError(
                f"{type(self).__name__} 的地址必须是 Address，收到 {type(address).__name__}")
        expected_region = getattr(type(self), "address_region", None)
        if expected_region is None:
            raise InvalidSymbolError(
                f"{type(self).__name__} 是中间基类，请用 VariableSymbol / FunctionSymbol")
        if address.region is not expected_region:
            raise InvalidSymbolError(
                f"{type(self).__name__} 的地址必须落在 {expected_region.name} 区，"
                f"收到 {address.region.name}")
        if not isinstance(linkage, Linkage):
            raise InvalidSymbolError(f"非法链接属性: {linkage!r}")
        self.ctype = ctype
        self.linkage = linkage
        self._address = address

    @property
    def namespace(self) -> NamespaceKind:
        # 变量、函数、typedef 名、枚举常量共用普通标识符命名空间。
        return NamespaceKind.ORDINARY

    @property
    def has_storage(self) -> bool:
        return True

    @property
    def address(self) -> Address:
        return self._address

    def _describe(self) -> tuple[str, ...]:
        return (
            f"ctype={self.ctype!r}",
            f"address={self._address!r}",
            f"linkage={self.linkage.value}",
        )


class VariableSymbol(ObjectSymbol):
    """变量：局部变量、全局变量、形参。"""

    __slots__ = ()
    kind = SymbolKind.VARIABLE
    address_region = AddressRegion.SCOPE


class FunctionSymbol(ObjectSymbol):
    """函数：函数名本身就是一块存储，它的地址就是函数指针的值。

    旧实现用"函数名字符串"当函数指针（execute.py:774），既存不进内存，
    也不能比较/算术。换成 function 区的地址后，函数指针和普通指针同构。
    """

    __slots__ = ()
    kind = SymbolKind.FUNCTION
    address_region = AddressRegion.FUNCTION


class TypedefSymbol(Symbol):
    """typedef 别名：只指向一个 CType，没有存储。

    它进的是**普通标识符**命名空间——所以 `typedef int T;` 之后再写
    `int T;` 在同一个作用域里是重复定义，必须靠作用域链把它们放在同一张表里
    才看得见（旧的扁平 g_types.aliases 正是看不见这一点，见实证 1）。
    """

    __slots__ = ("ctype",)
    kind = SymbolKind.TYPEDEF

    def __init__(self, name: str, ctype: Any) -> None:
        super().__init__(name)
        self.ctype = ctype

    @property
    def namespace(self) -> NamespaceKind:
        return NamespaceKind.ORDINARY

    def _describe(self) -> tuple[str, ...]:
        return (f"ctype={self.ctype!r}",)


class ConstantSymbol(Symbol):
    """枚举常量：普通标识符，但值是编译期算出来的常量，没有存储。

    `enum { N = 3 };  &N` 在 C 里非法——所以它和变量虽然同一个命名空间，
    却不是同一种东西。
    """

    __slots__ = ("value", "ctype")
    kind = SymbolKind.ENUM_CONSTANT

    def __init__(self, name: str, value: int, ctype: Any = None) -> None:
        super().__init__(name)
        self.value = value
        self.ctype = ctype

    @property
    def namespace(self) -> NamespaceKind:
        return NamespaceKind.ORDINARY

    def _describe(self) -> tuple[str, ...]:
        return (f"value={self.value!r}", f"ctype={self.ctype!r}")


class TagSymbol(Symbol):
    """结构体/联合体/枚举的标签：进的是**标签命名空间**。

    所以 `struct Point` 和变量 `Point` 可以同时存在（C99 的两个命名空间）。
    标签名在 C 里跨 struct/union/enum 唯一，因此作用域链上按名字查找，
    种类只作为信息挂在符号上。
    """

    __slots__ = ("tag_kind", "ctype")
    kind = SymbolKind.TAG

    def __init__(self, name: str, tag_kind: TagKind, ctype: Any = None) -> None:
        super().__init__(name)
        if not isinstance(tag_kind, TagKind):
            raise InvalidSymbolError(f"非法标签种类: {tag_kind!r}")
        self.tag_kind = tag_kind
        self.ctype = ctype

    @property
    def namespace(self) -> NamespaceKind:
        return NamespaceKind.TAGS

    def _describe(self) -> tuple[str, ...]:
        return (f"tag_kind={self.tag_kind.value}", f"ctype={self.ctype!r}")
