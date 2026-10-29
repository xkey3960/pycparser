"""SlotMemory：作用域内存的 Phase A 实现。

重点验证"地址真的能指到东西"：标量、数组元素、结构体成员（含嵌套）都能通过
``基地址 + 偏移`` 读写，越界 / 悬空 / 类型不符都要报错。

注意每次访问都传类型：C 里 ``s`` 与 ``s.a`` 的地址可能相同（首成员偏移 0），
只有访问类型能区分它们。
"""

import pytest

from super_execute.application.ports import MemoryPort
from super_execute.domain.entities.c_types import (
    ArrayType,
    Member,
    StructType,
    UnionType,
)
from super_execute.domain.exceptions import (
    AllocationError,
    IncompleteTypeError,
    MemoryAccessError,
    OutOfBoundsError,
    RegionNotImplementedError,
    ScopeDestroyedError,
)
from super_execute.domain.services.builtin_types import CHAR, INT, SHORT
from super_execute.domain.value_objects import (
    SCOPE_REGION_SIZE,
    Address,
    AddressRegion,
)
from super_execute.frameworks.memory import SlotMemory

SCOPE = 1


@pytest.fixture
def memory():
    mem = SlotMemory()
    mem.create_scope(SCOPE)
    return mem


def _struct(tag, *members):
    ctype = StructType(tag)
    ctype.define(members)
    return ctype


def _address(offset, scope_id=SCOPE):
    return Address(AddressRegion.SCOPE, scope_id, offset)


class TestPortConformance:
    def test_implements_the_port(self, memory):
        assert isinstance(memory, MemoryPort)


class TestScopeLifecycle:
    def test_create_and_live(self, memory):
        assert memory.is_live(SCOPE)
        assert not memory.is_live(99)

    def test_duplicate_create_rejected(self, memory):
        with pytest.raises(AllocationError, match="已经存在"):
            memory.create_scope(SCOPE)

    @pytest.mark.parametrize("scope_id", [0, -1, 256, 1000])
    def test_scope_id_range(self, memory, scope_id):
        with pytest.raises(AllocationError, match="越界"):
            memory.create_scope(scope_id)

    def test_scope_id_must_be_int(self, memory):
        with pytest.raises(AllocationError, match="整数"):
            memory.create_scope("1")

    def test_destroy_missing_scope(self, memory):
        with pytest.raises(MemoryAccessError, match="不存在"):
            memory.destroy_scope(99)


class TestAllocation:
    def test_first_allocation_at_zero(self, memory):
        assert memory.allocate(SCOPE, INT) == _address(0)

    def test_allocations_respect_alignment(self, memory):
        """char 之后放 int 要跳过 3 个字节的 padding。"""
        first = memory.allocate(SCOPE, CHAR)
        second = memory.allocate(SCOPE, INT)
        assert first.offset == 0
        assert second.offset == 4

    def test_allocations_do_not_overlap(self, memory):
        a = memory.allocate(SCOPE, INT)
        b = memory.allocate(SCOPE, INT)
        assert (a.offset, b.offset) == (0, 4)

    def test_size_drives_the_next_offset(self, memory):
        memory.allocate(SCOPE, ArrayType(INT, 3))  # 12 字节
        assert memory.allocate(SCOPE, CHAR).offset == 12

    def test_incomplete_type_rejected(self, memory):
        with pytest.raises(IncompleteTypeError):
            memory.allocate(SCOPE, StructType("Forward"))

    def test_non_ctype_rejected(self, memory):
        with pytest.raises(AllocationError, match="CType"):
            memory.allocate(SCOPE, int)

    def test_region_capacity(self, memory):
        memory.allocate(SCOPE, ArrayType(CHAR, SCOPE_REGION_SIZE - 8))
        with pytest.raises(AllocationError, match="不够"):
            memory.allocate(SCOPE, ArrayType(CHAR, 16))

    def test_unknown_scope(self, memory):
        with pytest.raises(MemoryAccessError, match="尚未创建"):
            memory.allocate(77, INT)


class TestScalarAccess:
    def test_roundtrip(self, memory):
        addr = memory.allocate(SCOPE, INT)
        memory.write(addr, 42, INT)
        assert memory.read(addr, INT) == 42

    def test_uninitialized_is_none(self, memory):
        assert memory.read(memory.allocate(SCOPE, INT), INT) is None

    def test_overwrite(self, memory):
        addr = memory.allocate(SCOPE, INT)
        memory.write(addr, 1, INT)
        memory.write(addr, 2, INT)
        assert memory.read(addr, INT) == 2

    def test_offset_beyond_scalar_raises(self, memory):
        addr = memory.allocate(SCOPE, INT)
        memory.write(addr, 1, INT)
        with pytest.raises(OutOfBoundsError, match="越过"):
            memory.read(addr + 1, INT)


