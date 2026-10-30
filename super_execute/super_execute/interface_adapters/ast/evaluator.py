"""表达式求值：AST → 值，以及**lvalue → 地址**。

C 的表达式只有两种命运：算出一个值，或者算出一个地址。`s.m` 和 `a[i]` 之所以
既能在左边也能在右边，是因为它们的"值"其实是一个地址，赋值的另一半是
"把右值写到这个地址上"。

所以这里有两套入口：

    eval(node, scope)    → 值
    lvalue(node, scope)  → Address

`StructRef` / `ArrayRef` / `*p` 在 lvalue 里被翻译成"基地址 + 偏移"，
于是 `&s.m`、`*p = 1`、`a[i] += 1` 全都是同一套机制。

几处 C 语义要点（旧实现踩过的坑）：

* **整型除法向零截断**，不是 Python 的向下取整：`-7 / 2 == -3`，`7 / -2 == -3`；
* 取模结果与被除数同号；
* 指针算术按**元素大小**缩放，`p + 1` 跳过 ``sizeof(*p)`` 字节；
* `&&` / `||` 短路。
"""

from __future__ import annotations

from typing import Any, Callable

from pycparser import c_ast

from super_execute.application.ports.function_table_port import FunctionTablePort
from super_execute.application.ports.memory_port import MemoryPort
from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.application.use_cases.address import TakeAddress
from super_execute.application.use_cases.memory_access import LoadValue, StoreValue
from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    PointerType,
)
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    FunctionSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import (
    DivisionByZeroError,
    InvalidTypeError,
    NotAValueError,
    UndefinedSymbolError,
    UnresolvedTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.services.addressing import element_address, member_address
from super_execute.domain.value_objects import Address
from super_execute.interface_adapters.ast.inference import TypeInferencer

CallHandler = Callable[[c_ast.FuncCall, list[Any], Scope], Any]

_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})


def _unsupported_call(node: c_ast.FuncCall, args: list[Any], scope: Scope) -> Any:
    raise UnsupportedTypeError("还没有绑定函数调用处理器（set_call_handler）")


