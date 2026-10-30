"""表达式 → 类型。

为什么需要单独一层：`sizeof(x)`、`p + 1` 的步长、`s.m` 的成员类型都要求先知道
"这个表达式是什么类型"。旧实现把这件事叫 `infer_type`，摊在 `execute.py` 里；
这里把它独立出来，因为求值器和语句执行器都要用。

**注意它认识 pycparser 的节点**——所以它属于适配层，不属于 application。
用例和领域仍然对 AST 一无所知。
"""

from __future__ import annotations

from typing import Any

from pycparser import c_ast

from super_execute.application.ports.function_table_port import FunctionTablePort
from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    PointerType,
    StructType,
    UnionType,
)
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    FunctionSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import (
    InvalidTypeError,
    NotAValueError,
    UndefinedSymbolError,
    UnresolvedTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.services.builtin_types import (
    CHAR,
    DOUBLE,
    INT,
    UNSIGNED_INT,
    UNSIGNED_LONG,
)
from super_execute.domain.services.conversions import (
    integer_promote,
    usual_arithmetic_convert,
)
from super_execute.interface_adapters.ast.type_builder import TypeBuilder

_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">=", "&&", "||"})
_SHIFTS = frozenset({"<<", ">>"})

_CONST_TYPES = {
    "int": INT,
    "char": CHAR,
    "float": DOUBLE,
    "double": DOUBLE,
    "unsigned int": UNSIGNED_INT,
    "long": INT,
    "long long": INT,
}