class TestArrayAccess:
    def test_element_by_offset(self, memory):
        array = ArrayType(INT, 3)
        addr = memory.allocate(SCOPE, array)
        memory.write(addr, [10, 20, 30], array)

        assert memory.read(addr, array) == [10, 20, 30]
        assert memory.read(addr + 4, INT) == 20
        assert memory.read(addr + 8, INT) == 30

    def test_write_element_through_address(self, memory):
        array = ArrayType(INT, 3)
        addr = memory.allocate(SCOPE, array)
        memory.write(addr, [10, 20, 30], array)
        memory.write(addr + 4, 99, INT)
        assert memory.read(addr, array) == [10, 99, 30]

    def test_non_element_boundary_rejected(self, memory):
        """落在元素内部的偏移要报错，而不是悄悄当成某个元素。"""
        array = ArrayType(INT, 3)
        addr = memory.allocate(SCOPE, array)
        memory.write(addr, [1, 2, 3], array)
        with pytest.raises(OutOfBoundsError, match="越过"):
            memory.read(addr + 2, INT)

    def test_value_shorter_than_type(self, memory):
        """值比类型短时不能静默读出去（比如部分初始化）。"""
        array = ArrayType(INT, 3)
        addr = memory.allocate(SCOPE, array)
        memory.write(addr, [1], array)  # 只填了第一个
        with pytest.raises(OutOfBoundsError, match="下标越界"):
            memory.read(addr + 4, INT)


class TestStructAccess:
    def test_member_by_offsetof(self, memory):
        s = _struct("S", Member("a", CHAR), Member("b", INT), Member("c", SHORT))
        addr = memory.allocate(SCOPE, s)
        memory.write(addr, {"a": 1, "b": 2, "c": 3}, s)

        assert memory.read(addr + s.offsetof("a"), CHAR) == 1
        assert memory.read(addr + s.offsetof("b"), INT) == 2
        assert memory.read(addr + s.offsetof("c"), SHORT) == 3

    def test_first_member_at_offset_zero(self, memory):
        """&s.a 与 &s 是同一个地址，靠访问类型区分读的是谁。"""
        s = _struct("S", Member("a", CHAR), Member("b", INT))
        addr = memory.allocate(SCOPE, s)
        memory.write(addr, {"a": 1, "b": 2}, s)
        assert memory.read(addr, s) == {"a": 1, "b": 2}
        assert memory.read(addr + s.offsetof("a"), CHAR) == 1

    def test_write_member_through_address(self, memory):
        s = _struct("S", Member("a", CHAR), Member("b", INT))
        addr = memory.allocate(SCOPE, s)
        memory.write(addr, {"a": 1, "b": 2}, s)
        memory.write(addr + s.offsetof("b"), 200, INT)
        assert memory.read(addr, s) == {"a": 1, "b": 200}

    def test_padding_offset_has_no_member(self, memory):
        s = _struct("S", Member("a", CHAR), Member("b", INT))
        addr = memory.allocate(SCOPE, s)
        memory.write(addr, {"a": 1, "b": 2}, s)
        with pytest.raises(OutOfBoundsError, match="任何成员"):
            memory.read(addr + 1, CHAR)  # padding 字节

    def test_nested_member(self, memory):
        inner = _struct("In", Member("x", CHAR), Member("y", INT))
        outer = _struct("Out", Member("head", CHAR), Member("inner", inner))
        addr = memory.allocate(SCOPE, outer)
        memory.write(addr, {"head": 9, "inner": {"x": 1, "y": 2}}, outer)

        delta = outer.offsetof("inner") + inner.offsetof("y")
        assert memory.read(addr + delta, INT) == 2
        memory.write(addr + delta, 7, INT)
        assert memory.read(addr, outer)["inner"]["y"] == 7

    def test_array_of_structs(self, memory):
        s = _struct("S", Member("a", INT), Member("b", INT))
        array = ArrayType(s, 2)
        addr = memory.allocate(SCOPE, array)
        memory.write(addr, [{"a": 1, "b": 2}, {"a": 3, "b": 4}], array)

        second_b = s.sizeof() + s.offsetof("b")
        assert memory.read(addr + second_b, INT) == 4

    def test_member_missing_from_value(self, memory):
        s = _struct("S", Member("a", INT), Member("b", INT))
        addr = memory.allocate(SCOPE, s)
        memory.write(addr, {"a": 1}, s)  # 缺 b
        with pytest.raises(OutOfBoundsError, match="没有可取的值"):
            memory.read(addr + s.offsetof("b"), INT)


