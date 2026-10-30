"""解释器门面：装载翻译单元 → 调用 main。

到这一层，"新架构能不能跑 C"终于可以回答。它的职责只有三件：

1. **装载**：开文件作用域，登记类型/全局/函数签名，同时记住函数体（AST 节点）；
2. **调用**：按函数符号建函数作用域、绑形参、执行函数体；
3. **入口**：跑 ``main`` 并返回它的返回值。

函数体存在这一层（``dict[str, c_ast.FuncDef]``），不塞进领域符号——
``FunctionSymbol`` 只该知道"名字、类型、地址"，不该抱着 AST。这也是为什么
旧实现里 ``Function`` 类同时持有 ``body`` 会让人分不清层次。
"""

from __future__ import annotations

from typing import Any, Sequence

from pycparser import c_ast

from super_execute.application.ports.memory_port import MemoryPort
from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.application.use_cases.scope_session import ScopeSession
from super_execute.application.use_cases.variables import DeclareVariable
from super_execute.domain.entities.c_types import FunctionType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import FunctionSymbol
from super_execute.domain.exceptions import (
    LinkError,
    UndefinedSymbolError,
    UnsupportedTypeError,
)
from super_execute.domain.services.defaults import default_value
from super_execute.domain.services.conversions import array_to_pointer
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.services.type_resolver import TypeResolver
from super_execute.domain.value_objects import ScopeKind
from super_execute.frameworks.memory import FunctionTable, SlotMemory
from super_execute.interface_adapters.ast.declaration_loader import DeclarationLoader
from super_execute.interface_adapters.ast.evaluator import Evaluator
from super_execute.interface_adapters.ast.statements import (
    ReturnSignal,
    StatementExecutor,
)
from super_execute.interface_adapters.ast.type_builder import TypeBuilder


class Interpreter:
    """把 AST 跑起来的门面（依赖全部可注入，便于测试替换内存实现）。"""

    def __init__(
        self,
        memory: MemoryPort | None = None,
        allocator: ScopeIdAllocator | None = None,
        functions: FunctionTable | None = None,
        resolver: TypeResolverPort | None = None,
    ) -> None:
        self._memory = memory if memory is not None else SlotMemory()
        self._allocator = allocator if allocator is not None else ScopeIdAllocator()
        self._functions = functions if functions is not None else FunctionTable()
        self._resolver = resolver if resolver is not None else TypeResolver()

        self._session = ScopeSession(self._allocator, self._memory)
        self._loader = DeclarationLoader(self._memory, self._resolver, self._functions)
        self._evaluator = Evaluator(self._memory, self._resolver, self._functions)
        self._executor = StatementExecutor(
            self._evaluator, self._memory, self._resolver, self._session
        )
        self._declare = DeclareVariable(self._memory)
        self._bodies: dict[str, c_ast.FuncDef] = {}
        self._globals: Scope | None = None

        # 函数调用要回到这里，用回填避免求值器与解释器互相依赖
        self._evaluator.set_call_handler(self._handle_call)

    # ==================== 装载 ====================

    @property
    def globals(self) -> Scope:
        if self._globals is None:
            raise LinkError("还没有装载任何翻译单元")
        return self._globals

    @property
    def memory(self) -> MemoryPort:
        return self._memory

    @property
    def functions(self) -> FunctionTable:
        return self._functions

    def load(self, file_ast: c_ast.FileAST) -> Scope:
        """装载一个翻译单元（可多次调用以支持多文件）。"""
        if self._globals is None:
            self._globals = self._session.open(ScopeKind.FILE)

        for node in file_ast.ext:
            if isinstance(node, c_ast.FuncDef):
                self._bodies[node.decl.name] = node

        self._loader.load(self._globals, file_ast)
        return self._globals

    # ==================== 运行 ====================

    def run(self, entry: str = "main") -> Any:
        """执行入口函数，返回它的返回值。"""
        return self.call(entry, ())

    def call(self, name: str, args: Sequence[Any], scope: Scope | None = None) -> Any:
        lookup = scope if scope is not None else self.globals
        symbol = lookup.find(name)
        if symbol is None:
            raise UndefinedSymbolError(f"未定义的函数 '{name}'")
        if not isinstance(symbol, FunctionSymbol):
            raise UnsupportedTypeError(f"'{name}' 不是函数（函数指针调用还没接）")
        if not isinstance(symbol.ctype, FunctionType):
            raise LinkError(f"'{name}' 没有函数类型")

        body = self._bodies.get(name)
        if body is None:
            raise LinkError(f"函数 '{name}' 只有声明没有定义")

        scope = self._session.open(ScopeKind.FUNCTION, self.globals)
        try:
            self._bind_parameters(scope, body, symbol.ctype, args)
            try:
                self._executor.execute(body.body, scope)
            except ReturnSignal as signal:
                return signal.value
            return None
        finally:
            self._session.close(scope)

    # ==================== 内部 ====================

    def _bind_parameters(
        self,
        scope: Scope,
        body: c_ast.FuncDef,
        ftype: FunctionType,
        args: Sequence[Any],
    ) -> None:
        params = _parameter_decls(body)
        builder = TypeBuilder(self._resolver, self.globals)

        for index, decl in enumerate(params):
            ctype = array_to_pointer(builder.build(decl.type))
            if index < len(args):
                value = args[index]
            else:
                value = default_value(ctype)  # 少传的参数按零值补
            self._declare(scope, decl.name, ctype, value)

        if len(args) > len(params) and not ftype.variadic:
            raise LinkError(
                f"'{body.decl.name}' 只接受 {len(params)} 个参数，传了 {len(args)} 个"
            )

    def _handle_call(self, node: c_ast.FuncCall, args: list[Any], scope: Scope) -> Any:
        if not isinstance(node.name, c_ast.ID):
            raise UnsupportedTypeError(
                "暂时只支持直接用函数名调用（函数指针调用还没接）"
            )
        return self.call(node.name.name, args, scope)


def _parameter_decls(body: c_ast.FuncDef) -> list[c_ast.Decl]:
    """取出有名字的形参声明（``f(void)`` 的 void 不算）。"""
    decl = body.decl
    if decl.type.args is None:
        return []
    return [p for p in decl.type.args.params if isinstance(p, c_ast.Decl) and p.name]
