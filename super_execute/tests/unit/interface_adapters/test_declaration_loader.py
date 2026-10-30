"""DeclarationLoader：把真实的 C 源码顶层声明装进运行时。

这一层是"外面的世界"与用例的接缝——所以下面全部用真正的 pycparser 解析结果，
不构造假 AST。
"""

import pytest

from super_execute.domain.entities.c_types import FunctionType, StructType
from super_execute.domain.entities.symbol import (
    FunctionSymbol,
    TypedefSymbol,
    VariableSymbol,
)
from super_execute.domain.value_objects import Linkage

SOURCE = """
typedef unsigned long size_t;
struct Point { short a; int b; };
struct Point g_point;
static int g_count = 3;
int add(int x, int y);
int main(void) { return 0; }
enum Color { RED, GREEN = 5, BLUE };
struct Node { int v; struct Node *next; };
typedef struct Point PointT;
"""


@pytest.fixture
def loaded(runtime, parse):
    runtime["loader"].load(runtime["scope"], parse(SOURCE))
    return runtime


class TestTypedefs:
    def test_typedef_symbol(self, loaded):
        symbol = loaded["scope"].require("size_t")
        assert isinstance(symbol, TypedefSymbol)
        assert symbol.ctype.name == "unsigned long int"

    def test_typedef_to_struct(self, loaded):
        symbol = loaded["scope"].require("PointT")
        assert symbol.ctype is loaded["scope"].require_tag("Point").ctype


class TestTags:
    def test_struct_defined(self, loaded):
        point = loaded["scope"].require_tag("Point").ctype
        assert isinstance(point, StructType)
        assert point.is_complete and point.sizeof() == 8

    def test_self_referential_struct(self, loaded):
        node = loaded["scope"].require_tag("Node").ctype
        assert node.member("next").ctype.target is node

    def test_enum_registered(self, loaded):
        color = loaded["scope"].require_tag("Color").ctype
        assert color.constants == {"RED": 0, "GREEN": 5, "BLUE": 6}


class TestVariables:
    def test_global_allocated(self, loaded):
        symbol = loaded["scope"].require("g_point")
        assert isinstance(symbol, VariableSymbol)
        assert symbol.ctype.sizeof() == 8
        assert loaded["memory"].read(symbol.address, symbol.ctype) == {"a": 0, "b": 0}

    def test_alignment_between_globals(self, loaded):
        point = loaded["scope"].require("g_point")
        count = loaded["scope"].require("g_count")
        assert (point.address.offset, count.address.offset) == (0, 8)

    def test_initializer(self, loaded):
        symbol = loaded["scope"].require("g_count")
        assert loaded["memory"].read(symbol.address, symbol.ctype) == 3

    def test_linkage(self, loaded):
        assert loaded["scope"].require("g_point").linkage is Linkage.EXTERNAL
        assert loaded["scope"].require("g_count").linkage is Linkage.INTERNAL

    def test_naked_struct_definition_registers_no_variable(self, loaded):
        """`struct Point { ... };` 只有标签，没有变量。"""
        assert "Point" not in loaded["scope"].ordinary


class TestFunctions:
    def test_prototype_registered(self, loaded):
        symbol = loaded["scope"].require("add")
        assert isinstance(symbol, FunctionSymbol)
        assert isinstance(symbol.ctype, FunctionType)
        assert symbol.ctype.param_types != ()

    def test_definition_registered(self, loaded):
        assert isinstance(loaded["scope"].require("main"), FunctionSymbol)

    def test_addresses_in_function_region(self, loaded):
        add = loaded["functions"].address_of("add")
        main = loaded["functions"].address_of("main")
        assert add.offset == 0 and main.offset == 1
        assert loaded["functions"].resolve(add).name == "add"

    def test_prototype_then_definition_reuses_address(self, runtime, parse):
        """先原型后定义：同名函数只占一个函数地址。"""
        runtime["loader"].load(runtime["scope"], parse("int f(int);"))
        first = runtime["functions"].address_of("f")
        runtime["loader"].load(runtime["scope"], parse("int f(int) { return 0; }"))
        second = runtime["functions"].address_of("f")
        assert first == second
        assert len(runtime["functions"]) == 1


class TestMultipleTranslationUnits:
    def test_same_global_across_units(self, runtime, parse):
        """两个翻译单元都声明 `int g;` 时，第二次会撞上已存在的符号。"""
        from super_execute.domain.exceptions import DuplicateSymbolError

        runtime["loader"].load(runtime["scope"], parse("int g;"))
        with pytest.raises(DuplicateSymbolError):
            runtime["loader"].load(runtime["scope"], parse("int g;"))

    def test_identical_typedef_across_units_is_deduped(self, runtime, parse):
        """头文件内容被两个文件各自展开 → 同一份 typedef 出现两次，应静默去重。"""
        source = "typedef struct Pt { int x; int y; } Pt;"
        first = runtime["loader"].load(runtime["scope"], parse(source))[0]
        second = runtime["loader"].load(runtime["scope"], parse(source))[0]

        assert first is second
        assert runtime["scope"].require("Pt").ctype.sizeof() == 8

    def test_conflicting_struct_definition(self, runtime, parse):
        from super_execute.domain.exceptions import InvalidTypeError

        runtime["loader"].load(runtime["scope"], parse("struct P { int a; };"))
        with pytest.raises(InvalidTypeError, match="重复定义"):
            runtime["loader"].load(
                runtime["scope"], parse("struct P { int a; int b; };")
            )


class TestInitializers:
    """能折叠的当场算掉，折不动的推迟到所有翻译单元装载完。"""

    def test_constant_expression_is_folded(self, runtime, parse):
        runtime["loader"].load(runtime["scope"], parse("int g = 1 + 2 * 3;"))
        symbol = runtime["scope"].require("g")
        assert runtime["memory"].read(symbol.address, symbol.ctype) == 7

    def test_constant_referencing_enum(self, runtime, parse):
        runtime["loader"].load(
            runtime["scope"], parse("enum E { A = 5 }; int g = A * 2;")
        )
        symbol = runtime["scope"].require("g")
        assert runtime["memory"].read(symbol.address, symbol.ctype) == 10

    def test_non_constant_initializer_is_deferred(self, runtime, parse):
        runtime["loader"].load(runtime["scope"], parse("int f(void); int g = f();"))
        names = [name for _, name, _ in runtime["loader"].deferred_initializers]
        assert names == ["g"]

    def test_zero_value_before_initialization(self, runtime, parse):
        """推迟的初值在装载阶段只是零值，求值发生在 run()。"""
        runtime["loader"].load(runtime["scope"], parse("int f(void); int g = f();"))
        symbol = runtime["scope"].require("g")
        assert runtime["memory"].read(symbol.address, symbol.ctype) == 0

    def test_initializer_list_still_unsupported(self, runtime, parse):
        runtime["loader"].load(runtime["scope"], parse("int a[2] = {1, 2};"))
        interpreter_symbol = runtime["scope"].require("a")
        assert interpreter_symbol is not None  # 声明成功，初值推迟
        assert len(runtime["loader"].deferred_initializers) == 1


class TestSkipped:
    def test_pragma_is_ignored(self, runtime, parse):
        ast = parse("#pragma once\nint g;\n")
        symbols = runtime["loader"].load(runtime["scope"], ast)
        assert [s.name for s in symbols if hasattr(s, "name")] == ["g"]