class TypeInferencer:
    """按当前作用域推导表达式的 C 类型。"""

    __slots__ = ("_resolver", "_functions")

    def __init__(
        self,
        resolver: TypeResolverPort | None = None,
        functions: FunctionTablePort | None = None,
    ) -> None:
        self._resolver = resolver
        self._functions = functions

    @property
    def resolver(self) -> TypeResolverPort | None:
        return self._resolver

    def infer(self, node: Any, scope: Scope) -> CType:
        if node is None:
            return INT
        if isinstance(node, c_ast.Constant):
            return self._constant(node)
        if isinstance(node, c_ast.ID):
            return self._identifier(node.name, scope)
        if isinstance(node, c_ast.BinaryOp):
            return self._binary(node, scope)
        if isinstance(node, c_ast.UnaryOp):
            return self._unary(node, scope)
        if isinstance(node, c_ast.Assignment):
            return self.infer(node.lvalue, scope)
        if isinstance(node, c_ast.Cast):
            return self.from_type(node.to_type, scope)
        if isinstance(node, c_ast.Typename):
            return self.from_type(node, scope)
        if isinstance(node, c_ast.StructRef):
            return self._struct_ref(node, scope)
        if isinstance(node, c_ast.ArrayRef):
            return self._array_ref(node, scope)
        if isinstance(node, c_ast.TernaryOp):
            return self._ternary(node, scope)
        if isinstance(node, c_ast.FuncCall):
            return self._call(node, scope)
        if isinstance(node, c_ast.ExprList):
            if not node.exprs:
                raise UnsupportedTypeError("空的逗号表达式")
            return self.infer(node.exprs[-1], scope)
        if isinstance(node, c_ast.Compound):
            return self._compound(node, scope)
        raise UnsupportedTypeError(f"还没支持的表达式类型: {type(node).__name__}")

    def _compound(self, node: c_ast.Compound, scope: Scope) -> CType:
        """GNU 语句表达式 `({ ... })` 的类型 = 最后一条表达式语句的类型。

        中间那些声明/语句不产生值，所以要跳过——注意语句表达式里可以夹
        ``Decl``（`({ int a = 3; a + 4; })`）。
        """
        for item in reversed(node.block_items or []):
            if isinstance(item, (c_ast.Decl, c_ast.Typedef, c_ast.Pragma)):
                continue
            return self.infer(item, scope)
        raise UnsupportedTypeError("语句表达式里没有产生值的语句")

    # ---- 基础 ----

    @staticmethod
    def _constant(node: c_ast.Constant) -> CType:
        if node.type == "string":
            raise UnsupportedTypeError("字符串字面量还没支持")
        return _CONST_TYPES.get(node.type, INT)

    def _identifier(self, name: str, scope: Scope) -> CType:
        symbol = scope.find(name)
        if symbol is None:
            raise UndefinedSymbolError(
                f"未定义的标识符 '{name}'（查找路径 {scope.describe()}）"
            )
        if isinstance(symbol, ConstantSymbol):
            return symbol.ctype or INT
        if isinstance(symbol, (VariableSymbol, FunctionSymbol)):
            if symbol.ctype is None:
                raise UnresolvedTypeError(f"'{name}' 的类型尚未解析")
            return symbol.ctype
        raise NotAValueError(f"'{name}' 是 {type(symbol).__name__}，没有值的类型")

    def from_type(self, node: Any, scope: Scope) -> CType:
        """把 ``sizeof(int)`` / 强制转换目标那种"类型节点"变成 CType。"""
        if self._resolver is None:
            raise InvalidTypeError("没有类型解析器，无法解析类型节点")
        return TypeBuilder(self._resolver, scope).build(node)

    # ---- 运算 ----

    def _binary(self, node: c_ast.BinaryOp, scope: Scope) -> CType:
        left = self.infer(node.left, scope)
        right = self.infer(node.right, scope)

        if node.op in _COMPARISONS:
            return INT
        if node.op in _SHIFTS:
            return integer_promote(left)

        # 指针参与加减：指针 ± 整数 → 指针；指针 - 指针 → 整型（ptrdiff）
        if isinstance(left, PointerType) and isinstance(right, PointerType):
            if node.op == "-":
                return INT
            raise InvalidTypeError(f"两个指针不能做 '{node.op}'")
        if isinstance(left, PointerType) and node.op in ("+", "-"):
            return left
        if isinstance(right, PointerType) and node.op == "+":
            return right
        if isinstance(left, PointerType) or isinstance(right, PointerType):
            raise InvalidTypeError(f"指针不能做 '{node.op}' 运算")

        return usual_arithmetic_convert(left, right)

    def _unary(self, node: c_ast.UnaryOp, scope: Scope) -> CType:
        if node.op == "&":
            return PointerType(self.infer(node.expr, scope))
        if node.op == "*":
            operand = self.infer(node.expr, scope)
            if not isinstance(operand, PointerType):
                raise InvalidTypeError(f"不能解引用 {operand.name}")
            return operand.target
        if node.op == "!":
            return INT
        if node.op in ("sizeof", "__alignof__"):
            return UNSIGNED_LONG
        if node.op in ("++", "--", "p++", "p--"):
            return self.infer(node.expr, scope)
        if node.op in ("-", "+", "~"):
            return integer_promote(self.infer(node.expr, scope))
        raise UnsupportedTypeError(f"还不支持的一元运算: {node.op}")

    def _ternary(self, node: c_ast.TernaryOp, scope: Scope) -> CType:
        left = self.infer(node.iftrue, scope)
        right = self.infer(node.iffalse, scope)
        if isinstance(left, PointerType):
            return left
        if isinstance(right, PointerType):
            return right
        return usual_arithmetic_convert(left, right)

    # ---- 成员 / 元素 ----

    def _struct_ref(self, node: c_ast.StructRef, scope: Scope) -> CType:
        base = self.infer(node.name, scope)
        if node.type == "->":
            if not isinstance(base, PointerType):
                raise InvalidTypeError(f"'{base.name}' 不是指针，不能用 ->")
            base = base.target
        if not isinstance(base, (StructType, UnionType)):
            raise InvalidTypeError(f"'{base.name}' 没有成员")
        return base.member(node.field.name).ctype

    def _array_ref(self, node: c_ast.ArrayRef, scope: Scope) -> CType:
        base = self.infer(node.name, scope)
        if isinstance(base, ArrayType):
            return base.element
        if isinstance(base, PointerType):
            return base.target
        raise InvalidTypeError(f"'{base.name}' 不能取下标")

    def _call(self, node: c_ast.FuncCall, scope: Scope) -> CType:
        name = node.name.name if isinstance(node.name, c_ast.ID) else None
        if name is not None:
            symbol = scope.find(name)
            if isinstance(symbol, FunctionSymbol) and symbol.ctype is not None:
                return _ret_of(symbol.ctype)
        if self._functions is not None and name is not None:
            address = self._functions.address_of(name)
            if address is not None:
                return _ret_of(self._functions.resolve(address).ctype)
        raise UnsupportedTypeError(
            f"暂时只能推断直接以函数名调用的返回类型: {type(node.name).__name__}"
        )


def _ret_of(ctype: CType) -> CType:
    from super_execute.domain.entities.c_types import FunctionType

    if not isinstance(ctype, FunctionType):
        raise InvalidTypeError(f"'{ctype.name}' 不是函数类型")
    return ctype.ret


def _is_arithmetic(ctype: CType) -> bool:
    return isinstance(ctype, BasicType)
