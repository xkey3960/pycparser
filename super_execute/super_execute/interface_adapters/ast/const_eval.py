"""常量折叠：编译期把表达式算成一个整数。

有两处非它不可：

    int a[2 + 1];                    /* 数组维度必须是常量表达式 */
    enum E { A = 1 + 1, B = A * 3 }; /* 枚举值，且可以引用前面的枚举常量 */

C 的常量表达式里不能出现变量，但可以出现：整型/字符字面量、枚举常量、
算术/位运算、比较与逻辑、`sizeof`、整型强转、三目。

不折叠的情况一律返回 ``None``，由调用方决定是报错还是推迟到运行期
（全局初始化就是"推迟"那条路）。
"""

from __future__ import annotations

from typing import Any

from pycparser import c_ast

from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.domain.entities.c_types import BasicType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import ConstantSymbol, VariableSymbol
from super_execute.domain.services.arithmetic import c_div, c_mod

_COMPARISONS = {
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
}

_INT_CONSTANTS = ("int", "long", "unsigned int", "short", "char")


def fold(node: Any, scope: Scope, resolver: TypeResolverPort) -> Any:
    """尝试把表达式折叠成常量；折不动返回 None。"""
    if node is None:
        return None

    if isinstance(node, c_ast.Constant):
        return _literal(node)
    if isinstance(node, c_ast.ID):
        return _identifier(node.name, scope)
    if isinstance(node, c_ast.BinaryOp):
        return _binary(node, scope, resolver)
    if isinstance(node, c_ast.UnaryOp):
        return _unary(node, scope, resolver)
    if isinstance(node, c_ast.Cast):
        return _cast(node, scope, resolver)
    if isinstance(node, c_ast.TernaryOp):
        cond = fold(node.cond, scope, resolver)
        if cond is None:
            return None
        return fold(node.iftrue if cond else node.iffalse, scope, resolver)
    if isinstance(node, c_ast.ExprList):
        if not node.exprs:
            return None
        return fold(node.exprs[-1], scope, resolver)
    return None


def _literal(node: c_ast.Constant) -> Any:
    if node.type in ("int", "long", "unsigned int", "short"):
        try:
            return int(node.value, 0)
        except ValueError:
            return None
    if node.type == "char":
        text = node.value.strip("'")
        if len(text) == 1:
            return ord(text)
        try:
            return int(node.value, 0)
        except ValueError:
            return None
    if node.type in ("float", "double"):
        try:
            return float(node.value)
        except ValueError:
            return None
    return None


def _identifier(name: str, scope: Scope) -> Any:
    symbol = scope.find(name)
    if isinstance(symbol, ConstantSymbol):
        return symbol.value
    return None


def _binary(node: c_ast.BinaryOp, scope: Scope, resolver: TypeResolverPort) -> Any:
    left = fold(node.left, scope, resolver)
    if left is None:
        return None
    right = fold(node.right, scope, resolver)
    if right is None:
        return None
    return _apply(node.op, left, right)


def _unary(node: c_ast.UnaryOp, scope: Scope, resolver: TypeResolverPort) -> Any:
    if node.op in ("sizeof", "__alignof__"):
        ctype = _sizeof_operand(node.expr, scope, resolver)
        if ctype is None:
            return None
        return ctype.sizeof() if node.op == "sizeof" else ctype.alignof()

    value = fold(node.expr, scope, resolver)
    if value is None:
        return None
    if node.op == "-":
        return -value
    if node.op == "+":
        return value
    if node.op == "~":
        return ~int(value)
    if node.op == "!":
        return 0 if value else 1
    return None


def _cast(node: c_ast.Cast, scope: Scope, resolver: TypeResolverPort) -> Any:
    value = fold(node.expr, scope, resolver)
    if value is None:
        return None
    from super_execute.interface_adapters.ast.type_builder import TypeBuilder

    target = TypeBuilder(resolver, scope).build(node.to_type)
    if isinstance(target, BasicType):
        return float(value) if target.is_float else int(value)
    return None


def _sizeof_operand(node: Any, scope: Scope, resolver: TypeResolverPort) -> Any:
    if isinstance(node, c_ast.Typename):
        from super_execute.interface_adapters.ast.type_builder import TypeBuilder

        return TypeBuilder(resolver, scope).build(node)
    if isinstance(node, c_ast.ID):
        symbol = scope.find(node.name)
        if isinstance(symbol, VariableSymbol):
            return symbol.ctype
    return None


def _apply(op: str, left: Any, right: Any) -> Any:
    comparator = _COMPARISONS.get(op)
    if comparator is not None:
        return 1 if comparator(left, right) else 0
    if op == "&&":
        return 1 if (left and right) else 0
    if op == "||":
        return 1 if (left or right) else 0
    if op == "+":
        return left + right
    if op == "-":
        return left - right
    if op == "*":
        return left * right
    if op == "/":
        if isinstance(left, int) and isinstance(right, int):
            return c_div(left, right)
        return left / right
    if op == "%":
        return c_mod(int(left), int(right))
    if op == "<<":
        return int(left) << int(right)
    if op == ">>":
        return int(left) >> int(right)
    if op == "&":
        return int(left) & int(right)
    if op == "|":
        return int(left) | int(right)
    if op == "^":
        return int(left) ^ int(right)
    return None
