"""CType 家族：大小/对齐/完整性/判等语义。"""

import pytest

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
from super_execute.domain.exceptions import (
    IncompleteTypeError,
    InvalidTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.services.builtin_types import (
    CHAR,
    DOUBLE,
    INT,
    UNSIGNED_CHAR,
    VOID,
)


class TestBasicType:
    def test_size_and_align(self):
        assert (INT.sizeof(), INT.alignof()) == (4, 4)
        assert (CHAR.sizeof(), CHAR.alignof()) == (1, 1)

    def test_void_is_incomplete(self):
        """void 没有大小：sizeof(void) 在 C 里非法。"""
        assert VOID.is_complete is False
        with pytest.raises(IncompleteTypeError):
            VOID.sizeof()
        with pytest.raises(IncompleteTypeError):
            VOID.alignof()

    def test_signedness_and_float_flags(self):
        assert INT.is_signed and not INT.is_float
        assert not UNSIGNED_CHAR.is_signed
        assert DOUBLE.is_float

    def test_equality_by_name(self):
        assert INT == BasicType("int", 4, 4)
        assert INT != CHAR

    def test_hashable(self):
        assert len({INT, BasicType("int", 4, 4), CHAR}) == 2

    def test_rejects_bad_size(self):
        with pytest.raises(InvalidTypeError):
            BasicType("bad", 0, 1)
        with pytest.raises(InvalidTypeError):
            BasicType("bad", 1, 0)
        with pytest.raises(InvalidTypeError):
            BasicType("", 1, 1)


class TestPointerType:
    def test_size_equals_address_width(self):
        """指针宽度必须等于 Address 的宽度（4 字节），否则"指针就是地址"不成立。"""
        p = PointerType(INT)
        assert (p.sizeof(), p.alignof()) == (4, 4)

    def test_name(self):
        assert PointerType(CHAR).name == "char *"
        assert PointerType(PointerType(CHAR)).name == "char * *"

    def test_equality_by_target(self):
        assert PointerType(INT) == PointerType(INT)
        assert PointerType(INT) != PointerType(CHAR)

    def test_rejects_non_ctype(self):
        with pytest.raises(InvalidTypeError):
            PointerType("int")

    def test_pointer_to_incomplete_ok(self):
        assert PointerType(StructType("S")).sizeof() == 4


class TestArrayType:
    def test_size_is_element_times_count(self):
        assert ArrayType(INT, 3).sizeof() == 12

    def test_alignment_follows_element(self):
        assert ArrayType(INT, 3).alignof() == 4
        assert ArrayType(CHAR, 7).alignof() == 1

    def test_incomplete_array(self):
        """`int a[];` 是不完整类型，只有补上长度或作 FAM 时才成立。"""
        a = ArrayType(INT)
        assert a.is_complete is False
        with pytest.raises(IncompleteTypeError, match="不完整数组"):
            a.sizeof()

    def test_zero_and_negative(self):
        """C99 没有零长数组（FAM 走 count=None），两者都必须报错。"""
        with pytest.raises(InvalidTypeError, match="必须为正"):
            ArrayType(INT, 0)
        with pytest.raises(InvalidTypeError):
            ArrayType(INT, -1)

    def test_equality(self):
        assert ArrayType(INT, 3) == ArrayType(INT, 3)
        assert ArrayType(INT, 3) != ArrayType(INT, 4)
        assert ArrayType(INT, 3) != ArrayType(CHAR, 3)

    def test_rejects_non_ctype_element(self):
        with pytest.raises(InvalidTypeError):
            ArrayType("int", 3)


class TestFunctionType:
    def test_size_is_illegal(self):
        f = FunctionType(INT, (INT, CHAR))
        with pytest.raises(UnsupportedTypeError, match="函数类型"):
            f.sizeof()
        with pytest.raises(UnsupportedTypeError):
            f.alignof()

    def test_name(self):
        assert FunctionType(INT, (INT, CHAR)).name == "int (int, char)"
        assert FunctionType(INT).name == "int ()"

    def test_variadic(self):
        assert FunctionType(INT, (CHAR,), variadic=True).name == "int (char, ...)"
        assert FunctionType(INT, variadic=True).name == "int (...)"

    def test_equality(self):
        assert FunctionType(INT, (CHAR,)) == FunctionType(INT, (CHAR,))
        assert FunctionType(INT, (CHAR,)) != FunctionType(INT, (CHAR, CHAR))
        assert FunctionType(INT, (CHAR,)) != FunctionType(INT, (CHAR,), variadic=True)

    def test_rejects_bad_params(self):
        with pytest.raises(InvalidTypeError):
            FunctionType(INT, (CHAR, "int"))


class TestEnumType:
    def test_forward_declared_is_incomplete(self):
        e = EnumType("Color")
        assert e.is_complete is False
        with pytest.raises(IncompleteTypeError):
            e.sizeof()

    def test_defined_enum_is_int_sized(self):
        e = EnumType("Color", {"RED": 0, "GREEN": 1})
        assert (e.sizeof(), e.alignof()) == (4, 4)
        assert e.constants == {"RED": 0, "GREEN": 1}

    def test_define_once(self):
        e = EnumType("Color")
        e.define({"RED": 0})
        assert e.sizeof() == 4
        with pytest.raises(InvalidTypeError, match="已经定义"):
            e.define({"BLUE": 2})

    def test_anonymous_naming(self):
        assert EnumType().name == "enum <anonymous>"


class TestDefensiveCopies:
    """对外暴露的容器必须是副本——否则调用方能悄悄改掉领域对象。"""

    def test_enum_constants_returns_copy(self):
        e = EnumType("Color", {"RED": 0})
        e.constants["BLUE"] = 2                     # 改副本
        assert e.constants == {"RED": 0}            # 内部不受影响

    def test_basic_type_equality_ignores_size(self):
        """判等按类型名，不看 size/align——两个 BasicType("int", 8, 8) 仍是 int。"""
        assert BasicType("int", 4, 4) == BasicType("int", 8, 8)

    def test_pointer_equality_compares_target(self):
        assert PointerType(INT) != PointerType(CHAR)


class TestCompoundIdentity:
    def test_structs_are_compared_by_identity(self):
        """成员完全相同的两个 struct 也是**不同**类型——C 语义如此。"""
        a = StructType("P")
        b = StructType("P")
        a.define([Member("x", INT)])
        b.define([Member("x", INT)])
        assert a != b

    def test_tag_is_not_a_unique_name(self):
        """同名标签在不同作用域是不同实体（这正是上一轮修掉的问题）。"""
        assert StructType("P").tag == StructType("P").tag
        assert StructType("P") is not StructType("P")

    def test_union_and_struct_differ(self):
        s = StructType("X")
        u = UnionType("X")
        assert s != u
