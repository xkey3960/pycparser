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
    DomainError,
    InvalidTypeError,
    NotAValueError,
    OutOfBoundsError,
    UndefinedSymbolError,
    UnresolvedTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.services.addressing import element_address, member_address
from super_execute.domain.services.arithmetic import c_div, c_mod
from super_execute.domain.services.builtin_types import CHAR
from super_execute.domain.services.defaults import default_value
from super_execute.domain.services.conversions import convert_value
from super_execute.domain.value_objects import Address, AddressRegion
from super_execute.interface_adapters.ast.inference import TypeInferencer
from super_execute.interface_adapters.ast.string_literal import decode_string_literal

CallHandler = Callable[[c_ast.FuncCall, list[Any], Scope], Any]

_COMPARISONS = frozenset({"==", "!=", "<", "<=", ">", ">="})


def _unsupported_call(node: c_ast.FuncCall, args: list[Any], scope: Scope) -> Any:
    raise UnsupportedTypeError("还没有绑定函数调用处理器（set_call_handler）")


def _unsupported_compound(node: c_ast.Compound, scope: Scope) -> Any:
    raise UnsupportedTypeError("还没有绑定语句表达式处理器（set_compound_handler）")


def _is_char_array(ctype: Any) -> bool:
    return isinstance(ctype, ArrayType) and ctype.element.name == "char"


def complete_from_string(ctype: Any, init: Any) -> Any:
    """``char buf[] = "hi";`` 的长度由字符串决定——含结尾 NUL。

    类型不完整时补上长度；其他情况原样返回。声明处（局部与全局）都要用。
    """
    if isinstance(ctype, ArrayType) and ctype.count is None:
        if _is_char_array(ctype) and _is_string_literal(init):
            return ctype.complete(len(decode_string_literal(init.value)) + 1)
    return ctype


def _is_string_literal(node: Any) -> bool:
    return isinstance(node, c_ast.Constant) and node.type == "string"


def _string_into_array(text: str, ctype: ArrayType) -> list[int]:
    """把字符串**拷贝**进字符数组，多余位置补零。

    ``char buf[4] = "abc";`` 合法（正好放下，没有 NUL）；
    ``char buf[2] = "abc";`` 不合法——C 不允许丢掉结尾以外的字符。
    """
    chars = [ord(char) for char in text]
    count = ctype.count
    if count is None:
        return chars + [0]
    if len(chars) > count:
        raise InvalidTypeError(
            f"初始化字符串太长：{len(chars)} 个字符放不进 char[{count}]"
        )
    return chars + [0] * (count - len(chars))


def _designator(entry: Any) -> tuple[Any, Any]:
    """拆开指定初始化器：``{.b = 5}`` → ``('b', 值表达式)``，``{[1] = 7}`` → ``(1, …)``。

    普通项返回 ``(None, 表达式)``，由调用方按键位顺序往下排。
    """
    if not isinstance(entry, c_ast.NamedInitializer) or not entry.name:
        return None, entry

    first = entry.name[0]
    if isinstance(first, c_ast.ID):
        return first.name.lstrip("."), entry.expr
    # 注意：Python 版 pycparser 把 `[1]` 的设计符直接摊成 Constant，
    # 而不是 ArrayRef——两种都要认。
    if isinstance(first, c_ast.Constant) and first.type in (
        "int",
        "long",
        "unsigned int",
    ):
        return int(first.value, 0), entry.expr
    if isinstance(first, c_ast.ArrayRef):
        index = first.subscript
        if isinstance(index, c_ast.Constant) and index.type in (
            "int",
            "long",
            "unsigned int",
        ):
            return int(index.value, 0), entry.expr
        raise UnsupportedTypeError("指定初始化的下标必须是整型常量")
    raise UnsupportedTypeError(f"不认识的指定初始化器: {type(first).__name__}")


