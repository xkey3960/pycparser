"""用例层：每个用例一件事，依赖通过构造注入。

用例只依赖端口（``application.ports``）与领域对象，不知道 ``SlotMemory``、
``pycparser``、``gcc`` 的存在——这样换内存实现、换解析前端都不动用例。
"""

from super_execute.application.use_cases.address import TakeAddress
from super_execute.application.use_cases.memory_access import LoadValue, StoreValue
from super_execute.application.use_cases.scope_session import ScopeSession
from super_execute.application.use_cases.variables import (
    DeclareVariable,
    DeclareVariableOfName,
    ReadVariable,
    WriteVariable,
    require_variable,
)

__all__ = [
    "DeclareVariable",
    "DeclareVariableOfName",
    "LoadValue",
    "ReadVariable",
    "ScopeSession",
    "StoreValue",
    "TakeAddress",
    "WriteVariable",
    "require_variable",
]
