"""作用域 id 分配器（裁决 D3）。

为什么需要它：地址编码把 scope_id 压成 8 位、0 号留给 NULL，于是同时存活的
作用域最多 255 个。递归一深就会撞到上限，所以 id 必须**可复用**——弹栈时归还，
下次优先复用最小的空闲 id。

复用带来的风险是悬空指针：释放后 id 被新作用域占用，旧地址就会命中新作用域而
不报错。这一半不在这里解决，而是由 ScopeMemory 在弹栈时把整片内存标记为已销毁、
解引用时抛错来兜底（D3 的后半句，随 MemoryRegion 一起落地）。

这里只管"发号"和"记号"，不碰内存，因此是个纯领域服务。
"""

from __future__ import annotations

from super_execute.domain.exceptions import InvalidScopeError, ScopeExhaustedError
from super_execute.domain.value_objects import SCOPE_ID_MAX, SCOPE_ID_MIN


class ScopeIdAllocator:
    """发放 / 回收作用域 id。"""

    __slots__ = ("_active", "_retired", "_next")

    def __init__(self) -> None:
        self._active: set[int] = set()
        self._retired: set[int] = set()
        self._next: int = SCOPE_ID_MIN

    # ---- 发放 ----

    def acquire(self) -> int:
        """取一个空闲 id：优先复用已归还的最小 id，否则用未发放过的下一个。"""
        if self._retired:
            scope_id = min(self._retired)
            self._retired.discard(scope_id)
        elif self._next <= SCOPE_ID_MAX:
            scope_id = self._next
            self._next += 1
        else:
            raise ScopeExhaustedError(
                f"作用域 id 已用尽（{SCOPE_ID_MIN}..{SCOPE_ID_MAX}，"
                f"当前活跃 {len(self._active)} 个）")
        self._active.add(scope_id)
        return scope_id

    # ---- 回收 ----

    def release(self, scope_id: int) -> None:
        """归还一个 id，进入可复用池。"""
        if scope_id not in self._active:
            raise InvalidScopeError(
                f"作用域 id {scope_id} 未被分配或已归还，不能重复归还")
        self._active.discard(scope_id)
        self._retired.add(scope_id)

    # ---- 观测 ----

    def active(self) -> frozenset[int]:
        return frozenset(self._active)

    def retired(self) -> frozenset[int]:
        return frozenset(self._retired)

    @property
    def idle(self) -> int:
        """还可以再发多少个 id。"""
        return (SCOPE_ID_MAX - SCOPE_ID_MIN + 1) - len(self._active)

    def __len__(self) -> int:
        return len(self._active)

    def __repr__(self) -> str:
        return (f"ScopeIdAllocator(active={len(self._active)}, "
                f"retired={len(self._retired)}, next={self._next})")
