"""函数表端口：用例需要"函数名 → 函数地址"时从这里要。"""

from typing import Protocol, runtime_checkable

from super_execute.domain.value_objects import Address


@runtime_checkable
class FunctionTablePort(Protocol):
    """函数地址表。

    ``&func`` 与间接调用都要它：函数名的值就是它的地址（TASK.md 的要求），
    而不是旧实现里那个"函数名字符串"。
    """

    def address_of(self, name: str) -> Address | None:
        """函数名 → 地址；没有这个函数返回 None。"""

    def resolve(self, address: Address) -> object:
        """函数地址 → 函数符号（间接调用时用）。"""
