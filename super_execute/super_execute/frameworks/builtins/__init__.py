"""内建函数（C 标准库的最小实现）。

对外的门面是 :class:`~super_execute.frameworks.builtins.table.BuiltinTable`，
它满足 ``application.ports.builtin_port.BuiltinPort``。
"""

from super_execute.frameworks.builtins.table import SIGNATURES, BuiltinTable

__all__ = ["SIGNATURES", "BuiltinTable"]
