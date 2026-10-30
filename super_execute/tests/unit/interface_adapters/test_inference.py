"""TypeInferencer：表达式 → C 类型。

`sizeof`、指针步长、成员类型都靠这一层。它认识 pycparser 节点（所以属于适配层），
但产出的全是领域 CType。
"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    PointerType,
)
from super_execute.domain.exceptions import (
    InvalidTypeError,
    UndefinedSymbolError,
)
from super_execute.domain.services.builtin_types import (
    CHAR,
    DOUBLE,
    INT,
    SHORT,
    UNSIGNED_LONG,
)


def infer(runtime, expr, source):
    return runtime["evaluator"].infer(expr(source), runtime["scope"])


class TestConstants:
    def test_int_literal(self, world, expr):
        assert infer(world, expr, "42") is INT

    def test_char_literal(self, world, expr):
        assert infer(world, expr, "'a'") is CHAR


class TestIdentifiers:
    def test_variable(self, world, expr):
        assert infer(world, expr, "i") is INT

    def test_struct_variable(self, world, expr):
        assert infer(world, expr, "s") is world["point"]

    def test_array_variable(self, world, expr):
        ctype = infer(world, expr, "arr")
        assert isinstance(ctype, ArrayType) and ctype.count == 3

    def test_undefined(self, world, expr):
        with pytest.raises(UndefinedSymbolError):
            infer(world, expr, "nope")


class TestArithmetic:
    def test_int_plus_int(self, world, expr):
        assert infer(world, expr, "i + 1") is INT

    def test_char_promoted(self, world, expr):
        """char + int → int（整型提升）。"""
        assert infer(world, expr, "c + i") is INT

    def test_int_plus_double(self, world, expr):
        assert infer(world, expr, "i + d") is DOUBLE

    def test_comparison_is_int(self, world, expr):
        assert infer(world, expr, "i < 3") is INT

    def test_logical_is_int(self, world, expr):
        assert infer(world, expr, "i && 1") is INT

    def test_shift_keeps_left_type(self, world, expr):
        assert infer(world, expr, "i << 2") is INT


class TestPointers:
    def test_pointer_plus_int_is_pointer(self, world, expr):
        ctype = infer(world, expr, "pi + 1")
        assert isinstance(ctype, PointerType) and ctype.target is INT

    def test_int_plus_pointer(self, world, expr):
        ctype = infer(world, expr, "1 + pi")
        assert isinstance(ctype, PointerType)

    def test_dereference(self, world, expr):
        assert infer(world, expr, "*pi") is INT

    def test_address_of(self, world, expr):
        ctype = infer(world, expr, "&i")
        assert isinstance(ctype, PointerType) and ctype.target is INT

    def test_pointer_minus_pointer_is_int(self, world, expr):
        assert infer(world, expr, "pi - pi") is INT

    def test_pointer_arithmetic_on_wrong_op(self, world, expr):
        with pytest.raises(InvalidTypeError):
            infer(world, expr, "pi * 2")


class TestMembersAndElements:
    def test_member_type(self, world, expr):
        assert infer(world, expr, "s.b") is INT

    def test_arrow_member_type(self, world, expr):
        assert infer(world, expr, "p->b") is INT

    def test_array_element_type(self, world, expr):
        assert infer(world, expr, "arr[0]") is INT

    def test_pointer_index_type(self, world, expr):
        assert infer(world, expr, "pi[1]") is INT

    def test_nested_member(self, world, expr):
        assert infer(world, expr, "p->a") is SHORT


class TestOtherForms:
    def test_assignment_takes_lvalue_type(self, world, expr):
        assert infer(world, expr, "i = 5") is INT

    def test_cast(self, world, expr):
        assert infer(world, expr, "(char)i") is CHAR

    def test_sizeof_is_unsigned_long(self, world, expr):
        assert infer(world, expr, "sizeof(int)") is UNSIGNED_LONG

    def test_ternary(self, world, expr):
        assert infer(world, expr, "1 ? i : i") is INT

    def test_comma_returns_last(self, world, expr):
        assert infer(world, expr, "(i, d)") is DOUBLE

    def test_increment(self, world, expr):
        assert infer(world, expr, "++i") is INT

    def test_string_literal_is_char_array(self, world, expr):
        """``"hello"`` 的类型是 ``char[6]``——含结尾 NUL。"""
        assert infer(world, expr, '"hello"').name == "char[6]"
