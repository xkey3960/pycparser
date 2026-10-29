"""FunctionTable：函数名 ↔ 函数地址。

这是 TASK.md 里"函数名的值应该是地址"的落点：有了函数地址，函数指针才能
存进内存、参与比较；旧实现用的是函数名字符串。
"""

import pytest

from super_execute.domain.entities.symbol import FunctionSymbol, VariableSymbol
from super_execute.domain.exceptions import (
    InvalidSymbolError,
    MemoryAccessError,
    UndefinedSymbolError,
)
from super_execute.domain.value_objects import Address, AddressRegion
from super_execute.frameworks.memory import FunctionTable


def _func(name):
    # 建符号时的地址只是占位，真正的地址由表来发
    return FunctionSymbol(name, Address(AddressRegion.FUNCTION, 0, 0))


@pytest.fixture
def table():
    return FunctionTable()


class TestBind:
    def test_first_function_at_offset_zero(self, table):
        assert table.bind(_func("main")) == Address(AddressRegion.FUNCTION, 0, 0)

    def test_offsets_increase(self, table):
        first = table.bind(_func("main"))
        second = table.bind(_func("log_tx"))
        assert (first.offset, second.offset) == (0, 1)

    def test_same_name_is_idempotent(self, table):
        first = table.bind(_func("main"))
        assert table.bind(_func("main")) == first
        assert len(table) == 1

    def test_rejects_non_function_symbol(self, table):
        var = VariableSymbol("x", Address(AddressRegion.SCOPE, 1, 0))
        with pytest.raises(InvalidSymbolError, match="FunctionSymbol"):
            table.bind(var)


class TestResolve:
    def test_roundtrip(self, table):
        symbol = _func("main")
        address = table.bind(symbol)
        assert table.resolve(address) is symbol

    def test_address_of(self, table):
        address = table.bind(_func("main"))
        assert table.address_of("main") == address
        assert table.address_of("nope") is None

    def test_unknown_offset(self, table):
        with pytest.raises(UndefinedSymbolError, match="没有函数"):
            table.resolve(Address(AddressRegion.FUNCTION, 0, 5))

    def test_non_function_region_rejected(self, table):
        with pytest.raises(MemoryAccessError, match="不是函数地址"):
            table.resolve(Address(AddressRegion.SCOPE, 1, 0))

    def test_non_address_rejected(self, table):
        with pytest.raises(MemoryAccessError, match="Address"):
            table.resolve(0)


class TestContainer:
    def test_contains(self, table):
        table.bind(_func("main"))
        assert "main" in table
        assert "nope" not in table
        assert 42 not in table  # 非字符串不报 TypeError

    def test_len(self, table):
        table.bind(_func("a"))
        table.bind(_func("b"))
        assert len(table) == 2

    def test_repr(self, table):
        table.bind(_func("main"))
        assert "main" in repr(table)
