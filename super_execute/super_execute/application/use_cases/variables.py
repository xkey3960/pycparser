"""变量相关的用例：声明、读、写。

这三件事在旧实现里分别是 ``ExeDecl`` 里的一行 ``g_scope.declare``、48 处
``g_scope.get`` 和 8 处 ``g_scope.set``——名字和值直接绑在 Python dict 里。
现在拆开成：**作用域负责名字，内存负责值**，地址负责把两边接上。

    declare:  名字 → 类型 → 分配 → 地址 → 绑进作用域
    read   :  名字 → 符号 → 地址 + 类型 → 内存读
    write  :  名字 → 符号 → 地址 + 类型 → 内存写

声明拆成两个用例，因为 C 的**声明符**比类型名丰富：``int x`` 的类型来自
名字（``IdentifierType``），而 ``struct P *p`` / ``int a[3]`` 的类型来自
声明符上的 ``PtrDecl`` / ``ArrayDecl``——后者必须由调用方先构造成 ``CType``。
把它们强行塞进一个"类型名列表"参数，迟早要在里面拼 ``"*"`` 这种伪语法。
"""

from __future__ import annotations

from typing import Any, Sequence

from super_execute.application.ports.memory_port import MemoryPort
from super_execute.application.ports.type_resolver_port import TypeResolverPort
from super_execute.domain.entities.c_types import CType
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import VariableSymbol
from super_execute.domain.exceptions import (
    DuplicateSymbolError,
    InvalidTypeError,
    NotAValueError,
    UnresolvedTypeError,
)


def require_variable(scope: Scope, name: str) -> VariableSymbol:
    """按名字取一个可以读写值的变量；不是变量就报错。"""
    symbol = scope.require(name)  # 找不到 → UndefinedSymbolError
    if not isinstance(symbol, VariableSymbol):
        raise NotAValueError(f"'{name}' 是 {type(symbol).__name__}，不是可以读写的变量")
    if symbol.ctype is None:
        raise UnresolvedTypeError(f"变量 '{name}' 的类型尚未解析")
    return symbol


class DeclareVariable:
    """按**已解析的类型**声明变量并分配存储。

    指针、数组这些派生类型由调用方从声明符构造好后传进来。
    """

    __slots__ = ("_memory",)

    def __init__(self, memory: MemoryPort) -> None:
        self._memory = memory

    def __call__(
        self,
        scope: Scope,
        name: str,
        ctype: CType,
        initial: Any = None,
    ) -> VariableSymbol:
        if not isinstance(ctype, CType):
            raise InvalidTypeError(f"声明需要 CType，收到 {type(ctype).__name__}")
        # 先查重再分配：分配是单调向前的，重复声明不能白吃一段存储
        if scope.ordinary.local(name) is not None:
            raise DuplicateSymbolError(f"作用域里已经有 '{name}' 了")

        address = self._memory.allocate(scope.scope_id, ctype)
        symbol = VariableSymbol(name, address, ctype=ctype)
        scope.declare(symbol)
        if initial is not None:
            self._memory.write(address, initial, ctype)
        return symbol


class DeclareVariableOfName:
    """按类型**名字**声明变量（``int x;`` / ``struct P p;`` / ``MyTypedef t;``）。"""

    __slots__ = ("_declare", "_resolver")

    def __init__(self, memory: MemoryPort, resolver: TypeResolverPort) -> None:
        self._declare = DeclareVariable(memory)
        self._resolver = resolver

    def __call__(
        self,
        scope: Scope,
        name: str,
        type_names: Sequence[str],
        initial: Any = None,
    ) -> VariableSymbol:
        ctype = self._resolver.resolve(scope, type_names)
        return self._declare(scope, name, ctype, initial)


class ReadVariable:
    """读一个变量的值（经它的地址）。"""

    __slots__ = ("_memory",)

    def __init__(self, memory: MemoryPort) -> None:
        self._memory = memory

    def __call__(self, scope: Scope, name: str) -> Any:
        symbol = require_variable(scope, name)
        return self._memory.read(symbol.address, symbol.ctype)


class WriteVariable:
    """写一个变量的值（经它的地址）。"""

    __slots__ = ("_memory",)

    def __init__(self, memory: MemoryPort) -> None:
        self._memory = memory

    def __call__(self, scope: Scope, name: str, value: Any) -> None:
        symbol = require_variable(scope, name)
        self._memory.write(symbol.address, value, symbol.ctype)
