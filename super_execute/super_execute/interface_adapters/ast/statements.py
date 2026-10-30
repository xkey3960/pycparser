"""跑一个 C 程序：语句、作用域、函数调用。

这一层把前面所有东西接起来——类型系统、内存、用例、适配器。它认识 pycparser 的
节点（所以属于适配层），但真正干活的是用例与领域对象。

**控制流用异常实现**：`return` / `break` / `continue` 各自抛一个信号，由能处理它的
语句捕获。旧实现也是这个思路（`ReturnException` 等），好处是不必给执行器维护
"当前循环/函数"的显式栈。

作用域用 :class:`ScopeSession` 开关：每次进块都真的建一块存储，出块销毁。
代价是 8 位 id 空间的限制——函数调用占 2 个 id（函数作用域 + 函数体块），
所以递归深度上限约 127。递归再深会报 id 用尽，而不是静默出错。
"""

from __future__ import annotations

from typing import Any

from pycparser import c_ast

from super_execute.application.ports.memory_port import MemoryPort
from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.application.use_cases.scope_session import ScopeSession
from super_execute.application.use_cases.variables import DeclareVariable
from super_execute.domain.entities.c_types import ArrayType, BasicType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import TypedefSymbol
from super_execute.domain.exceptions import DomainError, UnsupportedTypeError
from super_execute.domain.value_objects import ScopeKind
from super_execute.interface_adapters.ast.const_eval import fold
from super_execute.interface_adapters.ast.declaration_loader import check_static_assert
from super_execute.interface_adapters.ast.evaluator import Evaluator
from super_execute.interface_adapters.ast.type_builder import TypeBuilder


class ReturnSignal(Exception):
    """``return``：一路穿到函数调用点。"""

    def __init__(self, value: Any) -> None:
        self.value = value


class BreakSignal(Exception):
    """``break``：由最近的循环/switch 捕获。"""


class ContinueSignal(Exception):
    """``continue``：由最近的循环捕获。"""


class GotoSignal(Exception):
    """``goto``：向外层块传播，直到找到同名标签。

    为什么用异常而不是"跳转表"：C 的标签是**函数作用域**的，`goto` 可以从
    循环里跳到外层块。逐层块捕获、找不到就继续往外抛，正好复现这个语义，
    也不需要给每个块预先建一张表。
    """

    def __init__(self, name: str) -> None:
        super().__init__(name)
        self.name = name


_STATEMENT_TYPES = (
    c_ast.Compound,
    c_ast.Decl,
    c_ast.DeclList,
    c_ast.If,
    c_ast.While,
    c_ast.DoWhile,
    c_ast.For,
    c_ast.Switch,
    c_ast.Case,
    c_ast.Default,
    c_ast.Return,
    c_ast.Break,
    c_ast.Continue,
    c_ast.Goto,
    c_ast.Label,
    c_ast.Typedef,
    c_ast.Pragma,
    c_ast.EmptyStatement,
)


def _produces_value(node: Any) -> bool:
    """这条语句会不会产生值（语句表达式取最后一条表达式的值）。"""
    return not isinstance(node, _STATEMENT_TYPES)


def _switch_items(stmt: Any) -> list[Any]:
    """switch 体内的一串项（``case``/``default``/普通语句平铺在一起）。"""
    if isinstance(stmt, c_ast.Compound):
        return list(stmt.block_items or [])
    return [stmt] if stmt is not None else []


def _case_body(item: Any) -> list[Any]:
    """``case``/``default`` 标签挂的那几条语句；普通语句就是它自己。"""
    if isinstance(item, (c_ast.Case, c_ast.Default)):
        return list(item.stmts or [])
    return [item]


def _case_matches(expr: Any, value: Any, scope: Scope, resolver: Any) -> bool:
    """这个 case 标签是否匹配。

    两种形状：普通常量（``case 3:``）和 GNU 的**范围**（``case 1 ... 5:``，
    解析成 ``RangeExpression``）。范围按闭区间判断。
    """
    if type(expr).__name__ == "RangeExpression":
        low = fold(expr.first, scope, resolver)
        high = fold(expr.last, scope, resolver)
        if not isinstance(low, int) or not isinstance(high, int):
            raise UnsupportedTypeError("case 范围的端点必须是整型常量表达式")
        return low <= value <= high

    label = fold(expr, scope, resolver)
    if not isinstance(label, int):
        raise UnsupportedTypeError(
            f"case 标签必须是整型常量表达式: {type(expr).__name__}"
        )
    return label == value


