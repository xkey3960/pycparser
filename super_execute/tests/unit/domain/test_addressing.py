"""地址算术：`&s.m` 与 `&a[i]` 都退化成"基地址 + 偏移"（D5）。"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    Member,
    StructType,
    UnionType,
)
from super_execute.domain.exceptions import (
    AddressError,
    IncompleteTypeError,
    InvalidTypeError,
    OutOfBoundsError,
)
from super_execute.domain.services.addressing import element_address, member_address
from super_execute.domain.services.builtin_types import CHAR, DOUBLE, INT, SHORT
from super_execute.domain.value_objects import Address, AddressRegion


def _struct(tag, *members):
    ctype = StructType(tag)
    ctype.define(members)
    return ctype


def _base(offset=0, scope_id=1):
    return Address(AddressRegion.SCOPE, scope_id, offset)


class TestMemberAddress:
    def test_uses_offsetof(self):
        s = _struct("S", Member("a", CHAR), Member("b", INT), Member("c", SHORT))
        base = _base(100)
        assert member_address(base, s, "b") == base + 4
        assert member_address(base, s, "c") == base + 8

    def test_first_member_equals_base(self):
        """&s.a == &s（a 在偏移 0）——C 里这是合法的同一地址。"""
        s = _struct("S", Member("a", CHAR), Member("b", INT))
        base = _base(16)
        assert member_address(base, s, "a") == base

    def test_nested_member(self):
        inner = _struct("In", Member("x", CHAR), Member("y", INT))
        outer = _struct("Out", Member("head", CHAR), Member("inner", inner))
        base = _base(0)
        mid = member_address(base, outer, "inner")
        assert mid == base + outer.offsetof("inner")
        assert member_address(mid, inner, "y") == base + outer.offsetof("inner") + 4

    def test_union_members_all_at_base(self):
        u = UnionType("U")
        u.define([Member("i", INT), Member("d", DOUBLE)])
        base = _base(8)
        assert member_address(base, u, "i") == base
        assert member_address(base, u, "d") == base

    def test_non_compound_rejected(self):
        with pytest.raises(InvalidTypeError, match="不是结构体"):
            member_address(_base(), INT, "x")

    def test_incomplete_struct_rejected(self):
        with pytest.raises(IncompleteTypeError):
            member_address(_base(), StructType("Forward"), "x")

    def test_unknown_member(self):
        s = _struct("S", Member("a", INT))
        with pytest.raises(InvalidTypeError, match="没有成员"):
            member_address(_base(), s, "nope")


class TestElementAddress:
    def test_scales_by_element_size(self):
        array = ArrayType(INT, 3)
        base = _base(64)
        assert element_address(base, array, 0) == base
        assert element_address(base, array, 1) == base + 4
        assert element_address(base, array, 2) == base + 8

    def test_struct_elements(self):
        s = _struct("S", Member("a", INT), Member("b", INT))  # 8 字节
        array = ArrayType(s, 4)
        base = _base(0)
        assert element_address(base, array, 3) == base + 24

    @pytest.mark.parametrize("index", [-1, 3, 99])
    def test_index_out_of_range(self, index):
        with pytest.raises(OutOfBoundsError, match="越界"):
            element_address(_base(), ArrayType(INT, 3), index)

    def test_bool_index_rejected(self):
        with pytest.raises(InvalidTypeError, match="整数"):
            element_address(_base(), ArrayType(INT, 3), True)

    def test_non_array_rejected(self):
        with pytest.raises(InvalidTypeError, match="不是数组"):
            element_address(_base(), INT, 0)

    def test_incomplete_array_rejected(self):
        with pytest.raises(IncompleteTypeError):
            element_address(_base(), ArrayType(INT), 0)

    def test_offset_overflow_is_caught_by_address(self):
        """偏移越过 64 KiB 时由 Address 自己挡住，不会悄悄回绕。"""
        base = _base(0xFFFC)  # 距离区尾只剩 4 字节
        with pytest.raises(AddressError):
            element_address(base, ArrayType(INT, 2), 1)  # +4 → 0x10000 越界
