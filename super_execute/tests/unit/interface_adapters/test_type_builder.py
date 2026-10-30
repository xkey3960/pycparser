"""TypeBuilder：C 的声明符 → CType。

C 的类型藏在声明符的形状里，这是适配器最容易做错的地方——下面每个用例都对应
一种形状，用真实的 pycparser 解析结果验证。
"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    FunctionType,
    PointerType,
    StructType,
    UnionType,
)
from super_execute.domain.entities.symbol import TypedefSymbol
from super_execute.domain.exceptions import (
    InvalidTypeError,
    UndefinedTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.services.builtin_types import (
    INT,
    UNSIGNED_LONG,
)
from super_execute.domain.value_objects import TagKind
from super_execute.interface_adapters.ast.type_builder import TypeBuilder


class TestBaseTypes:
    def test_builtin(self, builder, decl_type):
        assert builder.build(decl_type("int x;")) is INT

    def test_multi_specifier(self, builder, decl_type):
        assert builder.build(decl_type("unsigned long x;")) is UNSIGNED_LONG

    def test_typedef_reference(self, builder, decl_type):
        builder.scope.declare(TypedefSymbol("MyInt", INT))
        assert builder.build(decl_type("typedef int MyInt; MyInt x;", -1)) is INT

    def test_unknown_type_name(self, builder, decl_type):
        """解析器认识这个 typedef（源码里有），但解析视角里没登记。"""
        with pytest.raises(UndefinedTypeError):
            builder.build(decl_type("typedef int Hidden; Hidden x;", -1))


class TestDerivedTypes:
    def test_pointer(self, builder, decl_type):
        ctype = builder.build(decl_type("int *p;"))
        assert isinstance(ctype, PointerType)
        assert ctype.target is INT
        assert ctype.sizeof() == 4

    def test_pointer_to_pointer(self, builder, decl_type):
        ctype = builder.build(decl_type("int **p;"))
        assert isinstance(ctype.target, PointerType)

    def test_array(self, builder, decl_type):
        ctype = builder.build(decl_type("int a[3];"))
        assert isinstance(ctype, ArrayType)
        assert ctype.count == 3
        assert ctype.sizeof() == 12

    def test_multidimensional_array(self, builder, decl_type):
        ctype = builder.build(decl_type("int a[2][3];"))
        assert (ctype.count, ctype.element.count) == (2, 3)
        assert ctype.sizeof() == 24

    def test_array_of_pointers(self, builder, decl_type):
        ctype = builder.build(decl_type("int *a[3];"))
        assert isinstance(ctype.element, PointerType)

    def test_pointer_to_array(self, builder, decl_type):
        ctype = builder.build(decl_type("int (*p)[4];"))
        assert isinstance(ctype, PointerType)
        assert isinstance(ctype.target, ArrayType)
        assert ctype.target.count == 4

    def test_flexible_array(self, builder, decl_type):
        """弹性数组成员长度未定，走 count=None。"""
        builder.build(decl_type("struct S { int n; char data[]; } s;"))
        s = builder.scope.require_tag("S").ctype
        assert s.member("data").ctype.count is None

    def test_non_constant_dimension_rejected(self, builder, decl_type):
        with pytest.raises(UnsupportedTypeError, match="整型常量"):
            builder.build(decl_type("int a[N];"))


class TestFunctionTypes:
    def test_simple_prototype(self, builder, decl_type):
        ctype = builder.build(decl_type("int add(int a, int b);"))
        assert isinstance(ctype, FunctionType)
        assert ctype.ret is INT
        assert ctype.param_types == (INT, INT)
        assert ctype.variadic is False

    def test_void_parameter_list(self, builder, decl_type):
        """`int f(void)` 没有参数——void 不是真参数。"""
        ctype = builder.build(decl_type("int f(void);"))
        assert ctype.param_types == ()

    def test_variadic(self, builder, decl_type):
        ctype = builder.build(decl_type("int printf(char *fmt, ...);"))
        assert ctype.variadic is True
        assert len(ctype.param_types) == 1

    def test_mixed_param_types(self, builder, decl_type):
        ctype = builder.build(decl_type("int f(char c, short s, int **p);"))
        assert [t.name for t in ctype.param_types] == ["char", "short int", "int * *"]


class TestRecords:
    def test_struct_with_members(self, builder, decl_type):
        ctype = builder.build(decl_type("struct P { short a; int b; } s;"))
        assert isinstance(ctype, StructType)
        assert (ctype.sizeof(), ctype.alignof()) == (8, 4)
        assert [ctype.offsetof(x) for x in "ab"] == [0, 4]

    def test_struct_tag_registered(self, builder, decl_type):
        builder.build(decl_type("struct P { int a; } s;"))
        tag = builder.scope.require_tag("P")
        assert tag.tag_kind is TagKind.STRUCT
        assert tag.ctype.is_complete

    def test_self_referential_struct(self, builder, decl_type):
        """`struct Node { struct Node *next; }` —— 标签必须先登记再定义成员。"""
        builder.build(decl_type("struct Node { int v; struct Node *next; } n;"))
        node = builder.scope.require_tag("Node").ctype
        assert node.sizeof() == 8
        assert node.member("next").ctype.target is node

    def test_forward_declaration_then_definition(self, builder, decl_type):
        builder.build(decl_type("struct S;"))
        forward = builder.scope.require_tag("S").ctype
        assert not forward.is_complete

        builder.build(decl_type("struct S { int a; } s;"))
        assert builder.scope.require_tag("S").ctype is forward
        assert forward.is_complete and forward.sizeof() == 4

    def test_union(self, builder, decl_type):
        ctype = builder.build(decl_type("union U { int i; double d; } u;"))
        assert isinstance(ctype, UnionType)
        assert (ctype.sizeof(), ctype.alignof()) == (8, 8)

    def test_anonymous_struct_not_registered(self, builder, decl_type):
        ctype = builder.build(decl_type("struct { int a; } x;"))
        assert isinstance(ctype, StructType)
        assert ctype.tag is None
        assert builder.scope.find_tag("") is None

    def test_nested_struct_member(self, builder, decl_type):
        builder.build(
            decl_type("struct Out { char head; struct In { int y; } inner; } o;")
        )
        outer = builder.scope.require_tag("Out").ctype
        assert outer.offsetof("inner") == 4
        assert outer.sizeof() == 8

    def test_bitfield_width_is_folded(self, builder, decl_type):
        """`int a : 4 + 4` 的宽度要折成 8（宽度必须是常量表达式）。"""
        ctype = builder.build(decl_type("struct B { int a : 4 + 4; int b : 3; } e;"))
        assert [member.bit_width for member in ctype.members] == [8, 3]
        assert ctype.sizeof() == 4  # 打包进同一个 32 位单元（gcc 同）

    def test_non_constant_bitfield_width_rejected(self, builder, decl_type):
        with pytest.raises(UnsupportedTypeError, match="常量"):
            builder.build(decl_type("int n; struct B { int a : n; } b;", 1))

    def test_empty_struct_rejected(self, builder, decl_type):
        with pytest.raises(InvalidTypeError, match="至少需要一个具名成员"):
            builder.build(decl_type("struct E { } e;"))


class TestEnums:
    def test_auto_increment_values(self, builder, decl_type):
        ctype = builder.build(decl_type("enum Color { RED, GREEN, BLUE } c;"))
        assert ctype.constants == {"RED": 0, "GREEN": 1, "BLUE": 2}

    def test_explicit_values_and_continuation(self, builder, decl_type):
        ctype = builder.build(decl_type("enum E { A = 5, B, C = 10, D } e;"))
        assert ctype.constants == {"A": 5, "B": 6, "C": 10, "D": 11}

    def test_negative_value(self, builder, decl_type):
        ctype = builder.build(decl_type("enum E { NEG = -3 } e;"))
        assert ctype.constants == {"NEG": -3}

    def test_constants_injected_into_scope(self, builder, decl_type):
        builder.build(decl_type("enum E { A, B } e;"))
        assert builder.scope.require("A").value == 0
        assert builder.scope.require("B").value == 1

    def test_enum_size_is_int(self, builder, decl_type):
        ctype = builder.build(decl_type("enum E { A } e;"))
        assert (ctype.sizeof(), ctype.alignof()) == (4, 4)

    def test_constant_expression_values(self, builder, decl_type):
        """枚举值可以是常量表达式，并且能引用前面的枚举常量。"""
        ctype = builder.build(decl_type("enum E { A = 1 + 1, B = A * 3 } e;"))
        assert ctype.constants == {"A": 2, "B": 6}

    def test_sizeof_enumerator(self, builder, decl_type):
        ctype = builder.build(decl_type("enum E { A = sizeof(int) } e;"))
        assert ctype.constants == {"A": 4}

    def test_truly_non_constant_enumerator_rejected(self, builder, decl_type):
        """枚举值引用了变量 → 折不动 → 明确报错（不是悄悄当 0）。"""
        with pytest.raises(UnsupportedTypeError, match="整型常量"):
            builder.build(decl_type("int x; enum E { A = x } e;", 1))


class TestTagScope:
    def test_same_tag_name_in_different_scopes(self, builder, decl_type, empty_scope):
        """同名标签在不同作用域是不同类型——上一轮的核心结论在适配器层复验。"""
        from super_execute.domain.entities.scope import Scope
        from super_execute.domain.value_objects import ScopeKind

        inner = Scope(2, ScopeKind.BLOCK, empty_scope)
        inner_builder = TypeBuilder(builder.resolver, inner)

        builder.build(decl_type("struct P { int a; } x;"))
        inner_builder.build(decl_type("struct P { int a; int b; int c; } y;"))

        assert builder.scope.require_tag("P").ctype.sizeof() == 4
        assert inner.require_tag("P").ctype.sizeof() == 12
