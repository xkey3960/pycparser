"""AST 适配器测试的共享夹具。

这里要真的用 pycparser 解析源码——适配器存在的意义就是"认识真实的 AST 形状"，
用假的 AST 节点测等于自欺。源码都是无 ``#include`` 的片段，所以不必过 cpp。
"""

import pytest
from pycparser import c_ast
from pycparser.c_parser import CParser

from super_execute.application.use_cases import DeclareVariable
from super_execute.domain.entities.scope import Scope
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.services.type_resolver import TypeResolver
from super_execute.domain.value_objects import ScopeKind
from super_execute.frameworks.memory import FunctionTable, SlotMemory
from super_execute.interface_adapters.ast.declaration_loader import DeclarationLoader
from super_execute.interface_adapters.ast.evaluator import Evaluator
from super_execute.interface_adapters.ast.type_builder import TypeBuilder


@pytest.fixture
def parse():
    """把源码解析成 FileAST（等价于 pycparser 的 parse_file，但不过 cpp）。"""

    def _parse(source: str) -> c_ast.FileAST:
        return CParser().parse(source, "<test>")

    return _parse


@pytest.fixture
def decl_type(parse):
    """取第 index 个声明的**声明符**（类型节点），用来直接喂给 TypeBuilder。

    pycparser 需要先认识 typedef 名，所以引用 typedef 的片段必须把 typedef
    一起写进源码，再用 index 取最后一条。
    """

    def _decl_type(source: str, index: int = 0):
        node = parse(source).ext[index]
        if isinstance(node, c_ast.Typedef):
            return node.type
        if isinstance(node, c_ast.FuncDef):
            return node.decl.type
        return node.type

    return _decl_type


@pytest.fixture
def expr(parse):
    """把一段表达式塞进 ``return`` 里，取出那个表达式节点。"""

    def _expr(source: str):
        ast = parse(f"int __probe__(void) {{ return {source}; }}")
        return ast.ext[0].body.block_items[0].expr

    return _expr


@pytest.fixture
def empty_scope():
    return Scope(1, ScopeKind.FILE)


@pytest.fixture
def builder(empty_scope):
    return TypeBuilder(TypeResolver(), empty_scope)


@pytest.fixture
def runtime():
    """文件作用域 + 内存 + 函数表 + 装载器 + 求值器。"""
    memory = SlotMemory()
    allocator = ScopeIdAllocator()
    scope = allocator.open(ScopeKind.FILE)
    memory.create_scope(scope.scope_id)
    functions = FunctionTable()
    return {
        "scope": scope,
        "memory": memory,
        "functions": functions,
        "loader": DeclarationLoader(memory, TypeResolver(), functions),
        "declare": DeclareVariable(memory),
        "evaluator": Evaluator(memory, TypeResolver(), functions),
    }


@pytest.fixture
def world(runtime):
    """一套标准变量：标量 / 结构体 / 数组 / 指针。"""
    from super_execute.domain.entities.c_types import (
        ArrayType,
        Member,
        PointerType,
        StructType,
    )
    from super_execute.domain.entities.symbol import TagSymbol
    from super_execute.domain.services.builtin_types import CHAR, DOUBLE, INT, SHORT
    from super_execute.domain.value_objects import TagKind

    declare = runtime["declare"]
    scope = runtime["scope"]

    point = StructType("Point")
    point.define([Member("a", SHORT), Member("b", INT)])
    scope.declare(TagSymbol("Point", TagKind.STRUCT, point))

    declare(scope, "i", INT, initial=3)
    declare(scope, "c", CHAR, initial=1)
    declare(scope, "d", DOUBLE, initial=1.5)
    declare(scope, "s", point, initial={"a": 1, "b": 2})
    declare(scope, "arr", ArrayType(INT, 3), initial=[10, 20, 30])
    declare(scope, "pi", PointerType(INT), initial=None)
    declare(scope, "p", PointerType(point), initial=None)

    runtime["point"] = point
    return runtime
