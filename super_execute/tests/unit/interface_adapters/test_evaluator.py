"""Evaluator：值、地址（lvalue）、C 的运算语义。

这里最容易搞错的不是"算得对不对"，而是**C 与 Python 语义不同的地方**：
整型除法向零截断、取模与被除数同号、指针算术按元素大小缩放。
每一条都有对应用例。
"""

import pytest

from super_execute.domain.exceptions import (
    DivisionByZeroError,
    InvalidTypeError,
    OutOfBoundsError,
    UndefinedSymbolError,
    UnsupportedTypeError,
)


def ev(world, expr, source):
    return world["evaluator"].eval(expr(source), world["scope"])


class TestArithmetic:
    def test_precedence(self, world, expr):
        assert ev(world, expr, "1 + 2 * 3") == 7
        assert ev(world, expr, "(1 + 2) * 3") == 9

    def test_variables(self, world, expr):
        assert ev(world, expr, "i + 1") == 4

    def test_float_mix(self, world, expr):
        assert ev(world, expr, "i + d") == 4.5

    @pytest.mark.parametrize(
        "source,expected",
        [("7 / 2", 3), ("-7 / 2", -3), ("7 / -2", -3), ("-7 / -2", 3)],
    )
    def test_integer_division_truncates_toward_zero(
        self, world, expr, source, expected
    ):
        """Python 的 // 是向下取整，C 是向零截断——这是旧实现踩过的坑。"""
        assert ev(world, expr, source) == expected

    @pytest.mark.parametrize(
        "source,expected", [("7 % 3", 1), ("-7 % 3", -1), ("7 % -3", 1)]
    )
    def test_modulo_follows_dividend_sign(self, world, expr, source, expected):
        assert ev(world, expr, source) == expected

    def test_bitwise_and_shifts(self, world, expr):
        assert ev(world, expr, "1 << 4 | 3") == 19
        assert ev(world, expr, "12 & 10") == 8
        assert ev(world, expr, "12 ^ 10") == 6

    def test_unary(self, world, expr):
        assert ev(world, expr, "-i") == -3
        assert ev(world, expr, "~0") == -1
        assert ev(world, expr, "!0") == 1
        assert ev(world, expr, "!i") == 0


class TestComparisonAndLogic:
    @pytest.mark.parametrize(
        "source,expected",
        [("i == 3", 1), ("i != 3", 0), ("i < 4", 1), ("i >= 4", 0)],
    )
    def test_comparisons(self, world, expr, source, expected):
        assert ev(world, expr, source) == expected

    def test_logical(self, world, expr):
        assert ev(world, expr, "i && 1") == 1
        assert ev(world, expr, "0 || 0") == 0

    def test_short_circuit(self, world, expr):
        """`0 && (1/0)` 不能真去算右边。"""
        assert ev(world, expr, "0 && (i / 0)") == 0
        assert ev(world, expr, "1 || (i / 0)") == 1


class TestStructAndArray:
    def test_member_read(self, world, expr):
        assert ev(world, expr, "s.a") == 1
        assert ev(world, expr, "s.b") == 2

    def test_array_read(self, world, expr):
        assert ev(world, expr, "arr[0]") == 10
        assert ev(world, expr, "arr[1]") == 20
        assert ev(world, expr, "arr[i - 1]") == 30  # i == 3

    def test_member_write(self, world, expr):
        ev(world, expr, "s.b = 42")
        assert ev(world, expr, "s.b") == 42

    def test_array_write(self, world, expr):
        ev(world, expr, "arr[2] = 99")
        assert ev(world, expr, "arr[2]") == 99

    def test_compound_assignment(self, world, expr):
        ev(world, expr, "s.b += 5")
        assert ev(world, expr, "s.b") == 7
        ev(world, expr, "arr[0] *= 2")
        assert ev(world, expr, "arr[0]") == 20

    def test_out_of_range_index(self, world, expr):
        with pytest.raises(OutOfBoundsError):
            ev(world, expr, "arr[3]")


