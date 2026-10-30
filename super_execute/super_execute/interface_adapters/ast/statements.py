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
from super_execute.domain.entities.c_types import BasicType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import TypedefSymbol
from super_execute.domain.exceptions import DomainError
from super_execute.domain.value_objects import ScopeKind
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
        block = self._session.open(ScopeKind.BLOCK, scope)
        try:
            for item in node.block_items or []:
                self.execute(item, block)
        finally:
            self._session.close(block)

    def _declaration(self, node: c_ast.Decl, scope: Scope) -> None:
        builder = TypeBuilder(self._resolver, scope)
        if not node.name:
            builder.build(node.type)  # 局部类型定义：只登记标签
            return

        ctype = builder.build(node.type)
        initial = None if node.init is None else self._evaluator.eval(node.init, scope)
        self._declare(scope, node.name, ctype, initial)

    def _typedef(self, node: c_ast.Typedef, scope: Scope) -> None:
        """函数体内的 typedef（旧的扁平类型表正是漏在这里）。"""
        builder = TypeBuilder(self._resolver, scope)
        scope.declare(TypedefSymbol(node.name, builder.build(node.type)))

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