class Evaluator:
    """求值器：值、地址、类型推导三件事。"""

    __slots__ = (
        "_memory",
        "_inferencer",
        "_take_address",
        "_load",
        "_store",
        "_call",
        "_compound",
        "_strings",
    )

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
        self._compound: CallHandler = _unsupported_compound
        self._strings: dict[str, Address] = {}

    def set_call_handler(self, handler: CallHandler) -> None:
        """函数调用要回到语句执行器/解释器，这里用回填避免双向依赖。"""
        self._call = handler

    def set_compound_handler(self, handler: CallHandler) -> None:
        """语句表达式 `({ ... })` 要执行语句，同样用回填。

        求值器本身不持有作用域会话（开块作用域、关块作用域是语句执行器的事），
        所以这里只留一个钩子。
        """
        self._compound = handler

    # ==================== 类型 ====================

    def infer(self, node: Any, scope: Scope) -> CType:
        return self._inferencer.infer(node, scope)

    def from_type(self, node: Any, scope: Scope) -> CType:
        return self._inferencer.from_type(node, scope)

    # ==================== 值 ====================

    def eval(self, node: Any, scope: Scope) -> Any:
        """求值入口：顺带把"最先出错的位置"记到异常上（QOL-1）。

        因为递归调用也走这里，**最内层**的节点会先附上 coord；外层看到已有值
        就不再覆盖，所以报出来的是真正的出错点，而不是最外层的调用语句。
        """
        try:
            return self._eval(node, scope)
        except DomainError as error:
            raise error.with_coord(getattr(node, "coord", None)) from None

    def _eval(self, node: Any, scope: Scope) -> Any:
        if isinstance(node, c_ast.Constant):
            if node.type == "string":
                return self._string_literal(node)
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
        if isinstance(node, c_ast.Compound):
            # GNU 语句表达式 `({ ... })`：出现在**表达式位置**的复合语句，
            # 值是最后一条表达式语句的值
            return self._compound(node, scope)
        raise UnsupportedTypeError(f"还没支持的表达式: {type(node).__name__}")

    def _string_literal(self, node: c_ast.Constant) -> Address:
        """字符串字面量：内容放进堆区，值是它的地址。

        相同的字面量**只分配一次**（C99 6.4.5p6 说重复的字面量是否合并是
        实现定义的），这样循环里反复求值不会把堆撑爆。
        """
        text = decode_string_literal(node.value)
        cached = self._strings.get(text)
        if cached is not None:
            return cached

        chars = [ord(char) for char in text] + [0]  # 结尾 NUL
        address = self._memory.allocate_heap(ArrayType(CHAR, len(chars)), chars)
        self._strings[text] = address
        return address

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
        # 赋值的最后一步是隐式转换：`int y = 5; y += 2.7;` 结果是 7
        value = convert_value(value, ctype)
        self._store(target, value, ctype)
        return value

    # ==================== 初始化器 ====================

    def eval_init(self, init: Any, ctype: CType, scope: Scope) -> Any:
        """按目标类型求一个初始化器的值。

        ``{...}`` 不是表达式——它是**按类型铺开**的：数组按下标、结构体按成员，
        缺的位置补零。所以不能走普通 ``eval``，必须带着目标类型递归。
        """
        if init is None:
            return default_value(ctype)
        if not isinstance(init, c_ast.InitList):
            # `char buf[16] = "ab";` —— 字符串字面量初始化字符数组，内容是**拷贝**进去的
            if _is_char_array(ctype) and _is_string_literal(init):
                return _string_into_array(decode_string_literal(init.value), ctype)
            return convert_value(self.eval(init, scope), ctype)
        return self._init_list(init, ctype, scope)

    def _init_list(self, node: c_ast.InitList, ctype: CType, scope: Scope) -> Any:
        entries = list(node.exprs or [])

        if isinstance(ctype, ArrayType):
            count = ctype.count if ctype.count is not None else len(entries)
            values = [default_value(ctype.element) for _ in range(count)]
            index = 0
            for entry in entries:
                designator, expr = _designator(entry)
                if designator is not None:
                    index = designator
                if not 0 <= index < count:
                    raise OutOfBoundsError(f"初始化器下标 {index} 超出数组长度 {count}")
                values[index] = self.eval_init(expr, ctype.element, scope)
                index += 1
            return values

        if isinstance(ctype, (StructType, UnionType)):
            members = list(ctype.members)
            values = {member.name: default_value(member.ctype) for member in members}
            index = 0
            for entry in entries:
                designator, expr = _designator(entry)
                if designator is not None:
                    member = next((m for m in members if m.name == designator), None)
                    if member is None:
                        raise InvalidTypeError(f"{ctype.name} 没有成员 '{designator}'")
                    values[member.name] = self.eval_init(expr, member.ctype, scope)
                    continue
                if index >= len(members):
                    raise InvalidTypeError(
                        f"{ctype.name} 只有 {len(members)} 个成员，初始化器给多了"
                    )
                member = members[index]
                values[member.name] = self.eval_init(expr, member.ctype, scope)
                index += 1
            return values

        # 标量写成 `int x = {5};` —— 只取第一项
        return (
            self.eval_init(entries[0], ctype, scope)
            if entries
            else default_value(ctype)
        )

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
        # 顺带校验"这个运算合法吗"（比如 struct * 2 要在这里报错）。
        # 出错时把运算本身也报出来——只说"类型不匹配"看不出是哪一步。
        try:
            result_type = self.infer(node, scope)
        except InvalidTypeError as error:
            raise InvalidTypeError(
                f"二元运算 BinaryOp('{op}') 的操作数类型不匹配：{error}"
            ) from None

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
            if address.region is AddressRegion.FUNCTION:
                # 解引用函数指针得到"函数本身"，而函数当值时就是它的地址，
                # 所以 `(*fp)(x)` 与 `fp(x)` 等价，不需要去读一块函数体存储
                return address
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

    def _address_of(self, node: Any, scope: Scope) -> Any:
        """`&x`：变量取符号地址，函数取函数地址，其余走 lvalue。

        **特例**：``&((T *)0)->m`` 是 ``offsetof`` 的标准写法。它算出来的不是
        真地址（空指针加偏移在 ``Address`` 里没有合法表示），而是**整数偏移**，
        所以这里直接返回 ``offsetof`` 的结果。
        """
        if isinstance(node, c_ast.ID):
            return self._take_address(scope, node.name)
        if isinstance(node, c_ast.StructRef) and node.type == "->":
            offset = self._offsetof_null_base(node, scope)
            if offset is not None:
                return offset
        return self.lvalue(node, scope)

    def _offsetof_null_base(self, node: c_ast.StructRef, scope: Scope) -> int | None:
        """``&((T *)0)->m`` → 成员偏移；基址不是空指针时返回 None。"""
        base = self.eval(node.name, scope)
        if not isinstance(base, Address) or not base.is_null:
            return None
        owner = self.infer(node.name, scope)
        if not isinstance(owner, PointerType):
            return None
        target = owner.target
        if not isinstance(target, (StructType, UnionType)) or not target.is_complete:
            return None
        return target.offsetof(node.field.name)

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
            # 指针之间强转在 Phase A 只是换解释，值不变；但**整数 0 要变成空指针**，
            # 否则 `&((T *)0)->m`（offsetof 的写法）会因为"基地址不是指针"失败。
            return convert_value(value, target)
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
            return c_div(a, b)
        return a / b
    if op == "%":
        return c_mod(int(a), int(b))
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