class TestPointers:
    @pytest.fixture(autouse=True)
    def _point_at(self, world, expr):
        """让 pi 指向 arr[0]，p 指向 s。"""
        evaluator = world["evaluator"]
        scope = world["scope"]
        evaluator.eval(expr("pi = &arr[0]"), scope)
        evaluator.eval(expr("p = &s"), scope)
        return world

    def test_dereference(self, world, expr):
        assert ev(world, expr, "*pi") == 10
        assert ev(world, expr, "(*p).b") == 2

    def test_arrow(self, world, expr):
        assert ev(world, expr, "p->b") == 2
        ev(world, expr, "p->b = 8")
        assert ev(world, expr, "s.b") == 8

    def test_pointer_index(self, world, expr):
        assert ev(world, expr, "pi[1]") == 20

    def test_pointer_arithmetic_scales_by_element(self, world, expr):
        assert ev(world, expr, "pi + 1") == ev(world, expr, "&arr[1]")
        assert (
            ev(world, expr, "p + 1") == ev(world, expr, "&s") + world["point"].sizeof()
        )

    def test_pointer_difference(self, world, expr):
        assert ev(world, expr, "&arr[2] - &arr[0]") == 2

    def test_pointer_equality(self, world, expr):
        assert ev(world, expr, "pi == &arr[0]") == 1
        assert ev(world, expr, "pi != &arr[1]") == 1

    def test_null_comparison(self, world, expr):
        assert ev(world, expr, "pi == 0") == 0
        ev(world, expr, "pi = 0")
        assert ev(world, expr, "pi == 0") == 1


class TestAddressOf:
    def test_variable(self, world, expr):
        address = ev(world, expr, "&i")
        assert address == world["scope"].require("i").address

    def test_member(self, world, expr):
        s = world["scope"].require("s")
        assert ev(world, expr, "&s.b") == s.address + world["point"].offsetof("b")

    def test_element(self, world, expr):
        arr = world["scope"].require("arr")
        assert ev(world, expr, "&arr[2]") == arr.address + 8

    def test_dereference_roundtrip(self, world, expr):
        ev(world, expr, "s.b = 77")
        assert ev(world, expr, "*(&s.b)") == 77


class TestIncrement:
    def test_postfix_returns_old(self, world, expr):
        assert ev(world, expr, "i++") == 3
        assert ev(world, expr, "i") == 4

    def test_prefix_returns_new(self, world, expr):
        assert ev(world, expr, "++i") == 4
        assert ev(world, expr, "i") == 4

    def test_decrement(self, world, expr):
        assert ev(world, expr, "--i") == 2

    def test_pointer_step(self, world, expr):
        ev(world, expr, "pi = &arr[0]")
        moved = ev(world, expr, "pi++")
        assert moved == ev(world, expr, "&arr[0]")
        assert ev(world, expr, "pi") == ev(world, expr, "&arr[1]")


class TestSizeofAndCast:
    def test_sizeof_type(self, world, expr):
        assert ev(world, expr, "sizeof(int)") == 4
        assert ev(world, expr, "sizeof(struct Point)") == 8

    def test_sizeof_expression(self, world, expr):
        assert ev(world, expr, "sizeof(s)") == 8
        assert ev(world, expr, "sizeof(arr)") == 12

    def test_sizeof_does_not_evaluate(self, world, expr):
        """`sizeof(i++)` 不能真的自增。"""
        assert ev(world, expr, "sizeof(i++)") == 4
        assert ev(world, expr, "i") == 3

    def test_cast_int(self, world, expr):
        assert ev(world, expr, "(char)i") == 3

    def test_cast_pointer_is_identity(self, world, expr):
        address = ev(world, expr, "&i")
        ev(world, expr, "pi = &i")
        assert ev(world, expr, "(int*)pi") == address


class TestOtherForms:
    def test_ternary(self, world, expr):
        assert ev(world, expr, "i > 0 ? 10 : 20") == 10

    def test_comma(self, world, expr):
        assert ev(world, expr, "(i = 5, i + 1)") == 6


class TestErrors:
    def test_undefined_identifier(self, world, expr):
        with pytest.raises(UndefinedSymbolError):
            ev(world, expr, "nope")

    def test_dereference_non_pointer(self, world, expr):
        with pytest.raises(InvalidTypeError):
            ev(world, expr, "*i")

    def test_division_by_zero(self, world, expr):
        with pytest.raises(DivisionByZeroError):
            ev(world, expr, "i / 0")

    def test_string_literal_unsupported(self, world, expr):
        with pytest.raises(UnsupportedTypeError):
            ev(world, expr, '"hi"')

    def test_array_arithmetic_type_error(self, world, expr):
        with pytest.raises(InvalidTypeError):
            ev(world, expr, "s * 2")