class Evaluator:
    """求值器：值、地址、类型推导三件事。"""

    __slots__ = ("_memory", "_inferencer", "_take_address", "_load", "_store", "_call")

    def __init__(
        self,
        memory: MemoryPort,
        resolver: TypeResolverPort | None = None,
        functions: FunctionTablePort | None = None,
    ) -> None:
        self._memory = memory
        self._inferencer = TypeInferencer(resolver, functions)
        self._take_address = TakeAddress(functions)
        self._load = LoadValue(memory)
        self._store = StoreValue(memory)
        self._call: CallHandler = _unsupported_call

    def set_call_handler(self, handler: CallHandler) -> None:
        """函数调用要回到语句执行器/解释器，这里用回填避免双向依赖。"""
        self._call = handler

    # ==================== 类型 ====================

    def infer(self, node: Any, scope: Scope) -> CType:
        return self._inferencer.infer(node, scope)

    def from_type(self, node: Any, scope: Scope) -> CType:
        return self._inferencer.from_type(node, scope)

    # ==================== 值 ====================

    def eval(self, node: Any, scope: Scope) -> Any:
        if isinstance(node, c_ast.Constant):
            return _constant_value(node)
        if isinstance(node, c_ast.ID):
            return self._eval_id(node.name, scope)
        if isinstance(node, c_ast.Assignment):
            return self._eval_assignment(node, scope)
        if isinstance(node, c_ast.BinaryOp):
            return self._eval_binary(node, scope)
        if isinstance(node, c_ast.UnaryOp):
            return self._eval_unary(node, scope)
        if isinstance(node, c_ast.Cast):
            return self._eval_cast(node, scope)
        if isinstance(node, (c_ast.StructRef, c_ast.ArrayRef)):
            return self._load_lvalue(node, scope)
        if isinstance(node, c_ast.TernaryOp):
            cond = self.eval(node.cond, scope)
            return self.eval(node.iftrue if cond else node.iffalse, scope)
        if isinstance(node, c_ast.ExprList):
            result = None
            for expr in node.exprs:
                result = self.eval(expr, scope)
            return result
        if isinstance(node, c_ast.FuncCall):
            args = [
                self.eval(arg, scope) for arg in (node.args.exprs if node.args else [])
            ]
            return self._call(node, args, scope)
        raise UnsupportedTypeError(f"还没支持的表达式: {type(node).__name__}")

    def _eval_id(self, name: str, scope: Scope) -> Any:
        symbol = scope.find(name)
        if symbol is None:
            raise UndefinedSymbolError(
                f"未定义的标识符 '{name}'（查找路径 {scope.describe()}）"
            )
        if isinstance(symbol, VariableSymbol):
            if symbol.ctype is None:
                raise UnresolvedTypeError(f"变量 '{name}' 的类型尚未解析")
            if isinstance(symbol.ctype, ArrayType):
                # 数组名退化成指向首元素的指针（C99 6.3.2.1）
                return symbol.address
            return self._memory.read(symbol.address, symbol.ctype)
        if isinstance(symbol, ConstantSymbol):
            return symbol.value
        if isinstance(symbol, FunctionSymbol):
            # 函数名当值用 = 它的地址（函数指针同构）
            return symbol.address
        raise NotAValueError(f"'{name}' 是 {type(symbol).__name__}，不能求值")

    # ==================== 地址（lvalue） ====================

    def lvalue(self, node: Any, scope: Scope) -> Address:
        if isinstance(node, c_ast.ID):
            symbol = scope.find(node.name)
            if isinstance(symbol, VariableSymbol):
                return symbol.address
            if isinstance(symbol, FunctionSymbol):
                raise NotAValueError(f"函数 '{node.name}' 不能作为赋值目标")
            if symbol is None:
                raise UndefinedSymbolError(f"未定义的标识符 '{node.name}'")
            raise NotAValueError(f"'{node.name}' 没有存储，不能取地址")
        if isinstance(node, c_ast.UnaryOp) and node.op == "*":
            address = self.eval(node.expr, scope)
            if not isinstance(address, Address):
                raise InvalidTypeError("解引用的目标不是指针")
            return address
        if isinstance(node, c_ast.StructRef):
            return self._struct_ref_address(node, scope)
        if isinstance(node, c_ast.ArrayRef):
            return self._array_ref_address(node, scope)
        raise UnsupportedTypeError(f"还不能作为赋值目标: {type(node).__name__}")

    def _struct_ref_address(self, node: c_ast.StructRef, scope: Scope) -> Address:
        base_type = self.infer(node.name, scope)
        if node.type == "->":
            if not isinstance(base_type, PointerType):
                raise InvalidTypeError(f"'{base_type.name}' 不是指针，不能用 ->")
            base = self.eval(node.name, scope)
            owner = base_type.target
        else:
            base = self.lvalue(node.name, scope)
            owner = base_type
        if not isinstance(base, Address):
            raise InvalidTypeError("成员访问的基地址不是指针")
        return member_address(base, owner, node.field.name)

    def _array_ref_address(self, node: c_ast.ArrayRef, scope: Scope) -> Address:
        base_type = self.infer(node.name, scope)
        index = self.eval(node.subscript, scope)
        if not isinstance(index, int) or isinstance(index, bool):
            raise InvalidTypeError(f"下标必须是整数，收到 {type(index).__name__}")

        if isinstance(base_type, ArrayType):
            return element_address(self.lvalue(node.name, scope), base_type, index)
        if isinstance(base_type, PointerType):
            base = self.eval(node.name, scope)
            if not isinstance(base, Address):
                raise InvalidTypeError("指针下标的基地址不是指针")
            return base.advanced(index * base_type.target.sizeof())
        raise InvalidTypeError(f"'{base_type.name}' 不能取下标")

    def _load_lvalue(self, node: Any, scope: Scope) -> Any:
        return self._load(self.lvalue(node, scope), self.infer(node, scope))

    # ==================== 赋值 ====================

    def _eval_assignment(self, node: c_ast.Assignment, scope: Scope) -> Any:
        target = self.lvalue(node.lvalue, scope)
        ctype = self.infer(node.lvalue, scope)

        if node.op == "=":
            value = self.eval(node.rvalue, scope)
        else:
            op = node.op[:-1]  # "+=" → "+"
            left = self._load(target, ctype)
            right = self.eval(node.rvalue, scope)
            value = _apply(op, left, right, _step_of(ctype))
        self._store(target, value, ctype)
        return value

    # ==================== 运算 ====================

    def _eval_binary(self, node: c_ast.BinaryOp, scope: Scope) -> Any:
        op = node.op
        if op == "&&":
            return (
                1
                if (self.eval(node.left, scope) and self.eval(node.right, scope))
                else 0
            )
        if op == "||":
            return (
                1
                if (self.eval(node.left, scope) or self.eval(node.right, scope))
                else 0
            )

        left_type = self.infer(node.left, scope)
        # 顺带校验"这个运算合法吗"（比如 struct * 2 要在这里报错）
        result_type = self.infer(node, scope)

        left = self.eval(node.left, scope)
        right = self.eval(node.right, scope)

        if op == "-" and isinstance(left, Address) and isinstance(right, Address):
            return (left.packed - right.packed) // (_step_of(left_type) or 1)

        step = _step_of(result_type)
        if step is None and isinstance(left, Address):
            step = _step_of(left_type)
        return _apply(op, left, right, step)

    def _eval_unary(self, node: c_ast.UnaryOp, scope: Scope) -> Any:
        op = node.op
        if op == "&":
            return self._address_of(node.expr, scope)
        if op == "*":
            address = self.eval(node.expr, scope)
            if not isinstance(address, Address):
                raise InvalidTypeError("解引用的目标不是指针")
            return self._load(address, self.infer(node, scope))
        if op in ("sizeof", "__alignof__"):
            ctype = self._sizeof_operand(node.expr, scope)
            return ctype.sizeof() if op == "sizeof" else ctype.alignof()
        if op in ("++", "--", "p++", "p--"):
            return self._step_pointer_or_int(node, scope)
        if op == "-":
            return -self.eval(node.expr, scope)
        if op == "+":
            return self.eval(node.expr, scope)
        if op == "~":
            return ~self.eval(node.expr, scope)
        if op == "!":
            return 0 if self.eval(node.expr, scope) else 1
        raise UnsupportedTypeError(f"还不支持的一元运算: {op}")

    def _address_of(self, node: Any, scope: Scope) -> Address:
        """`&x`：变量取符号地址，函数取函数地址，其余走 lvalue。"""
        if isinstance(node, c_ast.ID):
            return self._take_address(scope, node.name)
        return self.lvalue(node, scope)

    def _sizeof_operand(self, node: Any, scope: Scope) -> CType:
        if isinstance(node, c_ast.Typename):
            return self.from_type(node, scope)
        return self.infer(node, scope)

    def _step_pointer_or_int(self, node: c_ast.UnaryOp, scope: Scope) -> Any:
        target = self.lvalue(node.expr, scope)
        ctype = self.infer(node.expr, scope)
        old = self._load(target, ctype)

        if isinstance(old, Address):
            step = _step_of(ctype) or 1
            new = old.advanced(step if node.op.endswith("++") else -step)
        else:
            new = old + 1 if node.op.endswith("++") else old - 1

        self._store(target, new, ctype)
        return new if not node.op.startswith("p") else old

    def _eval_cast(self, node: c_ast.Cast, scope: Scope) -> Any:
        value = self.eval(node.expr, scope)
        target = self.from_type(node.to_type, scope)

        if isinstance(target, PointerType):
            return value  # 指针之间的强转在 Phase A 只是换解释，值不变
        if isinstance(target, BasicType):
            if target.is_float:
                return float(value)
            if isinstance(value, Address):
                return value.packed
            return int(value)
        raise UnsupportedTypeError(f"还不支持转换成 {target.name}")


