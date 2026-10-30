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
from super_execute.domain.entities.c_types import FunctionType, PointerType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import FunctionSymbol, VariableSymbol
from super_execute.domain.exceptions import (
    DomainError,
    LinkError,
    NotAValueError,
    UndefinedLabelError,
    UndefinedSymbolError,
    UnsupportedTypeError,
)
from super_execute.domain.services.defaults import default_value
from super_execute.domain.services.conversions import array_to_pointer, convert_value
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.services.type_resolver import TypeResolver
from super_execute.domain.value_objects import Address, AddressRegion, ScopeKind
from super_execute.frameworks.memory import FunctionTable, SlotMemory
from super_execute.interface_adapters.ast.declaration_loader import DeclarationLoader
from super_execute.interface_adapters.ast.evaluator import Evaluator
from super_execute.interface_adapters.ast.statements import (
    GotoSignal,
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
        self._bodies: dict[str, tuple[c_ast.FuncDef, Scope]] = {}
        self._static_bodies: dict[tuple[int, str], tuple[c_ast.FuncDef, Scope]] = {}
        self._units: dict[str, Scope] = {}
        self._unit_symbols: dict[int, list[Any]] = {}
        self._globals: Scope | None = None
        self._globals_initialized = False
        self._call_stack: list[str] = []

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

    def load(self, file_ast: c_ast.FileAST, name: str | None = None) -> Scope:
        """装载一个翻译单元（可多次调用以支持多文件）。

        每个文件开一层 ``UNIT`` 作用域挂在全程序作用域下：``static`` 符号进这一层，
        外部符号进共享的全程序层。于是两个文件各自的 ``static int g;`` 天然互不
        相干（D6），而外部符号照旧互相可见。

        ``name`` 记住"这个单元对应哪个源文件"——兼容层要靠它把 static 符号按
        文件名投影出来（旧 API 的 ``g_static_funcs`` / ``g_static_globals``）。
        """
        if self._globals is None:
            self._globals = self._session.open(ScopeKind.FILE)

        unit = self._session.open(ScopeKind.UNIT, self._globals)
        produced: list[Any] = []
        for node in file_ast.ext:
            symbol = self._loader.load_node(self._globals, node, unit)
            if symbol is not None:
                produced.append(symbol)
            if not isinstance(node, c_ast.FuncDef) or symbol is None:
                continue
            # 函数体按"它属于哪个翻译单元"归档：
            #   外部函数——全程序唯一，名字就是键（同名取第一份，入口取第一个 main）
            #   static 函数——每个文件各有一份，用 (单元, 名字) 区分（D6）
            if _is_static(node):
                self._static_bodies[(unit.scope_id, node.decl.name)] = (node, unit)
            else:
                self._bodies.setdefault(node.decl.name, (node, unit))

        # 即便调用方没给文件名，也登记一个键——兼容层要靠它按单元投影 static 符号
        self._units[name if name is not None else f"unit#{unit.scope_id}"] = unit
        self._unit_symbols[unit.scope_id] = produced
        return self._globals

    # ---- 供兼容层投影用（只读） ----

    def unit_symbols(self, name: str) -> list[Any]:
        """某个源文件装载时产生的符号（不含跨文件共享的那些）。"""
        unit = self._units.get(name)
        if unit is None:
            return []
        return list(self._unit_symbols.get(unit.scope_id, []))

    def all_unit_symbols(self) -> dict[str, list[Any]]:
        """``{源文件名: 该文件产生的符号}``，按装载顺序。"""
        return {
            name: list(self._unit_symbols.get(unit.scope_id, []))
            for name, unit in self._units.items()
        }

    # ==================== 运行 ====================

    def run(self, entry: str = "main") -> Any:
        """执行入口函数，返回它的返回值。

        出错时按旧实现的习惯打一份报告到 stdout（``[error] 位置: 消息`` +
        调用链），再把异常抛出去——调用方既能看报告，也能按类型捕获。
        """
        try:
            return self.call(entry, ())
        except DomainError as error:
            self._report(error)
            raise

    def _report(self, error: DomainError) -> None:
        print(f"[error] {error}")
        chain = error.call_chain
        if chain:
            print("调用链: " + " → ".join(chain))

    def call(self, name: str, args: Sequence[Any], scope: Scope | None = None) -> Any:
        self._initialize_globals()
        lookup = scope if scope is not None else self.globals
        symbol = lookup.find(name)
        if symbol is None:
            raise UndefinedSymbolError(f"未定义的函数 '{name}'")
        if not isinstance(symbol, FunctionSymbol):
            raise UnsupportedTypeError(f"'{name}' 不是函数（函数指针调用还没接）")
        if not isinstance(symbol.ctype, FunctionType):
            raise LinkError(f"'{name}' 没有函数类型")

        # 先看这个名字是不是**本翻译单元的 static**：是就用这个单元的那份函数体
        unit = _unit_owning(lookup, symbol)
        if unit is not None:
            recorded = self._static_bodies.get((unit.scope_id, name))
        else:
            recorded = self._bodies.get(name)

        if recorded is None:
            raise LinkError(f"函数 '{name}' 只有声明没有定义")
        body, unit = recorded

        # 函数作用域挂在**它自己那个翻译单元**下：这样函数体能看见本文件的 static，
        # 也能沿链看到外部符号——正是 C 的作用域规则
        scope = self._session.open(ScopeKind.FUNCTION, unit)
        self._call_stack.append(name)
        try:
            self._bind_parameters(scope, body, symbol.ctype, args)
            try:
                self._executor.execute(body.body, scope)
            except ReturnSignal as signal:
                return convert_value(signal.value, symbol.ctype.ret)
            return None
        except DomainError as error:
            # 最内层先记下调用链；外层发现已有值就不再覆盖
            raise error.with_call_chain(list(self._call_stack)) from None
        except GotoSignal as signal:
            # 一路跳出函数体还没找到标签 → 这个函数里根本没有它
            raise UndefinedLabelError(f"未定义的标签 '{signal.name}'") from None
        finally:
            self._session.close(scope)
            self._call_stack.pop()

    def call_through(
        self, address: Any, args: Sequence[Any], scope: Scope | None = None
    ) -> Any:
        """按**函数地址**调用（函数指针）。

        函数名当值时就是它的地址，所以 ``fp = inc; fp(41)`` 与 ``inc(41)`` 走的是
        同一条路：从函数表把地址解析回符号，再按名字调用。
        """
        if (
            not isinstance(address, Address)
            or address.region is not AddressRegion.FUNCTION
        ):
            raise NotAValueError(f"函数指针的值不是函数地址: {address!r}")
        target = self._functions.resolve(address)
        return self.call(target.name, args, scope)

    # ==================== 内部 ====================

    def _initialize_globals(self) -> None:
        """把折不成常量的全局初值算掉（`int g = helper();` 这种）。

        必须在**所有**翻译单元装载完之后做：初值里可能调用另一个文件里的函数，
        那时函数表和函数体才齐。只做一次，并且先把标志置上——初始化过程中
        调用的函数会再进 ``call()``，不该递归触发初始化。
        """
        if self._globals_initialized or self._globals is None:
            return
        self._globals_initialized = True

        for target, name, expression in self._loader.deferred_initializers:
            symbol = target.find(name)
            if not isinstance(symbol, VariableSymbol) or symbol.ctype is None:
                raise LinkError(f"全局初值的目标 '{name}' 不是变量")
            # 在**它所属的那一层**求值：static 全局的初值要能看见本文件的符号
            value = self._evaluator.eval(expression, target)
            self._memory.write(symbol.address, value, symbol.ctype)

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
                # 实参按形参类型转换：`f(5)` 传给 `double` 形参要变成 5.0
                value = convert_value(args[index], ctype)
            else:
                value = default_value(ctype)  # 少传的参数按零值补
            self._declare(scope, decl.name, ctype, value)

        if len(args) > len(params) and not ftype.variadic:
            raise LinkError(
                f"'{body.decl.name}' 只接受 {len(params)} 个参数，传了 {len(args)} 个"
            )

    def _handle_call(self, node: c_ast.FuncCall, args: list[Any], scope: Scope) -> Any:
        if not isinstance(node.name, c_ast.ID):
            # `(*fp)(x)` / `table[i](x)`：先把被调表达式求成地址
            return self.call_through(
                self._evaluator.eval(node.name, scope), args, scope
            )

        symbol = scope.find(node.name.name)
        if isinstance(symbol, VariableSymbol) and _is_function_pointer(symbol.ctype):
            # `fp(x)` 里的 fp 是变量，不是函数名：读出它存的地址再调用
            return self.call_through(
                self._memory.read(symbol.address, symbol.ctype), args, scope
            )
        return self.call(node.name.name, args, scope)


def _is_static(node: c_ast.FuncDef) -> bool:
    return "static" in (node.decl.storage or [])


def _is_function_pointer(ctype: Any) -> bool:
    return isinstance(ctype, PointerType) and isinstance(ctype.target, FunctionType)


def _unit_owning(scope: Scope, symbol: Any) -> Scope | None:
    """符号如果是某个翻译单元的 static，返回那一层；外部符号返回 None。"""
    for candidate in scope.chain():
        if (
            candidate.kind is ScopeKind.UNIT
            and candidate.ordinary.local(getattr(symbol, "name", "")) is symbol
        ):
            return candidate
    return None


def _parameter_decls(body: c_ast.FuncDef) -> list[c_ast.Decl]:
    """取出有名字的形参声明（``f(void)`` 的 void 不算）。"""
    decl = body.decl
    if decl.type.args is None:
        return []
    return [p for p in decl.type.args.params if isinstance(p, c_ast.Decl) and p.name]