class StatementExecutor:
    """语句执行器。"""

    __slots__ = ("_evaluator", "_memory", "_resolver", "_session", "_declare")

    def __init__(
        self,
        evaluator: Evaluator,
        memory: MemoryPort,
        resolver: TypeResolverPort,
        session: ScopeSession,
    ) -> None:
        self._evaluator = evaluator
        self._memory = memory
        self._resolver = resolver
        self._session = session
        self._declare = DeclareVariable(memory)

    # ==================== 入口 ====================

    def execute(self, node: Any, scope: Scope) -> None:
        """语句执行入口：顺带把出错位置记到异常上（与求值器同一套）。"""
        try:
            self._execute(node, scope)
        except DomainError as error:
            raise error.with_coord(getattr(node, "coord", None)) from None

    def _execute(self, node: Any, scope: Scope) -> None:
        if node is None or isinstance(node, c_ast.EmptyStatement):
            return
        if isinstance(node, c_ast.Compound):
            self._compound(node, scope)
            return
        if isinstance(node, c_ast.Decl):
            self._declaration(node, scope)
            return
        if isinstance(node, c_ast.DeclList):
            for decl in node.decls:
                self._declaration(decl, scope)
            return
        if isinstance(node, c_ast.StaticAssert):
            # 函数体里的 _Static_assert 同样是编译期检查
            check_static_assert(node, scope, self._resolver)
            return
        if isinstance(node, c_ast.Switch):
            self._switch(node, scope)
            return
        if isinstance(node, c_ast.If):
            self._if(node, scope)
            return
        if isinstance(node, c_ast.While):
            self._while(node, scope)
            return
        if isinstance(node, c_ast.DoWhile):
            self._do_while(node, scope)
            return
        if isinstance(node, c_ast.For):
            self._for(node, scope)
            return
        if isinstance(node, c_ast.Return):
            raise ReturnSignal(
                None if node.expr is None else self._evaluator.eval(node.expr, scope)
            )
        if isinstance(node, c_ast.Break):
            raise BreakSignal()
        if isinstance(node, c_ast.Continue):
            raise ContinueSignal()
        if isinstance(node, c_ast.Goto):
            raise GotoSignal(node.name)
        if isinstance(node, c_ast.Label):
            # 顺序执行到标签 = 直接执行它挂的那条语句
            if node.stmt is not None:
                self.execute(node.stmt, scope)
            return
        if isinstance(node, (c_ast.FuncDef,)):
            return  # 声明阶段已处理，运行期没有动作
        if isinstance(node, c_ast.Typedef):
            self._typedef(node, scope)
            return
        if isinstance(node, c_ast.Pragma):
            return

        # 兜底：表达式语句（`i++;` / `f();` / `x = y;`）
        self._evaluator.eval(node, scope)

    # ==================== 语句 ====================

    def _compound(self, node: c_ast.Compound, scope: Scope) -> None:
        items = node.block_items or []
        # 本块里定义了哪些标签（跳到标签 = 从那条语句继续执行）
        labels = {
            item.name: index
            for index, item in enumerate(items)
            if isinstance(item, c_ast.Label)
        }

        block = self._session.open(ScopeKind.BLOCK, scope)
        try:
            index = 0
            while index < len(items):
                try:
                    self.execute(items[index], block)
                except GotoSignal as signal:
                    target = labels.get(signal.name)
                    if target is None:
                        raise  # 标签不在这一层，交给外层块
                    index = target
                    continue
                index += 1
        finally:
            self._session.close(block)

    def execute_expression(self, node: c_ast.Compound, scope: Scope) -> Any:
        """GNU 语句表达式 ``({ ... })``：执行一个块，返回最后一条表达式的值。

        块里可以有声明（``({ int a = 3; a + 4; })``），所以要用**新开的块作用域**，
        使得里面的变量不泄漏到外面。
        """
        items = list(node.block_items or [])
        block = self._session.open(ScopeKind.BLOCK, scope)
        try:
            for item in items[:-1]:
                self.execute(item, block)
            if not items:
                return None
            last = items[-1]
            if isinstance(last, c_ast.Compound):
                # 嵌套的语句表达式：`({ int a = 2; ({ a * 5; }); })` 里内层那个
                return self.execute_expression(last, block)
            if _produces_value(last):
                return self._evaluator.eval(last, block)
            self.execute(last, block)  # 最后一条不是表达式 → 语句表达式的值未定义
            return None
        finally:
            self._session.close(block)

    def _declaration(self, node: c_ast.Decl, scope: Scope) -> None:
        builder = TypeBuilder(self._resolver, scope)
        if not node.name:
            builder.build(node.type)  # 局部类型定义：只登记标签
            return

        ctype = builder.build(node.type)
        # `int a[] = {1,2,3};` 的长度由初始化器决定（C99 6.7.9p22）
        if (
            isinstance(node.init, c_ast.InitList)
            and isinstance(ctype, ArrayType)
            and ctype.count is None
        ):
            ctype = ctype.complete(len(node.init.exprs or []))

        initial = None
        if node.init is not None:
            initial = self._evaluator.eval_init(node.init, ctype, scope)
        self._declare(scope, node.name, ctype, initial)

    def _typedef(self, node: c_ast.Typedef, scope: Scope) -> None:
        """函数体内的 typedef（旧的扁平类型表正是漏在这里）。"""
        builder = TypeBuilder(self._resolver, scope)
        scope.declare(TypedefSymbol(node.name, builder.build(node.type)))

    def _switch(self, node: c_ast.Switch, scope: Scope) -> None:
        """``switch``：跳到匹配的 ``case``，然后**顺序往下执行**（fall-through）。

        C 的 switch 不是"分支表"，本质是"goto 到某个标签"。所以这里：
        1. 先算出该从哪一条 ``case`` 开始（没有匹配的就去 ``default``）；
        2. 从那里开始**一路执行后面的语句**，直到 ``break`` 或走完。
        中间那些 ``case`` 标签没有额外作用——它们只是标记位置。
        """
        value = self._evaluator.eval(node.cond, scope)
        items = _switch_items(node.stmt)
        start = self._switch_start(items, value, scope)
        if start is None:
            return  # 既没匹配也没有 default：整段跳过

        block = self._session.open(ScopeKind.BLOCK, scope)
        try:
            for item in items[start:]:
                for statement in _case_body(item):
                    self.execute(statement, block)
        except BreakSignal:
            return  # break 只跳出 switch；continue/goto 继续往外传
        finally:
            self._session.close(block)

    def _switch_start(self, items: list[Any], value: Any, scope: Scope) -> int | None:
        """找到该从哪一项开始执行：先看匹配的 case，再看 default。"""
        default_index: int | None = None
        for index, item in enumerate(items):
            if isinstance(item, c_ast.Default):
                if default_index is None:
                    default_index = index
                continue
            if not isinstance(item, c_ast.Case):
                continue
            if _case_matches(item.expr, value, scope, self._resolver):
                return index
        return default_index

    def _if(self, node: c_ast.If, scope: Scope) -> None:
        if self._evaluator.eval(node.cond, scope):
            self.execute(node.iftrue, scope)
        elif node.iffalse is not None:
            self.execute(node.iffalse, scope)

    def _while(self, node: c_ast.While, scope: Scope) -> None:
        while self._evaluator.eval(node.cond, scope):
            try:
                self.execute(node.stmt, scope)
            except ContinueSignal:
                continue
            except BreakSignal:
                return

    def _do_while(self, node: c_ast.DoWhile, scope: Scope) -> None:
        while True:
            try:
                self.execute(node.stmt, scope)
            except ContinueSignal:
                pass
            except BreakSignal:
                return
            if not self._evaluator.eval(node.cond, scope):
                return

    def _for(self, node: c_ast.For, scope: Scope) -> None:
        # for 自己的作用域：`for (int i = 0; ...)` 里的 i 不该漏到外面
        loop_scope = self._session.open(ScopeKind.BLOCK, scope)
        try:
            if node.init is not None:
                if isinstance(node.init, c_ast.DeclList):
                    for decl in node.init.decls:
                        self._declaration(decl, loop_scope)
                else:
                    self._evaluator.eval(node.init, loop_scope)

            while node.cond is None or self._evaluator.eval(node.cond, loop_scope):
                try:
                    self.execute(node.stmt, loop_scope)
                except ContinueSignal:
                    pass
                except BreakSignal:
                    return
                if node.next is not None:
                    self._evaluator.eval(node.next, loop_scope)
        finally:
            self._session.close(loop_scope)


def _is_void(ctype: Any) -> bool:
    return isinstance(ctype, BasicType) and not ctype.is_complete


__all__ = [
    "BreakSignal",
    "ContinueSignal",
    "ReturnSignal",
    "StatementExecutor",
]