# ==================== 运算细节 ====================


def _constant_value(node: c_ast.Constant) -> Any:
    if node.type == "string":
        raise UnsupportedTypeError("字符串字面量还没支持")
    if node.type == "char":
        return (
            ord(node.value.strip("'")[0])
            if len(node.value.strip("'")) == 1
            else int(node.value, 0)
        )
    if node.type in ("float", "double"):
        return float(node.value)
    return int(node.value, 0)


def _step_of(ctype: CType) -> int | None:
    """指针步长：目标类型的大小。"""
    if isinstance(ctype, PointerType):
        return ctype.target.sizeof()
    return None


def _c_div(a: int, b: int) -> int:
    """C 的整数除法：向零截断（Python 的 // 是向下取整）。"""
    if b == 0:
        raise DivisionByZeroError("除数为 0")
    quotient = abs(a) // abs(b)
    return quotient if (a >= 0) == (b >= 0) else -quotient


def _c_mod(a: int, b: int) -> int:
    if b == 0:
        raise DivisionByZeroError("除数为 0")
    return a - _c_div(a, b) * b


def _equal(a: Any, b: Any) -> bool:
    if isinstance(a, Address) and isinstance(b, Address):
        return a == b
    if isinstance(a, Address):
        return a.packed == b
    if isinstance(b, Address):
        return b.packed == a
    return a == b


