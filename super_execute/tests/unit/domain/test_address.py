"""Address 值对象：4 字节编址方案（TASK.md / 裁决 D1）。"""

import pytest
from dataclasses import FrozenInstanceError

from super_execute.domain.exceptions import AddressError
from super_execute.domain.value_objects import (
    NULL_ADDRESS,
    Address,
    AddressRegion,
)


class TestEncoding:
    """地址与 4 字节整数之间的双向映射。"""

    def test_region_numbers_match_task_md(self):
        """region 编号必须与 TASK.md 的约定一致：0=scope / 1=heap / 2=function。"""
        assert int(AddressRegion.SCOPE) == 0
        assert int(AddressRegion.HEAP) == 1
        assert int(AddressRegion.FUNCTION) == 2

    def test_scope_address_bit_layout(self):
        """scope 区：高字节 region，次高字节 scope_id，低两字节 offset。"""
        addr = Address(AddressRegion.SCOPE, 3, 16)
        assert addr.packed == (0 << 24) | (3 << 16) | 16

    def test_heap_address_uses_wide_offset(self):
        """D1：heap 区把次高字节并入偏移，因此能寻址 16 MiB 而不只是 64 KiB。"""
        addr = Address(AddressRegion.HEAP, 0, 0xFFFFF)   # 1 MiB - 1，旧实现的堆容量
        assert addr.packed == (1 << 24) | 0xFFFFF

    def test_function_region_is_wide_too(self):
        addr = Address(AddressRegion.FUNCTION, 0, 1234)
        assert addr.packed == (2 << 24) | 1234

    @pytest.mark.parametrize("region,scope_id,offset", [
        (AddressRegion.SCOPE, 1, 0),
        (AddressRegion.SCOPE, 255, 0xFFFF),
        (AddressRegion.HEAP, 0, 0),
        (AddressRegion.HEAP, 0, 0xFFFFFF),
        (AddressRegion.FUNCTION, 0, 0xFFFFFF),
    ])
    def test_pack_unpack_roundtrip(self, region, scope_id, offset):
        addr = Address(region, scope_id, offset)
        assert Address.from_packed(addr.packed) == addr

    def test_region_accepts_plain_int(self):
        """允许 Address(1, 0, 16) 这种写法，统一收敛成 IntEnum。"""
        assert Address(1, 0, 16) == Address(AddressRegion.HEAP, 0, 16)

    def test_unknown_region_rejected(self):
        with pytest.raises(AddressError):
            Address(9, 0, 0)


class TestNull:
    """NULL 被定义成 (SCOPE, 0, 0)，packed 恰好是整数 0。"""

    def test_null_is_zero(self):
        assert NULL_ADDRESS.packed == 0
        assert NULL_ADDRESS.is_null
        assert Address.from_packed(0).is_null

    def test_null_factory(self):
        assert Address.null() == NULL_ADDRESS

    def test_scope_zero_with_offset_is_rejected(self):
        """0 号作用域只代表 NULL，配非零偏移是无意义的地址。"""
        with pytest.raises(AddressError, match="NULL 专用"):
            Address(AddressRegion.SCOPE, 0, 8)

    def test_null_arithmetic_rejected(self):
        with pytest.raises(AddressError, match="NULL"):
            NULL_ADDRESS.advanced(4)
        with pytest.raises(AddressError):
            NULL_ADDRESS + 1

    def test_non_null_not_mistaken_for_null(self):
        assert not Address(AddressRegion.SCOPE, 1, 0).is_null


