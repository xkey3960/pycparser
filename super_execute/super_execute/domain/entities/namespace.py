"""单层命名空间：名字 → 符号。

**为什么不在这里做父链查找**：C 的两个命名空间各自独立，但作用域链只有一条。
把链放在 :class:`Scope` 上，Namespace 就退化成"一层字典 + 重复声明检查"，
既好测也好替换；链的语义（沿哪些层查、遇到什么停）集中在一处，不会两份实现漂移
——旧代码里 `link()` 与 `activate()` 的三阶段就是这么漂开的。
"""

from __future__ import annotations

from typing import Iterator

from super_execute.domain.entities.symbol import Symbol
from super_execute.domain.exceptions import (
    DuplicateSymbolError,
    InvalidSymbolError,
    UndefinedSymbolError,
)
from super_execute.domain.value_objects import NamespaceKind


class Namespace:
    """某一层作用域里的一个命名空间。"""

    __slots__ = ("_kind", "_symbols")

    def __init__(self, kind: NamespaceKind) -> None:
        if not isinstance(kind, NamespaceKind):
            raise InvalidSymbolError(f"非法命名空间种类: {kind!r}")
        self._kind = kind
        self._symbols: dict[str, Symbol] = {}

    # ---- 查询 ----

    @property
    def kind(self) -> NamespaceKind:
        return self._kind

    def local(self, name: str) -> Symbol | None:
        """只在本层找，不回溯。"""
        return self._symbols.get(name)

    def require_local(self, name: str) -> Symbol:
        symbol = self._symbols.get(name)
        if symbol is None:
            raise UndefinedSymbolError(f"{self._kind.value} 命名空间里没有 '{name}'")
        return symbol

    def names(self) -> tuple[str, ...]:
        return tuple(self._symbols)

    # ---- 写入 ----

    def declare(self, symbol: Symbol) -> Symbol:
        """在本层新增一个绑定；同层重名报错。

        C 允许某些"重复声明"（`extern int x;` 两次、函数原型重复、tentative
        definition），但那是**语义层**的判断——由用例决定该走 declare 还是
        :meth:`redeclare`。这里只守住"一层一张表，键唯一"这个最底层的事实。
        """
        self._check_symbol(symbol)
        if symbol.name in self._symbols:
            raise DuplicateSymbolError(
                f"{self._kind.value} 命名空间里已存在 '{symbol.name}'"
                f"（已有 {type(self._symbols[symbol.name]).__name__}，"
                f"新来 {type(symbol).__name__}）"
            )
        self._symbols[symbol.name] = symbol
        return symbol

    def redeclare(self, symbol: Symbol) -> Symbol:
        """覆盖式写入（给 extern / 原型 / tentative definition 用）。"""
        self._check_symbol(symbol)
        self._symbols[symbol.name] = symbol
        return symbol

    def remove(self, name: str) -> Symbol:
        """摘掉一个绑定并返回（用于 enum 常量回滚等场景）。"""
        try:
            return self._symbols.pop(name)
        except KeyError as exc:
            raise UndefinedSymbolError(
                f"{self._kind.value} 命名空间里没有 '{name}'"
            ) from exc

    def clear(self) -> None:
        self._symbols.clear()

    def _check_symbol(self, symbol: Symbol) -> None:
        if not isinstance(symbol, Symbol):
            raise InvalidSymbolError(f"只能绑定 Symbol，收到 {type(symbol).__name__}")
        if symbol.namespace is not self._kind:
            raise InvalidSymbolError(
                f"{type(symbol).__name__} 属于 {symbol.namespace.value} 命名空间，"
                f"不能放进 {self._kind.value} 命名空间"
            )

    # ---- 容器协议 ----

    def __contains__(self, name: object) -> bool:
        # 守卫非字符串：`[] in ns` 不该抛 TypeError，而是"不在里面"。
        return isinstance(name, str) and name in self._symbols

    def __len__(self) -> int:
        return len(self._symbols)

    def __iter__(self) -> Iterator[Symbol]:
        return iter(self._symbols.values())

    def __repr__(self) -> str:
        return f"Namespace({self._kind.value}, {sorted(self._symbols)!r})"