def _apply(op: str, a: Any, b: Any, step: int | None) -> Any:
    """二元运算（指针算术与整数语义都在这里）。"""
    if op in _COMPARISONS:
        if op == "==":
            return 1 if _equal(a, b) else 0
        if op == "!=":
            return 0 if _equal(a, b) else 1
        left, right = _order_key(a), _order_key(b)
        return 1 if _compare(op, left, right) else 0

    stride = step or 1
    if op == "+":
        if isinstance(a, Address) and isinstance(b, int):
            return a.advanced(b * stride)
        if isinstance(b, Address) and isinstance(a, int):
            return b.advanced(a * stride)
    if op == "-":
        if isinstance(a, Address) and isinstance(b, int):
            return a.advanced(-b * stride)
        if isinstance(a, Address) and isinstance(b, Address):
            return (a.packed - b.packed) // stride

    if isinstance(a, Address) or isinstance(b, Address):
        raise InvalidTypeError(f"指针不能做 '{op}' 运算")
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        raise InvalidTypeError(
            f"'{op}' 的操作数不是数值（{type(a).__name__} 与 {type(b).__name__}）"
        )

    if op == "+":
        return a + b
    if op == "-":
        return a - b
    if op == "*":
        return a * b
    if op == "/":
        if isinstance(a, int) and isinstance(b, int):
            return _c_div(a, b)
        return a / b
    if op == "%":
        return _c_mod(int(a), int(b))
    if op == "<<":
        return int(a) << int(b)
    if op == ">>":
        return int(a) >> int(b)
    if op == "&":
        return int(a) & int(b)
    if op == "|":
        return int(a) | int(b)
    if op == "^":
        return int(a) ^ int(b)
    raise UnsupportedTypeError(f"还不支持的二元运算: {op}")


def _order_key(value: Any) -> Any:
    return value.packed if isinstance(value, Address) else value


def _compare(op: str, left: Any, right: Any) -> bool:
    if op == "<":
        return left < right
    if op == "<=":
        return left <= right
    if op == ">":
        return left > right
    return left >= right
