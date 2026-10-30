"""隐式类型转换（TYPE-2）：值流入某个类型时该变成什么。

C 里"值流入类型"的地方比想象的多：初始化、赋值、复合赋值、传参、返回。
最容易漏的是浮点转整型（要向零截断）。

**故意没做的**：窄化截断。Phase A 用 Python 整数存值，`char c = 300` 不会回绕
成 44——那是 Phase B 换成字节存储之后自然发生的事。这条在 conversions 的
docstring 里记着，测试里也钉住了当前行为。
"""

from super_execute.domain.entities.c_types import (
    ArrayType,
    EnumType,
    Member,
    PointerType,
    StructType,
)
from super_execute.domain.services.builtin_types import BOOL, CHAR, DOUBLE, INT
from super_execute.domain.services.conversions import (
    array_to_pointer,
    convert_value,
    integer_promote,
    usual_arithmetic_convert,
)
from super_execute.domain.value_objects import NULL_ADDRESS, Address, AddressRegion


class TestIntegerConversion:
    def test_float_truncates_toward_zero(self):
        assert convert_value(3.7, INT) == 3
        assert convert_value(-3.7, INT) == -3

    def test_int_to_float(self):
        assert convert_value(3, DOUBLE) == 3.0
        assert isinstance(convert_value(3, DOUBLE), float)

    def test_bool_normalizes(self):
        assert convert_value(5, BOOL) == 5  # Phase A 不做位宽截断
        assert convert_value(0.9, BOOL) == 0

    def test_enum_stores_as_int(self):
        assert convert_value(2, EnumType("E", {"A": 0})) == 2

    def test_void_returns_none(self):
        from super_execute.domain.services.builtin_types import VOID

        assert convert_value(5, VOID) is None


class TestPointerConversion:
    def test_zero_becomes_null(self):
        converted = convert_value(0, PointerType(INT))
        assert converted is NULL_ADDRESS
        assert converted.is_null

    def test_address_passes_through(self):
        address = Address(AddressRegion.SCOPE, 1, 8)
        assert convert_value(address, PointerType(INT)) == address

    def test_address_to_int_uses_packed(self):
        address = Address(AddressRegion.SCOPE, 1, 8)
        assert convert_value(address, INT) == address.packed


class TestAggregateConversion:
    def test_struct_value_untouched(self):
        """复合值原样返回；真正的拷贝发生在写入槽位时。"""
        point = StructType("P")
        point.define([Member("x", INT)])
        value = {"x": 1}
        assert convert_value(value, point) is value

    def test_array_value_untouched(self):
        assert convert_value([1, 2], ArrayType(INT, 2)) == [1, 2]


class TestTypeLevelRules:
    def test_integer_promotion(self):
        assert integer_promote(CHAR) is INT
        assert integer_promote(DOUBLE) is DOUBLE

    def test_enum_promotes_to_int(self):
        assert integer_promote(EnumType("E", {"A": 0})) is INT

    def test_usual_conversion_picks_wider(self):
        assert usual_arithmetic_convert(CHAR, INT) is INT
        assert usual_arithmetic_convert(INT, DOUBLE) is DOUBLE

    def test_array_decays_to_pointer(self):
        decayed = array_to_pointer(ArrayType(INT, 3))
        assert isinstance(decayed, PointerType)
        assert decayed.target is INT

    def test_non_array_unchanged_by_decay(self):
        assert array_to_pointer(INT) is INT
