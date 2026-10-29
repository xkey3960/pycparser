"""类型解析端口：用例需要把类型名变成 CType 时，从这里要。"""

from typing import Protocol, Sequence, runtime_checkable

from super_execute.domain.entities.c_types import CType
from super_execute.domain.entities.scope import Scope


@runtime_checkable
class TypeResolverPort(Protocol):
    """按给定作用域解析类型名。

    作用域是参数而不是构造参数：用例会跨作用域工作（文件 → 函数 → 块），
    "从哪个作用域看"每次都可能不同。
    """

    def resolve(self, scope: Scope, names: Sequence[str]) -> CType:
        """把 ``["unsigned", "long"]`` / ``["struct", "P"]`` / ``["MyTypedef"]``
        解析成 CType；解析不了就抛 UndefinedTypeError。"""
