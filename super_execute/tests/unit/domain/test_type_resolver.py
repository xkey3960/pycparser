"""类型名解析：把 Scope 和类型系统接起来。

这一层是上一轮实证 2（两个函数各自 `struct P`）的最终出口：解析必须落在
**离当前作用域最近**的标签上，否则两个函数会共用同一个布局。
"""

import pytest

from super_execute.domain.entities.c_types import (
    EnumType,
    Member,
    StructType,
    UnionType,
)
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import (
    TagSymbol,
    TypedefSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import (
    InvalidSymbolError,
    InvalidTypeError,
    UndefinedTypeError,
)
from super_execute.domain.services.builtin_types import (
    DOUBLE,
    INT,
    UNSIGNED_LONG,
)
from super_execute.domain.services.type_resolver import ScopeTypeResolver
from super_execute.domain.value_objects import (
    Address,
    AddressRegion,
    ScopeKind,
    TagKind,
)


def _struct(tag, *names):
    ctype = StructType(tag)
    ctype.define([Member(name, INT) for name in names])
    return ctype


# file_scope / function_scope 夹具见 conftest.py


class TestBuiltinResolution:
    def test_single_keyword(self, file_scope):
        assert ScopeTypeResolver(file_scope).resolve(["int"]) == INT

    def test_multi_specifier(self, file_scope):
        assert ScopeTypeResolver(file_scope).resolve(["unsigned", "long"]) == UNSIGNED_LONG

    def test_order_independent(self, file_scope):
        assert ScopeTypeResolver(file_scope).resolve(["long", "unsigned"]) == UNSIGNED_LONG

    def test_long_double_is_undefined(self, file_scope):
        """long double 本轮未支持：必须报错，不能悄悄当成 double。"""
        with pytest.raises(UndefinedTypeError, match="long double"):
            ScopeTypeResolver(file_scope).resolve(["long", "double"])


class TestTypedefResolution:
    def test_resolves_typedef(self, function_scope):
        function_scope.declare(TypedefSymbol("MyInt", INT))
        assert ScopeTypeResolver(function_scope).resolve(["MyInt"]) == INT

    def test_finds_typedef_through_chain(self, file_scope, function_scope):
        file_scope.declare(TypedefSymbol("Global", DOUBLE))
        assert ScopeTypeResolver(function_scope).resolve(["Global"]) == DOUBLE

    def test_inner_typedef_shadows_outer(self, file_scope, function_scope):
        file_scope.declare(TypedefSymbol("T", INT))
        function_scope.declare(TypedefSymbol("T", DOUBLE))
        assert ScopeTypeResolver(function_scope).resolve(["T"]) == DOUBLE
        assert ScopeTypeResolver(file_scope).resolve(["T"]) == INT

    def test_missing_name(self, function_scope):
        with pytest.raises(UndefinedTypeError, match="未定义的类型名"):
            ScopeTypeResolver(function_scope).resolve(["NoSuch"])

    def test_variable_is_not_a_type(self, function_scope):
        """普通命名空间里同名的是变量时，不能当类型用。"""
        function_scope.declare(
            VariableSymbol("Foo", Address(AddressRegion.SCOPE, 2, 0)))
        with pytest.raises(InvalidTypeError, match="不是类型名"):
            ScopeTypeResolver(function_scope).resolve(["Foo"])

    def test_placeholder_ctype_rejected_at_construction(self):
        """非 CType 的 ctype 在构造符号时就该被挡住（review 批次 B4）。"""
        with pytest.raises(InvalidSymbolError, match="ctype"):
            TypedefSymbol("Bad", "int")

    def test_unresolved_typedef_rejected_by_resolver(self, file_scope):
        """ctype 为 None（尚未解析）的 typedef 不能被当成类型用。"""
        file_scope.declare(TypedefSymbol("Pending", None))
        with pytest.raises(InvalidTypeError, match="没有绑定有效的 CType"):
            ScopeTypeResolver(file_scope).resolve(["Pending"])


class TestTagResolution:
    def test_resolves_struct_tag(self, function_scope):
        function_scope.declare(TagSymbol("P", TagKind.STRUCT, _struct("P", "x", "y")))
        resolved = ScopeTypeResolver(function_scope).resolve(["struct", "P"])
        assert resolved.sizeof() == 8

    def test_resolves_union_and_enum(self, function_scope):
        u = UnionType("U")
        u.define([Member("a", INT), Member("b", DOUBLE)])
        function_scope.declare(TagSymbol("U", TagKind.UNION, u))
        function_scope.declare(TagSymbol("E", TagKind.ENUM, EnumType("E", {"A": 0})))
        resolver = ScopeTypeResolver(function_scope)
        assert resolver.resolve(["union", "U"]).sizeof() == 8
        assert resolver.resolve(["enum", "E"]).sizeof() == 4

    def test_tag_searched_through_chain(self, file_scope, function_scope):
        file_scope.declare(TagSymbol("P", TagKind.STRUCT, _struct("P", "x")))
        assert ScopeTypeResolver(function_scope).resolve(["struct", "P"]).sizeof() == 4

    def test_missing_tag_name(self, function_scope):
        with pytest.raises(InvalidTypeError, match="缺少标签名"):
            ScopeTypeResolver(function_scope).resolve(["struct"])

    def test_undefined_tag(self, function_scope):
        with pytest.raises(UndefinedTypeError, match="未定义的标签"):
            ScopeTypeResolver(function_scope).resolve(["struct", "Nope"])

    def test_extra_words_after_tag_rejected(self, function_scope):
        """["struct","P","junk"] 不能被当成 struct P 放过。"""
        function_scope.declare(TagSymbol("P", TagKind.STRUCT, _struct("P", "x")))
        with pytest.raises(InvalidTypeError, match="多余的词"):
            ScopeTypeResolver(function_scope).resolve(["struct", "P", "junk"])

    def test_tag_kind_mismatch(self, function_scope):
        function_scope.declare(TagSymbol("P", TagKind.STRUCT, _struct("P", "x")))
        with pytest.raises(InvalidTypeError, match="struct 标签"):
            ScopeTypeResolver(function_scope).resolve(["union", "P"])

    def test_placeholder_tag_ctype_rejected(self, function_scope):
        function_scope.declare(TagSymbol("P", TagKind.STRUCT, None))
        with pytest.raises(InvalidTypeError, match="没有绑定有效的 CType"):
            ScopeTypeResolver(function_scope).resolve(["struct", "P"])


class TestEmpiricalAnchor:
    def test_sibling_functions_resolve_their_own_struct_p(self):
        """实证 2 的最终出口：两个函数各自的 `struct P` 必须解析成不同布局。

        旧实现两次 `sizeof(struct P)` 都拿到第一个定义（4+4=8），正确是 4+12=16。
        """
        file_scope = Scope(1, ScopeKind.FILE)
        f1 = Scope(2, ScopeKind.FUNCTION, file_scope)
        f2 = Scope(3, ScopeKind.FUNCTION, file_scope)

        f1.declare(TagSymbol("P", TagKind.STRUCT, _struct("P", "x")))
        f2.declare(TagSymbol("P", TagKind.STRUCT, _struct("P", "a", "b", "c")))

        assert ScopeTypeResolver(f1).resolve(["struct", "P"]).sizeof() == 4
        assert ScopeTypeResolver(f2).resolve(["struct", "P"]).sizeof() == 12
        assert (ScopeTypeResolver(f1).resolve(["struct", "P"]).sizeof()
                + ScopeTypeResolver(f2).resolve(["struct", "P"]).sizeof()) == 16

    def test_block_typedef_does_not_leak_into_resolution(self):
        """实证 1 的最终出口：出块后 `T` 必须解析回外层的 int。"""
        file_scope = Scope(1, ScopeKind.FILE)
        file_scope.declare(TypedefSymbol("T", INT))
        block = Scope(2, ScopeKind.BLOCK, file_scope)
        block.declare(TypedefSymbol("T", DOUBLE))

        assert ScopeTypeResolver(block).resolve(["T"]) == DOUBLE
        assert ScopeTypeResolver(file_scope).resolve(["T"]) == INT


class TestValidation:
    def test_empty_type_name(self, file_scope):
        with pytest.raises(InvalidTypeError, match="空类型名"):
            ScopeTypeResolver(file_scope).resolve([])

    def test_scope_required(self):
        with pytest.raises(InvalidTypeError, match="Scope"):
            ScopeTypeResolver("not a scope")

    def test_unparsable_multi_word(self, file_scope):
        with pytest.raises(UndefinedTypeError, match="未定义的类型"):
            ScopeTypeResolver(file_scope).resolve(["Foo", "Bar"])
