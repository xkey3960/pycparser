"""默认值：刚分配的存储里应该是什么。

C 的自动变量是"不确定值"，解释器不能真留空洞——否则
``struct Point s; s.a = 1;`` 会失败（成员容器还不存在），
而这段代码在 C 里是合法的。所以这里零初始化。
"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    EnumType,
    FunctionType,
    Member,
    PointerType,
    StructType,
    UnionType,
)
from super_execute.domain.exceptions import InvalidTypeError
from super_execute.domain.services.builtin_types import BOOL, CHAR, DOUBLE, INT
from super_execute.domain.services.defaults import default_value
from super_execute.domain.value_objects import NULL_ADDRESS


class TestScalars:
    def test_integer_zero(self):
        assert default_value(INT) == 0
        assert default_value(CHAR) == 0

    def test_float_zero(self):
        """0 == 0.0 在 Python 里为真，所以必须额外断言类型。"""
        value = default_value(DOUBLE)
        assert isinstance(value, float)
        assert value == 0.0

    def test_bool_zero(self):
        assert default_value(BOOL) == 0

    def test_enum_zero(self):
        assert default_value(EnumType("Color", {"RED": 0})) == 0

    def test_pointer_is_null(self):
        assert default_value(PointerType(INT)) is NULL_ADDRESS


class TestAggregates:
    def test_array_of_scalars(self):
        assert default_value(ArrayType(INT, 3)) == [0, 0, 0]

    def test_array_of_pointers(self):
        assert default_value(ArrayType(PointerType(CHAR), 2)) == [
            NULL_ADDRESS,
            NULL_ADDRESS,
        ]

    def test_struct_members_all_zeroed(self):
        s = StructType("S")
        s.define([Member("a", CHAR), Member("b", INT), Member("c", DOUBLE)])
        assert default_value(s) == {"a": 0, "b": 0, "c": 0.0}

    def test_nested_struct(self):
        inner = StructType("In")
        inner.define([Member("x", INT)])
        outer = StructType("Out")
        outer.define([Member("in", inner), Member("flag", CHAR)])
        assert default_value(outer) == {"in": {"x": 0}, "flag": 0}

    def test_union_gets_every_member(self):
        """Phase A 用 dict 存联合体，所以每个成员都要有初始值（都从 0 开始）。"""
        u = UnionType("U")
        u.define([Member("i", INT), Member("d", DOUBLE)])
        assert default_value(u) == {"i": 0, "d": 0.0}

    def test_flexible_array_member_is_empty(self):
        s = StructType("Fam")
        s.define([Member("n", INT), Member("data", ArrayType(CHAR))])
        assert default_value(s) == {"n": 0, "data": []}


class TestErrors:
    def test_incomplete_struct(self):
        with pytest.raises(InvalidTypeError, match="尚未定义"):
            default_value(StructType("Forward"))

    def test_function_type(self):
        with pytest.raises(InvalidTypeError, match="函数类型"):
            default_value(FunctionType(INT))
