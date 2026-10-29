"""内存区的具体实现。

本轮（D2 的 Phase A）：值还是 Python 对象，只是**按地址索引**——地址、越界、
悬空这些语义先立起来；Phase B 再把槽里的对象换成字节数组。
"""

from super_execute.frameworks.memory.function_table import FunctionTable
from super_execute.frameworks.memory.slot_memory import SlotMemory

__all__ = ["FunctionTable", "SlotMemory"]
