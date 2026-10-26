"""领域层：实体、值对象、领域服务、领域错误。

这一层不 import pycparser、不 import 旧 execute.py，也不知道"内存怎么实现"。
"""

from super_execute.domain.entities.namespace import Namespace
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    FunctionSymbol,
    ObjectSymbol,
    Symbol,
    TagSymbol,
    TypedefSymbol,
    VariableSymbol,
)
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.value_objects import (
    NULL_ADDRESS,
    Address,
    AddressRegion,
    Linkage,
    NamespaceKind,
    ScopeKind,
    SymbolKind,
    TagKind,
)

__all__ = [
    "NULL_ADDRESS",
    "Address",
    "AddressRegion",
    "ConstantSymbol",
    "FunctionSymbol",
    "Linkage",
    "Namespace",
    "NamespaceKind",
    "ObjectSymbol",
    "Scope",
    "ScopeIdAllocator",
    "ScopeKind",
    "Symbol",
    "SymbolKind",
    "TagKind",
    "TagSymbol",
    "TypedefSymbol",
    "VariableSymbol",
]
