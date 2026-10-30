"""结构体/联合体布局：对齐、padding、成员偏移、弹性数组成员。

黄金值全部由宿主 gcc 现算，不是手抄的。重算命令：

    # 源码见本文件末尾的 GCC_SOURCE
    gcc -std=c11 -o layout_golden golden.c && ./layout_golden

宿主是 x86_64-w64-mingw32（LLP64），标量尺寸与本项目模型一致；指针宽度刻意
不同（宿主 8、本项目 4），所以黄金用例里**不出现指针成员**。
"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    EnumType,
    Member,
    PointerType,
    StructType,
    UnionType,
    align_up,
)
from super_execute.domain.exceptions import (
    IncompleteTypeError,
    InvalidTypeError,
)
from super_execute.domain.services.builtin_types import CHAR, DOUBLE, INT, SHORT


def struct(tag, *members):
    ctype = StructType(tag)
    ctype.define(members)
    return ctype


def union(tag, *members):
    ctype = UnionType(tag)
    ctype.define(members)
    return ctype


def m(name, ctype):
    return Member(name, ctype)


# ==================== gcc 黄金值 ====================


class TestGoldenLayouts:
    """每个用例的期望值都来自 GCC_SOURCE 里对应结构的 sizeof/_Alignof/offsetof。"""

    def test_struct_a_char_int_short(self):
        """struct A { char a; int b; short c; };  → size=12 align=4"""
        t = struct("A", m("a", CHAR), m("b", INT), m("c", SHORT))
        assert (t.sizeof(), t.alignof()) == (12, 4)
        assert [t.offsetof(x) for x in "abc"] == [0, 4, 8]

    def test_struct_b_double_forces_padding(self):
        """struct B { char a; double b; char c; }; → size=24 align=8"""
        t = struct("B", m("a", CHAR), m("b", DOUBLE), m("c", CHAR))
        assert (t.sizeof(), t.alignof()) == (24, 8)
        assert [t.offsetof(x) for x in "abc"] == [0, 8, 16]

    def test_struct_c_packs_tightly(self):
        """struct C { short a; char b; }; → size=4 align=2"""
        t = struct("C", m("a", SHORT), m("b", CHAR))
        assert (t.sizeof(), t.alignof()) == (4, 2)
        assert [t.offsetof(x) for x in "ab"] == [0, 2]

    def test_struct_d_with_array_member(self):
        """struct D { char a[3]; int b; char c; }; → size=12 align=4"""
        t = struct("D", m("a", ArrayType(CHAR, 3)), m("b", INT), m("c", CHAR))
        assert (t.sizeof(), t.alignof()) == (12, 4)
        assert [t.offsetof(x) for x in "abc"] == [0, 4, 8]

    def test_struct_e_with_nested_struct(self):
        """struct E { char a; struct C c; int d; }; → size=12 align=4

        嵌套结构体按自己的对齐（2）落位，所以 c 在偏移 2、d 被顶到 8。
        """
        inner = struct("C", m("a", SHORT), m("b", CHAR))
        t = struct("E", m("a", CHAR), m("c", inner), m("d", INT))
        assert (t.sizeof(), t.alignof()) == (12, 4)
        assert [t.offsetof(x) for x in "acd"] == [0, 2, 8]

    def test_struct_f_trailing_padding(self):
        """struct F { double a; char b; }; → size=16 align=8（尾部补 7 字节）"""
        t = struct("F", m("a", DOUBLE), m("b", CHAR))
        assert (t.sizeof(), t.alignof()) == (16, 8)
        assert t.offsetof("b") == 8

    def test_union_u(self):
        """union U { char a; double b; int c; }; → size=8 align=8"""
        t = union("U", m("a", CHAR), m("b", DOUBLE), m("c", INT))
        assert (t.sizeof(), t.alignof()) == (8, 8)
        assert [t.offsetof(x) for x in "abc"] == [0, 0, 0]


# ==================== 边界情况 ====================


class TestEdgeCases:
    def test_empty_struct_rejected(self):
        """C99 6.7.2.1p1 要求至少一个具名成员；空结构体 sizeof==0 会让成员地址重合。"""
        with pytest.raises(InvalidTypeError, match="至少需要一个具名成员"):
            struct("Empty")
        with pytest.raises(InvalidTypeError, match="至少需要一个具名成员"):
            union("EmptyUnion")

    def test_single_char_struct(self):
        t = struct("One", m("a", CHAR))
        assert (t.sizeof(), t.alignof()) == (1, 1)

    def test_array_of_structs_alignment_follows_element(self):
        inner = struct("C", m("a", SHORT), m("b", CHAR))
        arr = ArrayType(inner, 2)
        assert arr.sizeof() == 8  # 4 * 2
        assert arr.alignof() == 2

    def test_flexible_array_member_takes_no_space(self):
        """C99 6.7.2.1p18：弹性数组成员不计入 sizeof，但影响对齐。"""
        t = struct("Fam", m("n", INT), m("data", ArrayType(CHAR)))
        assert t.is_complete
        assert t.sizeof() == 4
        assert t.offsetof("data") == 4

    def test_deeply_nested(self):
        inner = struct("C", m("a", SHORT), m("b", CHAR))  # 4/2
        mid = struct("Mid", m("x", CHAR), m("c", inner))  # x@0, c@2 → 6/2
        outer = struct("Out", m("y", CHAR), m("mid", mid), m("z", DOUBLE))
        assert mid.sizeof() == 6 and mid.alignof() == 2
        assert mid.offsetof("c") == 2
        assert outer.offsetof("mid") == 2  # 按 2 对齐
        assert outer.offsetof("z") == 8  # double 顶到 8
        assert outer.sizeof() == 16

    def test_union_size_rounds_up_to_alignment(self):
        t = union("U2", m("a", ArrayType(CHAR, 5)), m("b", SHORT))
        assert (t.sizeof(), t.alignof()) == (6, 2)  # 5 → 补到 6


class TestIncomplete:
    def test_forward_declared_struct_is_incomplete(self):
        t = StructType("S")
        assert not t.is_complete
        with pytest.raises(IncompleteTypeError, match="不完整"):
            t.sizeof()
        with pytest.raises(IncompleteTypeError):
            t.alignof()
        with pytest.raises(IncompleteTypeError):
            t.members

    def test_define_completes_it(self):
        t = StructType("S")
        t.define([m("a", INT)])
        assert t.is_complete and t.sizeof() == 4

    def test_double_define_rejected(self):
        t = struct("S", m("a", INT))
        with pytest.raises(InvalidTypeError, match="已经定义"):
            t.define([m("b", INT)])

    def test_structural_pointer_to_incomplete_is_allowed(self):
        """`struct S *p;` 合法：指针不需要完整类型。"""
        p = PointerType(StructType("S"))
        assert p.sizeof() == 4


class TestValidation:
    def test_duplicate_member_rejected(self):
        with pytest.raises(InvalidTypeError, match="重复"):
            struct("S", m("a", INT), m("a", CHAR))

    def test_unknown_member_offset(self):
        t = struct("S", m("a", INT))
        with pytest.raises(InvalidTypeError, match="没有成员"):
            t.offsetof("zzz")

    def test_member_type_checked(self):
        with pytest.raises(InvalidTypeError):
            Member("a", "int")

    def test_empty_member_name_rejected(self):
        with pytest.raises(InvalidTypeError):
            Member("", INT)

    def test_bitfields_pack_into_one_unit(self):
        """位域按 gcc 规则**打包**：同类型的连续位域共用一个存储单元。

        ``int a:8; int b:3`` 共 11 位，装得进一个 32 位单元 → 4 字节（gcc 同）。
        完整布局见 ``test_bitfield_layout.py``。
        """
        bits = struct(
            "Bits", Member("a", INT, bit_width=8), Member("b", INT, bit_width=3)
        )
        assert bits.sizeof() == 4
        assert [member.bit_width for member in bits.members] == [8, 3]
        assert bits.bit_layout("a") == (0, 0, 8)
        assert bits.bit_layout("b") == (0, 8, 3)

    def test_bitfield_width_must_fit_the_type(self):
        with pytest.raises(InvalidTypeError, match="超过"):
            Member("flag", INT, bit_width=33)

    def test_negative_bit_width_rejected(self):
        with pytest.raises(InvalidTypeError, match="不能为负"):
            Member("flag", INT, bit_width=-1)

    def test_union_with_bitfield_uses_max_size(self):
        """联合体里每个成员都在偏移 0，大小取最大者。"""
        combined = union("U", Member("flag", INT, bit_width=1), Member("value", INT))
        assert combined.sizeof() == 4


class TestAlignUp:
    @pytest.mark.parametrize(
        "value,align,expected",
        [
            (0, 4, 0),
            (1, 4, 4),
            (3, 4, 4),
            (4, 4, 4),
            (5, 4, 8),
            (5, 8, 8),
            (9, 8, 16),
            (7, 1, 7),
        ],
    )
    def test_align_up(self, value, align, expected):
        assert align_up(value, align) == expected

    def test_align_up_rejects_bad_alignment(self):
        with pytest.raises(InvalidTypeError):
            align_up(4, 0)

    def test_align_up_rejects_negative_value(self):
        """负数向下取整会得到 -4，那是静默的错，必须挡掉。"""
        with pytest.raises(InvalidTypeError, match="不能为负"):
            align_up(-5, 4)

    def test_align_up_rejects_negative_alignment(self):
        with pytest.raises(InvalidTypeError):
            align_up(4, -4)


class TestFlexibleArrayRules:
    """弹性数组成员（FAM）的三条 C99 限制。

    这些点原本是变异测试的漏网之鱼：把实现里"FAM 必须在最后"的判断删掉，
    249 个测试仍然全绿。
    """

    def _fam_struct(self):
        t = StructType("Fam")
        t.define([m("n", INT), m("data", ArrayType(CHAR))])
        return t

    def test_fam_struct_sizeof_excludes_flexible_part(self):
        """6.7.2.1p18：sizeof 不含弹性部分，所以可以直接对结构体求大小。"""
        t = self._fam_struct()
        assert t.sizeof() == 4
        assert t.offsetof("data") == 4
        assert t.has_flexible_array is True

    def test_fam_must_be_last_member(self):
        """6.7.2.1p3：弹性数组只能是最后一个成员。"""
        with pytest.raises(InvalidTypeError, match="最后一个成员"):
            struct("Bad", m("data", ArrayType(CHAR)), m("n", INT))

    def test_fam_rejected_in_union(self):
        """6.7.2.1p1：联合体不允许弹性数组成员。"""
        with pytest.raises(InvalidTypeError, match="联合体不允许弹性数组成员"):
            union("U", m("n", INT), m("a", ArrayType(INT)))

    def test_fam_struct_cannot_be_a_member(self):
        """含 FAM 的结构体作成员会静默少分配（sizeof 不含弹性部分）。"""
        fam = self._fam_struct()
        with pytest.raises(InvalidTypeError, match="不能作成员"):
            struct("Outer", m("c", CHAR), m("f", fam))

    def test_fam_struct_cannot_be_array_element(self):
        fam = self._fam_struct()
        with pytest.raises(InvalidTypeError, match="数组元素不能是"):
            ArrayType(fam, 2)

    def test_plain_struct_is_not_fam(self):
        t = struct("Plain", m("a", INT))
        assert t.has_flexible_array is False


class TestNaming:
    def test_tagged_and_anonymous_names(self):
        assert StructType("P").name == "struct P"
        assert StructType().name == "struct <anonymous>"
        assert UnionType("U").name == "union U"
        assert EnumType("E").name == "enum E"


GCC_SOURCE = r"""
#include <stdio.h>
#include <stddef.h>
struct A { char a; int b; short c; };
struct B { char a; double b; char c; };
struct C { short a; char b; };
struct D { char a[3]; int b; char c; };
struct E { char a; struct C c; int d; };
struct F { double a; char b; };
union  U { char a; double b; int c; };
int main(void){
  printf("A size=%zu align=%zu a=%zu b=%zu c=%zu\n", sizeof(struct A), _Alignof(struct A), offsetof(struct A,a), offsetof(struct A,b), offsetof(struct A,c));
  printf("B size=%zu align=%zu a=%zu b=%zu c=%zu\n", sizeof(struct B), _Alignof(struct B), offsetof(struct B,a), offsetof(struct B,b), offsetof(struct B,c));
  printf("C size=%zu align=%zu a=%zu b=%zu\n", sizeof(struct C), _Alignof(struct C), offsetof(struct C,a), offsetof(struct C,b));
  printf("D size=%zu align=%zu a=%zu b=%zu c=%zu\n", sizeof(struct D), _Alignof(struct D), offsetof(struct D,a), offsetof(struct D,b), offsetof(struct D,c));
  printf("E size=%zu align=%zu a=%zu c=%zu d=%zu\n", sizeof(struct E), _Alignof(struct E), offsetof(struct E,a), offsetof(struct E,c), offsetof(struct E,d));
  printf("F size=%zu align=%zu a=%zu b=%zu\n", sizeof(struct F), _Alignof(struct F), offsetof(struct F,a), offsetof(struct F,b));
  printf("U size=%zu align=%zu\n", sizeof(union U), _Alignof(union U));
  return 0;
}
"""
