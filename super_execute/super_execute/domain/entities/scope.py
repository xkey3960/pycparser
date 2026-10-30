"""作用域：一个词法作用域节点，带两个命名空间和一条父链。

这是本次重构的主角。旧实现的 `Scope` 只有"一个 dict + 父链"，因此**变量**
的作用域是对的，而 **typedef / struct / union / enum / 函数名** 全都不在里面
（它们散在扁平的 `g_types.tags` / `g_types.aliases` / `g_functions` 上）。
后果是实测出来的两条：

    块内 `typedef double T;` 出块后仍生效      → 返回 80，应为 40
    两个函数各自定义 `struct P`              → 返回 8，应为 16

所以这里把"C 的一个作用域"完整建模成：**两个命名空间（ordinary / tags）
× 一条作用域链 × 一个 8 位 id**。id 是地址编码里的 scope 区编号，
它把"名字"和"内存"这两件事接上——这正是符号表要重构的真正原因。
"""

from __future__ import annotations

from super_execute.domain.entities.namespace import Namespace
from super_execute.domain.entities.symbol import ObjectSymbol, Symbol, VariableSymbol
from super_execute.domain.exceptions import (
    InvalidScopeError,
    UndefinedSymbolError,
)
from super_execute.domain.value_objects import (
    SCOPE_ID_MAX,
    SCOPE_ID_MIN,
    Linkage,
    NamespaceKind,
    ScopeKind,
)


class Scope:
    """一个词法作用域节点。

    不变量：

    * ``scope_id`` 在全进程唯一，取值 1..255（0 留给 NULL 地址）；
    * ``FILE`` 是根，没有父作用域；
    * ``FUNCTION`` 的父作用域必须是 ``FILE``——C 里函数不嵌套，函数体看到的
      外部名字只能是文件作用域的；
    * ``BLOCK`` / ``PROTOTYPE`` 可以嵌套在任意作用域下；
    * internal / external 链接属性只能出现在 ``FILE`` 层（D6）。

    查找只走 ordinary 命名空间；标签命名空间要用 :meth:`find_tag`。
    两者分隔是 C 的规则，不是实现细节：`struct Point` 与变量 `Point` 必须能共存。
    """

    __slots__ = ("_scope_id", "_kind", "_parent", "_ordinary", "_tags")

    def __init__(
        self,
        scope_id: int,
        kind: ScopeKind,
        parent: Scope | None = None,
    ) -> None:
        if not isinstance(scope_id, int) or isinstance(scope_id, bool):
            raise InvalidScopeError(
                f"scope_id 必须是整数，收到 {type(scope_id).__name__}"
            )
        if not SCOPE_ID_MIN <= scope_id <= SCOPE_ID_MAX:
            raise InvalidScopeError(
                f"scope_id 越界: {scope_id}（合法范围 {SCOPE_ID_MIN}..{SCOPE_ID_MAX}）"
            )
        try:
            kind = ScopeKind(kind)
        except ValueError as exc:
            raise InvalidScopeError(f"未知的作用域种类: {kind!r}") from exc
        _validate_parent(kind, parent)

        self._scope_id = scope_id
        self._kind = kind
        self._parent = parent
        self._ordinary = Namespace(NamespaceKind.ORDINARY)
        self._tags = Namespace(NamespaceKind.TAGS)

    # ---- 结构 ----

    @property
    def scope_id(self) -> int:
        return self._scope_id

    @property
    def kind(self) -> ScopeKind:
        return self._kind

    @property
    def parent(self) -> Scope | None:
        return self._parent

    @property
    def ordinary(self) -> Namespace:
        return self._ordinary

    @property
    def tags(self) -> Namespace:
        return self._tags

    @property
    def is_root(self) -> bool:
        return self._parent is None

    @property
    def depth(self) -> int:
        return len(self.chain()) - 1

    def chain(self) -> tuple[Scope, ...]:
        """从本层到根的作用域序列（查找顺序）。"""
        scopes, cursor = [], self
        while cursor is not None:
            scopes.append(cursor)
            cursor = cursor._parent
        return tuple(scopes)

    # ---- 写入 ----

    def declare(self, symbol: Symbol) -> Symbol:
        """把符号绑到**本层**对应的命名空间上（不回溯，块的遮蔽由此而来）。

        写符号请统一走这里（或 :meth:`redeclare`）：``ordinary`` / ``tags`` 是
        公开的，直接对它们写入会绕过链接属性与地址归属的校验。
        """
        self._validate_binding(symbol)
        return self._namespace_for(symbol).declare(symbol)

    def redeclare(self, symbol: Symbol) -> Symbol:
        """覆盖式绑定（extern / 函数原型 / tentative definition 靠它）。

        namespace 层的 ``redeclare`` 不做合法性判断，所以这条路径必须经过
        Scope，否则同一条不变量会有两个入口、迟早漂开。
        """
        self._validate_binding(symbol)
        return self._namespace_for(symbol).redeclare(symbol)

    def _validate_binding(self, symbol: Symbol) -> None:
        """绑定前的不变量检查（declare 与 redeclare 共用一份）。"""
        if isinstance(symbol, ObjectSymbol) and symbol.linkage is not Linkage.NONE:
            # internal / external 只可能落在"全程序"或"翻译单元"这两层
            if self._kind not in (ScopeKind.FILE, ScopeKind.UNIT):
                raise InvalidScopeError(
                    f"{symbol.linkage.value} 链接属性只能出现在文件/翻译单元作用域，"
                    f"当前是 {self._kind.value}#{self._scope_id}"
                )
        if isinstance(symbol, VariableSymbol) and symbol.address is not None:
            # 地址里的 scope_id 就是"这块存储属于哪个作用域"，对不上就是错的绑定。
            if symbol.address.scope_id != self._scope_id:
                raise InvalidScopeError(
                    f"变量 '{symbol.name}' 的地址属于作用域 #{symbol.address.scope_id}，"
                    f"不能声明进 #{self._scope_id}"
                )

    def declare_all(self, *symbols: Symbol) -> None:
        for symbol in symbols:
            self.declare(symbol)

    def _namespace_for(self, symbol: Symbol) -> Namespace:
        if symbol.namespace is NamespaceKind.TAGS:
            return self._tags
        return self._ordinary

    # ---- 查找 ----

    def find(self, name: str) -> Symbol | None:
        """沿作用域链查找普通标识符；找不到返回 None。"""
        for scope in self.chain():
            symbol = scope._ordinary.local(name)
            if symbol is not None:
                return symbol
        return None

    def require(self, name: str) -> Symbol:
        symbol = self.find(name)
        if symbol is None:
            raise UndefinedSymbolError(
                f"未定义的标识符 '{name}'（查找路径 {self.describe()}）"
            )
        return symbol

    def find_tag(self, name: str) -> Symbol | None:
        """沿作用域链查找标签（struct/union/enum 共用一个命名空间）。"""
        for scope in self.chain():
            symbol = scope._tags.local(name)
            if symbol is not None:
                return symbol
        return None

    def require_tag(self, name: str) -> Symbol:
        symbol = self.find_tag(name)
        if symbol is None:
            raise UndefinedSymbolError(
                f"未定义的标签 '{name}'（查找路径 {self.describe()}）"
            )
        return symbol

    # ---- 容器协议 ----

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and self.find(name) is not None

    def describe(self) -> str:
        """可读的作用域链，用于错误消息：``block#3 -> function#2 -> file#1``。"""
        return " -> ".join(f"{s._kind.value}#{s._scope_id}" for s in self.chain())

    def __repr__(self) -> str:
        return (
            f"Scope({self._kind.value}#{self._scope_id}, "
            f"ordinary={len(self._ordinary)}, tags={len(self._tags)})"
        )


