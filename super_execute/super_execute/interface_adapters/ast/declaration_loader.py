"""把一个翻译单元（``FileAST``）的顶层声明装进运行时。

这一层是"外面的世界"与"用例"的接缝：它认识 pycparser 的节点形状，用例不认识。
所以所有 ``isinstance(node, c_ast.Xxx)`` 的判断都只出现在这里和
``type_builder``，下游一律是领域对象。

只处理**声明与定义**；函数体、表达式、语句都留给后面的求值器。已经能装下
真实 C 文件里绝大部分顶层内容：

    typedef / struct / union / enum 定义与前向声明
    全局变量（含 static 的内部链接、常量初值）
    函数原型与函数定义（只登记签名）

不支持的会显式报错，而不是悄悄跳过——静默跳过会让后面出现"未定义的符号"，
而真正的病因在三步之前。
"""

from __future__ import annotations

from typing import Any

from pycparser import c_ast

from super_execute.application.ports.function_table_port import FunctionTablePort
from super_execute.application.ports.memory_port import MemoryPort
from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.application.use_cases.functions import DeclareFunction
from super_execute.application.use_cases.variables import DeclareVariable
from super_execute.domain.entities.c_types import FunctionType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import TypedefSymbol, VariableSymbol
from super_execute.domain.exceptions import UnsupportedTypeError
from super_execute.domain.services.equivalence import types_equivalent
from super_execute.domain.value_objects import Linkage, ScopeKind
from super_execute.interface_adapters.ast.const_eval import fold
from super_execute.interface_adapters.ast.type_builder import TypeBuilder


