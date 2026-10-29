"""把"类型名"解析成 CType。

这一步把前一轮做的 Scope 和这一轮的类型系统接上：类型名要么是**标签**
（``struct P``，查 tags 命名空间），要么是**普通标识符**（typedef 名，
查 ordinary 命名空间），要么是**内建类型**（``unsigned long``）。

为什么解析要找作用域链而不是查一张全局表：这正是上一轮四条实证的根因。
两个函数各自定义 ``struct P`` 时，解析必须落在**离当前作用域最近**的那个标签上，
否则两个函数会共用同一个布局（旧实现就是这么错的，实测 8 应为 16）。
"""

from __future__ import annotations

from typing import Sequence

from super_execute.domain.entities.c_types import CType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import TagSymbol, TypedefSymbol
from super_execute.domain.exceptions import (
    InvalidTypeError,
    UndefinedTypeError,
)
from super_execute.domain.services.builtin_types import basic, canonical_type_name

#: 标签类说明符：``struct P`` / ``union U`` / ``enum E``。
_TAG_KEYWORDS = ("struct", "union", "enum")


class ScopeTypeResolver:
    """以某个作用域为视角解析类型名。

    解析顺序（与 C 一致）：

    1. ``struct|union|enum`` 开头的 → 沿作用域链找**标签**；
    2. 纯类型说明符（``unsigned long`` 等）→ 归一化后查内建类型表；
    3. 单个标识符 → 沿作用域链找**普通标识符**，必须是 typedef。

    注意「内建先于标识符」这一点：``int`` 这样的关键字不可能被用户定义的类型名
    遮蔽；反过来，typedef 名 ``int_t`` 也不会被误当成内建类型（它不在关键字集合里）。
    """

    __slots__ = ("_scope",)

    def __init__(self, scope: Scope) -> None:
        if not isinstance(scope, Scope):
            raise InvalidTypeError(f"解析视角必须是 Scope，收到 {type(scope).__name__}")
        self._scope = scope

    @property
    def scope(self) -> Scope:
        return self._scope

    def resolve(self, names: Sequence[str]) -> CType:
        words = [str(word) for word in names]
        if not words:
            raise InvalidTypeError("空类型名")

        head = words[0].lower()
        if head in _TAG_KEYWORDS:
            return self._resolve_tag(head, words)

        canonical = canonical_type_name(words)
        if canonical is not None:
            ctype = basic(canonical)
            if ctype is None:
                # 归一化成功但表里没有（如 long double）——仍归为未定义类型
                raise UndefinedTypeError(f"未定义的类型: '{' '.join(words)}'")
            return ctype

        if len(words) == 1:
            return self._resolve_identifier(words[0])

        raise UndefinedTypeError(f"未定义的类型: '{' '.join(words)}'")

    # ---- 两条查找路径 ----

    def _resolve_tag(self, head: str, words: list[str]) -> CType:
        if len(words) < 2:
            raise InvalidTypeError(f"'{head}' 缺少标签名")
        if len(words) > 2:
            raise InvalidTypeError(
                f"'{head} {words[1]}' 后面有多余的词: {' '.join(words[2:])}"
            )
        tag_name = words[1]
        symbol = self._scope.find_tag(tag_name)
        if symbol is None:
            raise UndefinedTypeError(
                f"未定义的标签 '{tag_name}'（查找路径 {self._scope.describe()}）"
            )
        if not isinstance(symbol, TagSymbol):
            raise InvalidTypeError(f"'{tag_name}' 不是标签")
        if symbol.tag_kind.value != head:
            raise InvalidTypeError(
                f"'{tag_name}' 是 {symbol.tag_kind.value} 标签，不能用 '{head}' 引用"
            )
        return _require_ctype(symbol.ctype, f"标签 '{tag_name}'")

    def _resolve_identifier(self, name: str) -> CType:
        symbol = self._scope.find(name)
        if symbol is None:
            raise UndefinedTypeError(
                f"未定义的类型名 '{name}'（查找路径 {self._scope.describe()}）"
            )
        if not isinstance(symbol, TypedefSymbol):
            raise InvalidTypeError(f"'{name}' 是 {type(symbol).__name__}，不是类型名")
        return _require_ctype(symbol.ctype, f"typedef '{name}'")


def _require_ctype(value: object, what: str) -> CType:
    """符号里挂的 ctype 必须真的是 CType，而不是占位/字符串。"""
    if not isinstance(value, CType):
        raise InvalidTypeError(
            f"{what} 没有绑定有效的 CType（当前 {type(value).__name__}）"
        )
    return value


class TypeResolver:
    """无状态的类型解析器：作用域由调用方每次传入。

    与 :class:`ScopeTypeResolver` 的区别只有"作用域从哪来"：前者在构造时绑定一个
    视角，适合单点使用；后者满足
    :class:`~super_execute.application.ports.type_resolver_port.TypeResolverPort`，
    可以注入用例——因为用例会跨作用域工作（文件 → 函数 → 块），视角是变化的。
    """

    __slots__ = ()

    def resolve(self, scope: Scope, names: Sequence[str]) -> CType:
        return ScopeTypeResolver(scope).resolve(names)
