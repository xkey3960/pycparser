"""进入 / 退出作用域。

这是第一件"跨层"的事：作用域 id 来自领域服务、作用域对象来自实体、存储来自端口。
把它收成一个用例，是为了让三者的顺序和失败回滚只写一遍——

    分配 id → 建 Scope → 建存储
    销毁存储 → 归还 id

如果调用方各自拼这几步，迟早会漏掉"建存储失败时把 id 退回去"这类收尾，
而 id 只有 255 个，漏几次就耗尽。
"""

from __future__ import annotations

from super_execute.application.ports.memory_port import MemoryPort
from super_execute.domain.entities.scope import Scope
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.value_objects import ScopeKind


class ScopeSession:
    """受控地开关作用域（id 与存储成对）。"""

    __slots__ = ("_allocator", "_memory")

    def __init__(self, allocator: ScopeIdAllocator, memory: MemoryPort) -> None:
        self._allocator = allocator
        self._memory = memory

    def open(self, kind: ScopeKind, parent: Scope | None = None) -> Scope:
        """开一个作用域：发 id、建 Scope、建存储。"""
        scope = self._allocator.open(kind, parent)
        try:
            self._memory.create_scope(scope.scope_id)
        except Exception:
            # 存储没建起来就把 id 退回去，不然 255 个 id 会被慢慢吃掉
            self._allocator.close(scope)
            raise
        return scope

    def close(self, scope: Scope) -> None:
        """关一个作用域：销毁存储、归还 id。"""
        self._memory.destroy_scope(scope.scope_id)
        self._allocator.close(scope)

    def __repr__(self) -> str:  # pragma: no cover - 调试用
        return f"ScopeSession({self._allocator!r})"