class DeclarationLoader:
    """把 ``FileAST`` 的顶层节点逐条变成用例调用。"""

    __slots__ = (
        "_memory",
        "_resolver",
        "_declare_var",
        "_declare_func",
        "deferred_initializers",
        "tag_registry",
        "conflicts",
    )

    def __init__(
        self,
        memory: MemoryPort,
        resolver: TypeResolverPort,
        functions: FunctionTablePort,
    ) -> None:
        self._memory = memory
        self._resolver = resolver
        self._declare_var = DeclareVariable(memory)
        self._declare_func = DeclareFunction(functions)

        #: 折不成常量的全局初值：``(目标作用域, 变量名, 初值表达式)``，按声明顺序。
        #: 由解释器在所有翻译单元装载完之后统一求值。
        self.deferred_initializers: list[tuple[Scope, str, Any]] = []

        #: 登记过的标签 ``(kind, 名字) -> CType``。惰性模式下类型可能只注册未布局，
        #: 兼容层要靠它投影 ``g_types.lookup_tag``。
        self.tag_registry: dict[tuple[str, str], Any] = {}

        #: 非致命的冲突（同名 typedef 类型不同等）。旧实现在非 strict 模式下
        #: 只打印告警并保留先定义的那个。
        self.conflicts: list[str] = []

    def load(
        self, scope: Scope, file_ast: c_ast.FileAST, unit: Scope | None = None
    ) -> list[Any]:
        """装载一个翻译单元，返回逐个声明产生的符号。

        ``scope`` 是**共享**作用域（外部符号、typedef、标签都进这里）；
        ``unit`` 是该文件自己的那一层，只用来放 ``static`` 符号。
        不传 ``unit`` 时退化成"全部进共享作用域"——旧的单作用域行为，
        单测与简单场景仍然按这个走。
        """
        produced: list[Any] = []
        for node in file_ast.ext:
            symbol = self.load_node(scope, node, unit)
            if symbol is not None:
                produced.append(symbol)
        return produced

    def load_node(self, scope: Scope, node: Any, unit: Scope | None = None) -> Any:
        if isinstance(node, c_ast.Typedef):
            return self._typedef(scope, node)
        if isinstance(node, c_ast.FuncDef):
            return self._function(scope, node.decl, unit)
        if isinstance(node, c_ast.Decl):
            return self._decl(scope, node, unit)
        if isinstance(node, (c_ast.Pragma, c_ast.StaticAssert)):
            return None  # pragma 无运行时语义；_Static_assert 留给编译期检查
        raise UnsupportedTypeError(f"还没支持的顶层节点: {type(node).__name__}")

    # ---- 各类声明 ----

    def _typedef(self, scope: Scope, node: c_ast.Typedef) -> TypedefSymbol:
        builder = TypeBuilder(self._resolver, scope, self.tag_registry)
        ctype = builder.build(node.type)

        existing = scope.ordinary.local(node.name)
        if isinstance(existing, TypedefSymbol):
            if types_equivalent(existing.ctype, ctype):
                # 跨文件重复 typedef（头文件内容被各文件展开）→ 静默去重
                return existing
            # 同名但类型不同：C 里是错误，但旧实现非 strict 只告警、保留先定义的
            # 那个。这里记成"冲突"而不是硬错误，由 Interpreter 按 strict 决定
            # 是报错还是打印告警。
            self.conflicts.append(
                f"typedef '{node.name}' 冲突：已有 '{existing.ctype.name}'，"
                f"新来 '{ctype.name}'（保留先定义的）"
            )
            return existing

        symbol = TypedefSymbol(node.name, ctype)
        scope.declare(symbol)
        return symbol

    def _function(
        self, scope: Scope, decl: c_ast.Decl, unit: Scope | None = None
    ) -> Any:
        builder = TypeBuilder(self._resolver, scope, self.tag_registry)
        ctype = builder.build(decl.type)
        if not isinstance(ctype, FunctionType):
            raise UnsupportedTypeError(f"'{decl.name}' 不是函数声明")
        linkage = self._linkage(scope, decl)
        target = _binding_scope(scope, unit, linkage)
        return self._declare_func(target, decl.name, ctype, linkage)

    def _decl(self, scope: Scope, decl: c_ast.Decl, unit: Scope | None = None) -> Any:
        builder = TypeBuilder(self._resolver, scope, self.tag_registry)

        if not decl.name:
            # 裸类型（`struct S { ... };`）：只登记标签，不产生变量
            builder.build(decl.type)
            return None

        ctype = builder.build(decl.type)
        linkage = self._linkage(scope, decl)
        target = _binding_scope(scope, unit, linkage)

        if isinstance(ctype, FunctionType):
            return self._declare_func(target, decl.name, ctype, linkage)

        # `extern int g;`（不带初值）只是**引用**已有全局，不是又定义了一个
        if "extern" in (decl.storage or []) and decl.init is None:
            existing = target.find(decl.name)
            if isinstance(existing, VariableSymbol):
                return existing

        # 能折叠的初值当场算掉；折不动（比如 `int g = helper();`）就记下来，
        # 等所有翻译单元装载完再求值——那时函数表才齐。
        initial = None
        if decl.init is not None:
            initial = fold(decl.init, scope, self._resolver)
            if initial is None:
                self.deferred_initializers.append((target, decl.name, decl.init))

        return self._declare_var(
            target,
            decl.name,
            ctype,
            initial=initial,
            linkage=linkage,
        )

    # ---- 细节 ----

    def _linkage(self, scope: Scope, decl: c_ast.Decl) -> Linkage:
        """只有文件作用域的符号才有链接属性；块内 static 暂按普通局部处理。"""
        if scope.kind is not ScopeKind.FILE:
            return Linkage.NONE
        storage = decl.storage or []
        return Linkage.INTERNAL if "static" in storage else Linkage.EXTERNAL


def _binding_scope(scope: Scope, unit: Scope | None, linkage: Linkage) -> Scope:
    """这个符号该绑到哪一层：static 进翻译单元，其余进共享作用域。"""
    if unit is None:
        return scope
    return unit if linkage is Linkage.INTERNAL else scope
