"""位域布局：与 gcc 对齐。

这里的期望值**不是算出来的，是量出来的**——把同一份结构体交给 gcc（mingw 13.2，
``int`` 4 字节）编译运行，打印 ``sizeof`` / ``offsetof`` 得到黄金值，再让本实现
逐条对上。

规则（gcc 在 x86 上的行为）：

* 每个位域属于一个"声明类型大小"的存储单元，单元按该类型的对齐要求放置；
* 连续的同类型位域**共用一个单元**，直到放不下；
* 放不下、或类型变了，就另起一个单元；
* 单元之后的普通成员从单元的**末尾**开始。

C 标准把这些定为"实现定义"，所以"选 gcc"是一个决定，不是唯一正确答案。
"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    Member,
    StructType,
    UnionType,
)
from super_execute.domain.exceptions import InvalidTypeError
from super_execute.domain.services.builtin_types import CHAR, INT, UNSIGNED_INT

#: gcc 实测的黄金值：结构体 → sizeof
GCC_SIZEOF = {
    "struct A { unsigned a : 3; };": 4,
    "struct B { unsigned a : 3; unsigned b : 5; };": 4,
    "struct C { unsigned a : 3; unsigned b : 30; };": 8,
    "struct D { char c; unsigned a : 3; };": 8,
    "struct E { unsigned a : 3; char c; };": 8,
    "struct F { unsigned a : 3; int n; };": 8,
    "struct G { unsigned a : 3; unsigned b : 5; int n; };": 8,
    "struct H { unsigned a : 20; unsigned b : 20; };": 8,
    "struct I { unsigned a : 3; char b : 2; };": 8,
    "struct J { char b : 2; unsigned a : 3; };": 8,
    "struct K { unsigned a : 31; unsigned b : 2; };": 8,
    "struct L { int n; unsigned a : 3; unsigned b : 5; char c; };": 12,
}


def struct(tag, *members):
    ctype = StructType(tag)
    ctype.define(members)
    return ctype


def run(source: str):
    from pycparser.c_parser import CParser

    from super_execute.interface_adapters.ast.interpreter import Interpreter

    interpreter = Interpreter()
    interpreter.load(CParser().parse(source, "<test>"))
    return interpreter.run()


class TestGoldenLayout:
    @pytest.mark.parametrize(("source", "expected"), GCC_SIZEOF.items())
    def test_sizeof_matches_gcc(self, source, expected):
        program = (
            source
            + " int main(void) { return sizeof(struct "
            + source.split()[1]
            + "); }"
        )
        assert run(program) == expected


class TestLayoutDetails:
    def test_same_unit_packs(self):
        bits = struct("B", Member("a", UNSIGNED_INT, 3), Member("b", UNSIGNED_INT, 5))
        assert bits.sizeof() == 4
        assert bits.bit_layout("a") == (0, 0, 3)
        assert bits.bit_layout("b") == (0, 3, 5)

    def test_overflow_starts_new_unit(self):
        bits = struct("C", Member("a", UNSIGNED_INT, 3), Member("b", UNSIGNED_INT, 30))
        assert bits.sizeof() == 8
        assert bits.bit_layout("b") == (4, 0, 30)

    def test_normal_member_after_unit_starts_at_unit_end(self):
        mixed = struct(
            "G",
            Member("a", UNSIGNED_INT, 3),
            Member("b", UNSIGNED_INT, 5),
            Member("n", INT),
        )
        assert mixed.sizeof() == 8
        assert mixed.offsetof("n") == 4

    def test_char_before_bitfield_pushes_unit_to_alignment(self):
        mixed = struct("D", Member("c", CHAR), Member("a", UNSIGNED_INT, 3))
        assert mixed.sizeof() == 8
        assert mixed.offsetof("c") == 0
        assert mixed.bit_layout("a")[0] == 4  # 单元按 int 对齐

    def test_different_bitfield_types_get_separate_units(self):
        mixed = struct("I", Member("a", UNSIGNED_INT, 3), Member("b", CHAR, 2))
        assert mixed.sizeof() == 8
        assert mixed.bit_layout("a")[0] == 0
        assert mixed.bit_layout("b")[0] == 4

    def test_bitfield_is_flagged(self):
        bits = struct("B", Member("a", UNSIGNED_INT, 3), Member("b", UNSIGNED_INT, 5))
        assert bits.is_bitfield("a")
        assert bits.is_bitfield("b") is not False  # 都是位域
        assert bits.is_bitfield("nope") is False


class TestOffsetOf:
    def test_bitfield_offsetof_rejected(self):
        """C 禁止对位域取偏移——它不一定从字节边界开始。"""
        bits = struct("B", Member("a", UNSIGNED_INT, 3))
        with pytest.raises(InvalidTypeError, match="位域"):
            bits.offsetof("a")

    def test_normal_member_still_works(self):
        bits = struct("B", Member("a", UNSIGNED_INT, 3), Member("n", INT))
        assert bits.offsetof("n") == 4


class TestUnionBitfields:
    def test_union_members_all_at_zero(self):
        combined = UnionType("U")
        combined.define([Member("a", UNSIGNED_INT, 3), Member("n", INT)])
        assert combined.sizeof() == 4
        assert combined.offsetof("n") == 0
        assert combined.bit_layout("a") == (0, 0, 3)


class TestArraysOfBitfieldStructs:
    def test_array_stride_uses_packed_size(self):
        """`struct B` 是 4 字节，数组元素间距也必须是 4。"""
        bits = struct("B", Member("a", UNSIGNED_INT, 3), Member("b", UNSIGNED_INT, 5))
        assert ArrayType(bits, 3).sizeof() == 12
