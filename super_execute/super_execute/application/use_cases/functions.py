"""函数声明用例：把函数名绑到函数表，并在作用域里留一个可查的符号。

为什么函数要单独一个用例（而不是当普通变量）：函数名的值不是"存储里的值"，
而是**函数地址**——它进的是 function 区，由函数表发放。TASK.md 的要求是
"函数指针和普通指针同构"，所以这里最终绑定的是一个带真实地址的
``FunctionSymbol``，而不是旧实现里那个"函数名字符串"。

原型可以重复声明（`int f(int); int f(int);`），所以这里用 ``redeclare``。
"""

from __future__ import annotations

from super_execute.application.ports.function_table_port import FunctionTablePort
from super_execute.domain.entities.c_types import FunctionType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import FunctionSymbol
from super_execute.domain.exceptions import InvalidTypeError
from super_execute.domain.value_objects import Address, AddressRegion, Linkage


class DeclareFunction:
    """把一个函数（定义或原型）登记进函数表与作用域。"""

    __slots__ = ("_functions",)

    def __init__(self, functions: FunctionTablePort) -> None:
        self._functions = functions

    def __call__(
        self,
        scope: Scope,
        name: str,
        ctype: FunctionType,
        linkage: Linkage = Linkage.NONE,
    ) -> FunctionSymbol:
        if not isinstance(ctype, FunctionType):
            raise InvalidTypeError(
                f"函数声明需要 FunctionType，收到 {type(ctype).__name__}"
            )
        # 先用占位地址换一个真地址：函数表按登记顺序发号
        placeholder = FunctionSymbol(name, Address(AddressRegion.FUNCTION, 0, 0), ctype)
        address = self._functions.bind(placeholder)

        symbol = FunctionSymbol(name, address, ctype=ctype, linkage=linkage)
        scope.redeclare(symbol)  # 原型可重复声明
        return symbol
