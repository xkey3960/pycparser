"""端口：应用层依赖的抽象接口。"""

from super_execute.application.ports.function_table_port import FunctionTablePort
from super_execute.application.ports.memory_port import MemoryPort
from super_execute.application.ports.type_resolver_port import TypeResolverPort

__all__ = ["FunctionTablePort", "MemoryPort", "TypeResolverPort"]