class TestBounds:
    """越界必须在构造时就被挡住，而不是等到解引用。"""

    def test_scope_offset_limit(self):
        Address(AddressRegion.SCOPE, 1, 0xFFFF)          # 边界允许
        with pytest.raises(AddressError, match="偏移越界"):
            Address(AddressRegion.SCOPE, 1, 0x10000)

    def test_scope_id_range(self):
        with pytest.raises(AddressError, match="scope_id 越界"):
            Address(AddressRegion.SCOPE, 256, 0)
        with pytest.raises(AddressError, match="scope_id 越界"):
            Address(AddressRegion.SCOPE, -1, 0)

    def test_wide_region_offset_limit(self):
        Address(AddressRegion.HEAP, 0, 0xFFFFFF)
        with pytest.raises(AddressError, match="偏移越界"):
            Address(AddressRegion.HEAP, 0, 0x1000000)

    @pytest.mark.parametrize("region", [AddressRegion.HEAP, AddressRegion.FUNCTION])
    def test_wide_regions_reject_scope_id(self, region):
        """heap / function 区没有作用域概念，scope_id 必须为 0。"""
        with pytest.raises(AddressError, match="没有 scope_id"):
            Address(region, 1, 0)

    def test_from_packed_rejects_out_of_range(self):
        with pytest.raises(AddressError, match="4 字节"):
            Address.from_packed(1 << 32)
        with pytest.raises(AddressError):
            Address.from_packed(-1)

    def test_from_packed_rejects_non_int(self):
        with pytest.raises(AddressError):
            Address.from_packed("16")

    def test_from_packed_rejects_reserved_region(self):
        """高字节 3..255 是保留区：要求抛 AddressError 而不是裸 ValueError。"""
        with pytest.raises(AddressError, match="内存区"):
            Address.from_packed(3 << 24)


class TestArithmetic:
    """值对象只做字节平移；按元素类型缩放是 application 层的事。"""

    def test_advanced_moves_offset(self):
        base = Address(AddressRegion.SCOPE, 2, 8)
        assert base.advanced(4) == Address(AddressRegion.SCOPE, 2, 12)
        assert base + 4 == Address(AddressRegion.SCOPE, 2, 12)
        assert base - 4 == Address(AddressRegion.SCOPE, 2, 4)

    def test_advanced_keeps_region_and_scope(self):
        base = Address(AddressRegion.HEAP, 0, 64)
        moved = base.advanced(64)
        assert (moved.region, moved.scope_id) == (AddressRegion.HEAP, 0)
        assert moved.offset == 128

    def test_advanced_beyond_limit_raises(self):
        base = Address(AddressRegion.SCOPE, 2, 0xFFFE)
        with pytest.raises(AddressError):
            base.advanced(4)          # 越过 64 KiB 边界

    def test_advanced_negative_below_zero_raises(self):
        with pytest.raises(AddressError):
            Address(AddressRegion.SCOPE, 2, 4).advanced(-8)

    def test_advanced_requires_int(self):
        with pytest.raises(AddressError, match="整数"):
            Address(AddressRegion.SCOPE, 2, 4).advanced(1.5)


class TestValueSemantics:
    def test_equality_by_value(self):
        assert Address(AddressRegion.SCOPE, 1, 4) == Address(AddressRegion.SCOPE, 1, 4)
        assert Address(AddressRegion.SCOPE, 1, 4) != Address(AddressRegion.SCOPE, 1, 8)

    def test_same_offset_different_region_differs(self):
        """0x0004 与 0x01000004 不是同一个地址——区号参与相等判断。"""
        assert Address(AddressRegion.SCOPE, 0, 0) != Address(AddressRegion.HEAP, 0, 0)

    def test_orderable_for_pointer_comparison(self):
        assert Address(AddressRegion.SCOPE, 1, 0) < Address(AddressRegion.SCOPE, 1, 4)
        assert Address(AddressRegion.SCOPE, 1, 0) < Address(AddressRegion.HEAP, 0, 0)

    def test_immutable(self):
        addr = Address(AddressRegion.SCOPE, 1, 0)
        with pytest.raises(FrozenInstanceError):
            addr.offset = 4

    def test_repr_is_readable(self):
        assert "SCOPE" in repr(Address(AddressRegion.SCOPE, 1, 0))
        assert "NULL" in repr(NULL_ADDRESS)