def _validate_parent(kind: ScopeKind, parent: Scope | None) -> None:
    """作用域链的合法性（见类的 docstring 里的不变量）。"""
    if parent is not None and not isinstance(parent, Scope):
        raise InvalidScopeError(f"父作用域必须是 Scope，收到 {type(parent).__name__}")

    if kind is ScopeKind.FILE:
        if parent is not None:
            raise InvalidScopeError("文件作用域是根，不能再有父作用域")
        return

    if kind is ScopeKind.UNIT:
        # 一个翻译单元挂在全程序作用域下：static 符号在这一层，
        # 外部符号在父层——于是"两个文件各自的 static g"天然不冲突（D6）
        if parent is None:
            raise InvalidScopeError("翻译单元作用域必须挂在全程序作用域下")
        if parent.kind is not ScopeKind.FILE:
            raise InvalidScopeError(
                f"翻译单元作用域只能挂在文件作用域下，收到 {parent.kind.value}"
                f"#{parent.scope_id}"
            )
        return

    if kind is ScopeKind.FUNCTION:
        if parent is None:
            raise InvalidScopeError("函数作用域必须挂在文件作用域或翻译单元作用域下")
        if parent.kind not in (ScopeKind.FILE, ScopeKind.UNIT):
            raise InvalidScopeError(
                f"函数作用域只能挂在文件/翻译单元作用域下，收到 {parent.kind.value}"
                f"#{parent.scope_id}"
            )
        return

    # BLOCK / PROTOTYPE：允许挂任意层；也允许作根（便于单元测试与语句表达式）。
