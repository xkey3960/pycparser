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
from super_execute.domain.entities.symbol import TypedefSymbol
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

        #: 折不成常量的全局初值：``(变量名, 初值表达式)``，按声明顺序。
        #: 由解释器在所有翻译单元装载完之后统一求值。
        self.deferred_initializers: list[tuple[str, Any]] = []

    def load(self, scope: Scope, file_ast: c_ast.FileAST) -> list[Any]:
        """装载一个翻译单元，返回逐个声明产生的符号。"""
        produced: list[Any] = []
        for node in file_ast.ext:
            symbol = self.load_node(scope, node)
            if symbol is not None:
                produced.append(symbol)
        return produced

    def load_node(self, scope: Scope, node: Any) -> Any:
        if isinstance(node, c_ast.Typedef):
            return self._typedef(scope, node)
        if isinstance(node, c_ast.FuncDef):
            return self._function(scope, node.decl)
        if isinstance(node, c_ast.Decl):
            return self._decl(scope, node)
        if isinstance(node, (c_ast.Pragma, c_ast.StaticAssert)):
            return None  # pragma 无运行时语义；_Static_assert 留给编译期检查
        raise UnsupportedTypeError(f"还没支持的顶层节点: {type(node).__name__}")

    # ---- 各类声明 ----

    def _typedef(self, scope: Scope, node: c_ast.Typedef) -> TypedefSymbol:
        builder = TypeBuilder(self._resolver, scope)
        ctype = builder.build(node.type)

        # 跨文件重复 typedef（头文件内容被各文件展开）→ 相同就静默去重
        existing = scope.ordinary.local(node.name)
        if isinstance(existing, TypedefSymbol) and types_equivalent(
            existing.ctype, ctype
        ):
            return existing

        symbol = TypedefSymbol(node.name, ctype)
        scope.declare(symbol)
        return symbol

    def _function(self, scope: Scope, decl: c_ast.Decl) -> Any:
        builder = TypeBuilder(self._resolver, scope)
        ctype = builder.build(decl.type)
        if not isinstance(ctype, FunctionType):
            raise UnsupportedTypeError(f"'{decl.name}' 不是函数声明")
        return self._declare_func(scope, decl.name, ctype, self._linkage(scope, decl))

    def _decl(self, scope: Scope, decl: c_ast.Decl) -> Any:
        builder = TypeBuilder(self._resolver, scope)

        if not decl.name:
            # 裸类型（`struct S { ... };`）：只登记标签，不产生变量
            builder.build(decl.type)
            return None

        ctype = builder.build(decl.type)
        if isinstance(ctype, FunctionType):
            return self._declare_func(
                scope, decl.name, ctype, self._linkage(scope, decl)
            )

        # 能折叠的初值当场算掉；折不动（比如 `int g = helper();`）就记下来，
        # 等所有翻译单元装载完再求值——那时函数表才齐。
        initial = None
        if decl.init is not None:
            initial = fold(decl.init, scope, self._resolver)
            if initial is None:
                self.deferred_initializers.append((decl.name, decl.init))

        return self._declare_var(
            scope,
            decl.name,
            ctype,
            initial=initial,
            linkage=self._linkage(scope, decl),
        )

    # ---- 细节 ----

    def _linkage(self, scope: Scope, decl: c_ast.Decl) -> Linkage:
        """只有文件作用域的符号才有链接属性；块内 static 暂按普通局部处理。"""
        if scope.kind is not ScopeKind.FILE:
            return Linkage.NONE
        storage = decl.storage or []
        return Linkage.INTERNAL if "static" in storage else Linkage.EXTERNAL
