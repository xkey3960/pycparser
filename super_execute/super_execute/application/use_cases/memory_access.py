"""指针访问用例：``*p`` 读、``*p = v`` 写。

这两件事看起来只是 ``memory.read/write`` 的转发，但它们多守一条 C 的规则：
**解引用 NULL 是错的**。把这条放在用例层，是因为它属于语言语义，
而内存实现只关心"地址落在哪个对象里"——NULL 在内存看来只是"0 号作用域 0 偏移"，
它甚至不知道那代表空指针。
"""

from __future__ import annotations

from typing import Any

from super_execute.application.ports.memory_port import MemoryPort
from super_execute.domain.entities.c_types import CType
from super_execute.domain.exceptions import NullPointerError, MemoryAccessError
from super_execute.domain.value_objects import Address


def _require_dereferenceable(address: Address) -> None:
    if not isinstance(address, Address):
        raise MemoryAccessError(f"需要 Address，收到 {type(address).__name__}")
    if address.is_null:
        raise NullPointerError("解引用 NULL 指针")


class LoadValue:
    """``*p``：按 ``ctype`` 读地址上的值。"""

    __slots__ = ("_memory",)

    def __init__(self, memory: MemoryPort) -> None:
        self._memory = memory

    def __call__(self, address: Address, ctype: CType) -> Any:
        _require_dereferenceable(address)
        return self._memory.read(address, ctype)


class StoreValue:
    """``*p = v``：按 ``ctype`` 把值写到地址上。"""

    __slots__ = ("_memory",)

    def __init__(self, memory: MemoryPort) -> None:
        self._memory = memory

    def __call__(self, address: Address, value: Any, ctype: CType) -> None:
        _require_dereferenceable(address)
        self._memory.write(address, value, ctype)
