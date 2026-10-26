"""符号实体：五类绑定各自的命名空间与"有没有存储"。"""

import pytest

from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    FunctionSymbol,
    ObjectSymbol,
    TagSymbol,
    TypedefSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import InvalidSymbolError
from super_execute.domain.value_objects import (
    Address,
    AddressRegion,
    Linkage,
    NamespaceKind,
    SymbolKind,
    TagKind,
)


def _scope_addr(scope_id=1, offset=0):
    return Address(AddressRegion.SCOPE, scope_id, offset)


def _func_addr(function_id=0):
    return Address(AddressRegion.FUNCTION, 0, function_id)


class TestNamespaces:
    """命名空间归属决定"谁和谁能冲突"。"""

    def test_variable_and_function_share_ordinary(self):
        var = VariableSymbol("x", _scope_addr())
        func = FunctionSymbol("f", _func_addr())
        assert var.namespace is NamespaceKind.ORDINARY
        assert func.namespace is NamespaceKind.ORDINARY

    def test_typedef_and_enum_constant_share_ordinary(self):
        """typedef 名和枚举常量都在普通标识符命名空间——所以它们会和变量撞名。"""
        assert TypedefSymbol("T", ctype=None).namespace is NamespaceKind.ORDINARY
        assert ConstantSymbol("N", 3).namespace is NamespaceKind.ORDINARY

    def test_tag_goes_to_tag_namespace(self):
        """标签是另一个命名空间：struct Point 与变量 Point 可以共存。"""
        assert TagSymbol("Point", TagKind.STRUCT).namespace is NamespaceKind.TAGS


class TestStorage:
    """有没有存储决定 `&` 能不能作用于它（UC-08）。"""

    def test_variable_has_storage(self):
        var = VariableSymbol("x", _scope_addr())
        assert var.has_storage is True
        assert var.address == _scope_addr()

    def test_function_has_storage(self):
        """函数的地址就是函数指针的值——不再用"函数名字符串"当指针。"""
        func = FunctionSymbol("f", _func_addr())
        assert func.has_storage is True
        assert func.address == _func_addr()

    @pytest.mark.parametrize("symbol", [
        TypedefSymbol("T", ctype=None),
        ConstantSymbol("N", 3),
        TagSymbol("S", TagKind.STRUCT),
    ])
    def test_type_bindings_have_no_storage(self, symbol):
        """`&T`（typedef）和 `&N`（枚举常量）在 C 里都是非法的。"""
        assert symbol.has_storage is False
        assert symbol.address is None


class TestAddressRegion:
    """地址必须落在与该符号匹配的内存区。"""

    def test_variable_rejects_function_address(self):
        with pytest.raises(InvalidSymbolError, match="SCOPE"):
            VariableSymbol("x", _func_addr())

    def test_function_rejects_scope_address(self):
        with pytest.raises(InvalidSymbolError, match="FUNCTION"):
            FunctionSymbol("f", _scope_addr())

    def test_address_must_be_value_object(self):
        with pytest.raises(InvalidSymbolError, match="Address"):
            VariableSymbol("x", ("var", "scope", "x"))


class TestValidation:
    def test_empty_name_rejected(self):
        with pytest.raises(InvalidSymbolError, match="非空"):
            VariableSymbol("", _scope_addr())

    def test_non_string_name_rejected(self):
        with pytest.raises(InvalidSymbolError):
            VariableSymbol(123, _scope_addr())

    def test_linkage_type_checked(self):
        with pytest.raises(InvalidSymbolError, match="链接属性"):
            VariableSymbol("x", _scope_addr(), linkage="static")

    def test_object_symbol_is_an_intermediate_base(self):
        """ObjectSymbol 没有绑定的区号，直接实例化必须报错而不是静默通过。"""
        with pytest.raises(InvalidSymbolError, match="中间基类"):
            ObjectSymbol("x", _scope_addr())

    def test_tag_kind_checked(self):
        with pytest.raises(InvalidSymbolError, match="标签种类"):
            TagSymbol("S", "struct")


class TestIdentity:
    def test_kind_matches_class(self):
        assert VariableSymbol("x", _scope_addr()).kind is SymbolKind.VARIABLE
        assert FunctionSymbol("f", _func_addr()).kind is SymbolKind.FUNCTION
        assert TypedefSymbol("T", None).kind is SymbolKind.TYPEDEF
        assert ConstantSymbol("N", 0).kind is SymbolKind.ENUM_CONSTANT
        assert TagSymbol("S", TagKind.UNION).kind is SymbolKind.TAG

    def test_repr_carries_name_and_address(self):
        text = repr(VariableSymbol("x", _scope_addr(2, 8)))
        assert "x" in text and "SCOPE" in text

    def test_enum_constant_keeps_value(self):
        assert ConstantSymbol("N", 7).value == 7

    def test_linkage_defaults_to_none(self):
        assert VariableSymbol("x", _scope_addr()).linkage is Linkage.NONE
