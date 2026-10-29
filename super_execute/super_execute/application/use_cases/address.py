"""取地址用例：``&x`` / ``&func``。

C 里 ``&`` 只对**有存储的东西**合法：变量、函数。``&T``（typedef）和
``&ENUM_CONST`` 都是非法的——这就是符号分成"有存储/无存储"两类的意义
（见 domain/entities/symbol.py 的表格）。

函数地址来自函数表而不是作用域：函数名在作用域里可能只是个占位，
真正的地址由 :class:`~super_execute.application.ports.function_table_port.FunctionTablePort`
发放。
"""

from __future__ import annotations

from super_execute.application.ports.function_table_port import FunctionTablePort
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import VariableSymbol
from super_execute.domain.exceptions import NotAValueError, UndefinedSymbolError
from super_execute.domain.value_objects import Address


class TakeAddress:
    """``&name`` → Address。"""

    __slots__ = ("_functions",)

    def __init__(self, functions: FunctionTablePort | None = None) -> None:
        self._functions = functions

    def __call__(self, scope: Scope, name: str) -> Address:
        symbol = scope.find(name)
        if isinstance(symbol, VariableSymbol):
            return symbol.address

        if self._functions is not None:
            address = self._functions.address_of(name)
            if address is not None:
                return address

        if symbol is None:
            raise UndefinedSymbolError(
                f"未定义的名字 '{name}'（查找路径 {scope.describe()}）"
            )
        raise NotAValueError(f"'{name}' 是 {type(symbol).__name__}，没有地址可取")
