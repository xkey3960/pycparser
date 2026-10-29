"""领域层：实体、值对象、领域服务、领域错误。

这一层不 import pycparser、不 import 旧 execute.py，也不知道"内存怎么实现"。
"""

from super_execute.domain.entities.c_types import (
    ENUM_ALIGN,
    ENUM_SIZE,
    POINTER_ALIGN,
    POINTER_SIZE,
    ArrayType,
    BasicType,
    CType,
    EnumType,
    FunctionType,
    Member,
    PointerType,
    StructType,
    UnionType,
    align_up,
)
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
from super_execute.domain.services.type_resolver import ScopeTypeResolver
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
    "ENUM_ALIGN",
    "ENUM_SIZE",
    "NULL_ADDRESS",
    "POINTER_ALIGN",
    "POINTER_SIZE",
    "Address",
    "AddressRegion",
    "ArrayType",
    "BasicType",
    "CType",
    "ConstantSymbol",
    "EnumType",
    "FunctionSymbol",
    "FunctionType",
    "Linkage",
    "Member",
    "Namespace",
    "NamespaceKind",
    "ObjectSymbol",
    "PointerType",
    "Scope",
    "ScopeIdAllocator",
    "ScopeKind",
    "ScopeTypeResolver",
    "StructType",
    "Symbol",
    "SymbolKind",
    "TagKind",
    "TagSymbol",
    "TypedefSymbol",
    "UnionType",
    "VariableSymbol",
    "align_up",
]
