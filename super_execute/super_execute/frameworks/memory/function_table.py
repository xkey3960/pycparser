"""function 区：函数表，把"函数名"变成"函数地址"。

TASK.md 的要求是：函数名的值应该是**函数对应的地址**，这样函数指针和普通指针
同构——能存进内存、能比较、能放进数组。旧实现用"函数名字符串"当指针
（`execute.py:774`），这三件事都做不到。

function 区没有字节偏移概念，:class:`~super_execute.domain.value_objects.Address`
的 offset 在这里是**表下标**（第几个登记的函数），不是字节。所以函数指针不能
做算术——C 里对函数指针做算术本来就是非法的。
"""

from __future__ import annotations

from super_execute.domain.entities.symbol import FunctionSymbol
from super_execute.domain.exceptions import (
    InvalidSymbolError,
    MemoryAccessError,
    UndefinedSymbolError,
)
from super_execute.domain.value_objects import Address, AddressRegion


class FunctionTable:
    """函数地址表。"""

    __slots__ = ("_by_address", "_by_name")

    def __init__(self) -> None:
        self._by_address: dict[int, FunctionSymbol] = {}
        self._by_name: dict[str, Address] = {}

    # ---- 登记 ----

    def bind(self, symbol: FunctionSymbol) -> Address:
        """登记一个函数，返回它的地址；同名重复登记是幂等的。"""
        if not isinstance(symbol, FunctionSymbol):
            raise InvalidSymbolError(
                f"函数表只能登记 FunctionSymbol，收到 {type(symbol).__name__}"
            )
        existing = self._by_name.get(symbol.name)
        if existing is not None:
            return existing
        offset = len(self._by_address)
        address = Address(AddressRegion.FUNCTION, 0, offset)
        self._by_address[offset] = symbol
        self._by_name[symbol.name] = address
        return address

    # ---- 查询 ----

    def resolve(self, address: Address) -> FunctionSymbol:
        """按函数地址找回符号（间接调用走这里）。"""
        if not isinstance(address, Address):
            raise MemoryAccessError(f"需要 Address，收到 {type(address).__name__}")
        if address.region is not AddressRegion.FUNCTION:
            raise MemoryAccessError(f"不是函数地址（落在 {address.region.name} 区）")
        symbol = self._by_address.get(address.offset)
        if symbol is None:
            raise UndefinedSymbolError(f"函数区偏移 {address.offset} 上没有函数")
        return symbol

    def address_of(self, name: str) -> Address | None:
        return self._by_name.get(name)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._by_name

    def __len__(self) -> int:
        return len(self._by_address)

    def __repr__(self) -> str:
        return f"FunctionTable({sorted(self._by_name)!r})"
