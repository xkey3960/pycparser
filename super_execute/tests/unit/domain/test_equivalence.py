"""类型等价：跨文件重复定义去重的基础。

为什么需要它：真实项目里同一个结构体/typedef 会出现在多个 `.c` 里（头文件内容被
各文件展开）。本项目的多文件夹具 `test/multi/lib.c` 与 `main.c` 就是两个文件都
原样写着同一份 `typedef struct Pt { int x; int y; } Pt;`。

比较还必须能处理自引用（`struct Node { struct Node *next; }`），否则会无限递归。
"""

from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    EnumType,
    FunctionType,
    Member,
    PointerType,
    StructType,
    UnionType,
)
from super_execute.domain.services.builtin_types import CHAR, DOUBLE, INT, SHORT
from super_execute.domain.services.equivalence import (
    members_equivalent,
    types_equivalent,
)


def _struct(tag, *members):
    ctype = StructType(tag)
    ctype.define(members)
    return ctype


def m(name, ctype):
    return Member(name, ctype)


class TestScalars:
    def test_same_basic(self):
        assert types_equivalent(INT, INT)
        assert types_equivalent(BasicType("x", 4, 4), BasicType("x", 8, 8))

    def test_different_basic(self):
        assert not types_equivalent(INT, CHAR)

    def test_enum_same_tag(self):
        assert types_equivalent(EnumType("E", {"A": 0}), EnumType("E", {"A": 0}))

    def test_enum_different_tag(self):
        assert not types_equivalent(EnumType("E"), EnumType("F"))


class TestDerived:
    def test_pointer(self):
        assert types_equivalent(PointerType(INT), PointerType(INT))
        assert not types_equivalent(PointerType(INT), PointerType(CHAR))

    def test_pointer_to_pointer(self):
        assert types_equivalent(
            PointerType(PointerType(INT)), PointerType(PointerType(INT))
        )

    def test_array(self):
        assert types_equivalent(ArrayType(INT, 3), ArrayType(INT, 3))
        assert not types_equivalent(ArrayType(INT, 3), ArrayType(INT, 4))

    def test_function(self):
        assert types_equivalent(FunctionType(INT, (INT,)), FunctionType(INT, (INT,)))
        assert not types_equivalent(
            FunctionType(INT, (INT,)), FunctionType(INT, (INT,), variadic=True)
        )

    def test_mixed_kinds(self):
        assert not types_equivalent(INT, PointerType(INT))
        assert not types_equivalent(PointerType(INT), ArrayType(INT, 1))


class TestCompound:
    def test_identical_members(self):
        left = _struct("P", m("x", INT), m("y", INT))
        right = _struct("P", m("x", INT), m("y", INT))
        assert types_equivalent(left, right)

    def test_different_member_type(self):
        left = _struct("P", m("x", INT))
        right = _struct("P", m("x", SHORT))
        assert not types_equivalent(left, right)

    def test_different_member_order(self):
        left = _struct("P", m("x", INT), m("y", CHAR))
        right = _struct("P", m("y", CHAR), m("x", INT))
        assert not types_equivalent(left, right)

    def test_different_member_count(self):
        left = _struct("P", m("x", INT))
        right = _struct("P", m("x", INT), m("y", INT))
        assert not types_equivalent(left, right)

    def test_struct_vs_union(self):
        left = _struct("P", m("x", INT))
        right = UnionType("P")
        right.define([m("x", INT)])
        assert not types_equivalent(left, right)

    def test_nested_struct(self):
        inner_left = _struct("In", m("a", INT))
        inner_right = _struct("In", m("a", INT))
        assert types_equivalent(
            _struct("Out", m("in", inner_left)), _struct("Out", m("in", inner_right))
        )

    def test_self_referential_terminates(self):
        """自引用结构体不能把比较拖进无限递归。"""
        left = StructType("Node")
        left.define([m("v", INT), m("next", PointerType(left))])
        right = StructType("Node")
        right.define([m("v", INT), m("next", PointerType(right))])
        assert types_equivalent(left, right)

    def test_self_referential_difference_detected(self):
        left = StructType("Node")
        left.define([m("v", INT), m("next", PointerType(left))])
        right = StructType("Node")
        right.define([m("v", DOUBLE), m("next", PointerType(right))])
        assert not types_equivalent(left, right)


class TestMembersEquivalent:
    def test_matches_existing(self):
        existing = _struct("P", m("x", INT), m("y", CHAR))
        assert members_equivalent(existing, [m("x", INT), m("y", CHAR)])

    def test_rejects_different(self):
        existing = _struct("P", m("x", INT))
        assert not members_equivalent(existing, [m("x", CHAR)])

    def test_incomplete_type_never_matches(self):
        assert not members_equivalent(StructType("Forward"), [m("x", INT)])

    def test_non_compound_never_matches(self):
        assert not members_equivalent(INT, [m("x", INT)])
