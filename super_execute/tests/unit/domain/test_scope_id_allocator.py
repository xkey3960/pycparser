"""ScopeIdAllocator：8 位 id 空间的发放与复用（裁决 D3）。"""

import pytest

from super_execute.domain.entities.scope import Scope
from super_execute.domain.exceptions import InvalidScopeError, ScopeExhaustedError
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.value_objects import SCOPE_ID_MAX, SCOPE_ID_MIN, ScopeKind


@pytest.fixture
def allocator():
    return ScopeIdAllocator()


class TestAcquire:
    def test_starts_at_min_id(self, allocator):
        assert allocator.acquire() == SCOPE_ID_MIN

    def test_allocates_sequentially(self, allocator):
        assert [allocator.acquire() for _ in range(3)] == [1, 2, 3]

    def test_ids_are_unique_while_active(self, allocator):
        assert len({allocator.acquire() for _ in range(50)}) == 50

    def test_len_counts_active(self, allocator):
        for _ in range(4):
            allocator.acquire()
        assert len(allocator) == 4


class TestReleaseAndReuse:
    def test_released_id_is_reused_first(self, allocator):
        """D3：复用退役 id，否则递归一深 8 位空间就耗尽。"""
        first, second = allocator.acquire(), allocator.acquire()
        allocator.release(first)
        assert allocator.acquire() == first          # 最小空闲优先
        assert second == 2

    def test_reuse_picks_smallest(self, allocator):
        ids = [allocator.acquire() for _ in range(3)]      # 1,2,3
        allocator.release(ids[2])
        allocator.release(ids[0])
        assert allocator.acquire() == ids[0]               # 复用 1，而不是 3

    def test_release_requires_active_id(self, allocator):
        with pytest.raises(InvalidScopeError, match="不能重复归还"):
            allocator.release(1)                            # 从没发过

    def test_double_release_rejected(self, allocator):
        scope_id = allocator.acquire()
        allocator.release(scope_id)
        with pytest.raises(InvalidScopeError):
            allocator.release(scope_id)

    def test_active_and_retired_views(self, allocator):
        a, b = allocator.acquire(), allocator.acquire()
        allocator.release(a)
        assert allocator.active() == frozenset({b})
        assert allocator.retired() == frozenset({a})


class TestExhaustion:
    def test_exhausted_when_all_ids_in_use(self, allocator):
        capacity = SCOPE_ID_MAX - SCOPE_ID_MIN + 1
        for _ in range(capacity):
            allocator.acquire()
        assert allocator.idle == 0
        with pytest.raises(ScopeExhaustedError, match="用尽"):
            allocator.acquire()

    def test_release_unblocks_exhaustion(self, allocator):
        capacity = SCOPE_ID_MAX - SCOPE_ID_MIN + 1
        ids = [allocator.acquire() for _ in range(capacity)]
        allocator.release(ids[0])
        assert allocator.acquire() == ids[0]


class TestWithScope:
    def test_allocated_id_is_a_valid_scope_id(self, allocator):
        """分配器发出的 id 必须能直接用于构造 Scope（值域一致）。"""
        root = Scope(allocator.acquire(), ScopeKind.FILE)
        child = Scope(allocator.acquire(), ScopeKind.FUNCTION, root)
        assert root.scope_id == 1 and child.scope_id == 2
        assert child.describe() == "function#2 -> file#1"

    def test_never_allocates_null_scope_id(self, allocator):
        """0 号留给 NULL 地址，因此分配器永远不能发出 0。"""
        for _ in range(10):
            assert allocator.acquire() != 0