class TestUnionAccess:
    def test_member_disambiguated_by_type(self, memory):
        """联合体所有成员都在偏移 0，只能靠访问类型指出要哪个成员。"""
        u = UnionType("U")
        u.define([Member("i", INT), Member("c", CHAR)])
        addr = memory.allocate(SCOPE, u)
        memory.write(addr, {"i": 5, "c": 6}, u)

        assert memory.read(addr, INT) == 5
        assert memory.read(addr, CHAR) == 6

    def test_member_address_equals_base(self, memory):
        """C 里 &u.m 对所有成员都等于 &u。"""
        u = UnionType("U")
        u.define([Member("i", INT), Member("c", CHAR)])
        addr = memory.allocate(SCOPE, u)
        assert addr + u.offsetof("i") == addr
        assert addr + u.offsetof("c") == addr


class TestTypeMismatch:
    def test_wrong_type_rejected(self, memory):
        addr = memory.allocate(SCOPE, INT)
        memory.write(addr, 1, INT)
        with pytest.raises(MemoryAccessError, match="不能用"):
            memory.read(addr, CHAR)

    def test_type_punning_not_supported(self, memory):
        """Phase A 是槽位存储，做不到按字节重解释——必须显式拒绝。"""
        s = _struct("S", Member("b", INT))
        addr = memory.allocate(SCOPE, s)
        memory.write(addr, {"b": 1}, s)
        with pytest.raises(MemoryAccessError, match="类型双关"):
            memory.read(addr + s.offsetof("b"), CHAR)


class TestOutOfBounds:
    def test_no_object_at_offset(self, memory):
        memory.allocate(SCOPE, INT)
        with pytest.raises(OutOfBoundsError, match="任何对象"):
            memory.read(_address(1000), INT)

    def test_between_two_objects(self, memory):
        memory.allocate(SCOPE, CHAR)
        memory.allocate(SCOPE, INT)  # 0..1 是 char，4..8 是 int，1..4 是洞
        with pytest.raises(OutOfBoundsError):
            memory.read(_address(2), CHAR)

    def test_non_address_rejected(self, memory):
        with pytest.raises(MemoryAccessError, match="Address"):
            memory.read(0, INT)

    def test_heap_region_not_implemented(self, memory):
        with pytest.raises(RegionNotImplementedError, match="HEAP"):
            memory.read(Address(AddressRegion.HEAP, 0, 0), INT)

    def test_function_region_not_implemented(self, memory):
        with pytest.raises(RegionNotImplementedError):
            memory.read(Address(AddressRegion.FUNCTION, 0, 0), INT)


class TestDestroyedScope:
    """D3：作用域销毁后，属于它的地址必须报错，而不是静默读到脏数据。"""

    def test_read_after_destroy(self, memory):
        addr = memory.allocate(SCOPE, INT)
        memory.write(addr, 42, INT)
        memory.destroy_scope(SCOPE)
        with pytest.raises(ScopeDestroyedError, match="销毁"):
            memory.read(addr, INT)

    def test_write_after_destroy(self, memory):
        addr = memory.allocate(SCOPE, INT)
        memory.destroy_scope(SCOPE)
        with pytest.raises(ScopeDestroyedError):
            memory.write(addr, 1, INT)

    def test_allocate_after_destroy(self, memory):
        memory.destroy_scope(SCOPE)
        with pytest.raises(ScopeDestroyedError):
            memory.allocate(SCOPE, INT)

    def test_is_live_after_destroy(self, memory):
        memory.destroy_scope(SCOPE)
        assert memory.is_live(SCOPE) is False

    def test_recreating_clears_destroyed_flag(self, memory):
        memory.destroy_scope(SCOPE)
        memory.create_scope(SCOPE)
        addr = memory.allocate(SCOPE, INT)
        memory.write(addr, 7, INT)
        assert memory.read(addr, INT) == 7

    def test_stale_address_aliases_reused_scope(self, memory):
        """**已知风险（D3 的代价）**：id 复用后旧地址会静默命中新作用域。

        8 位 id 空间装不下"代"，所以这里刻意把行为钉住：这是设计取舍，
        不是待修的 bug——真正的兜底是不要让 id 在活跃期被复用。
        """
        old = memory.allocate(SCOPE, INT)
        memory.write(old, 111, INT)
        memory.destroy_scope(SCOPE)

        memory.create_scope(SCOPE)
        new = memory.allocate(SCOPE, INT)
        assert new == old  # 同 id 同偏移
        memory.write(new, 222, INT)
        assert memory.read(old, INT) == 222  # 旧地址看到了新值

    def test_other_scopes_unaffected(self, memory):
        memory.create_scope(2)
        other = memory.allocate(2, INT)
        memory.write(other, 5, INT)

        memory.destroy_scope(SCOPE)
        assert memory.read(other, INT) == 5
