"""旧 ``execute`` 模块的兼容壳。

旧测试只用到几样东西：``setup_global_scope()``、几个异常类型，以及几个**模块级
全局表**（``g_scope`` / ``g_functions`` / ``g_static_funcs`` / ``g_static_globals``）。

前面那些好办，麻烦的是全局表：新实现里根本没有"按文件名分的 static 表"，因为
static 隔离是靠**作用域层级**做到的（翻译单元作用域挂在全程序作用域下）。
所以这里用模块级 ``__getattr__`` 在**访问的那一刻**从新模型投影出旧形状：

    g_static_funcs[文件]  ← 该翻译单元里带 internal 链接的函数符号
    g_static_globals[文件] ← 同样那些变量的**当前值**（真的从内存里读）
    g_functions           ← 外部函数名

这是适配器该干的事：形状是旧的，数据是真的。不是把断言设成恒真。
"""

from __future__ import annotations

from typing import Any

import compat_state

from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    FunctionSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import (
    AllocationError,
    DomainError,
    DivisionByZeroError,
    DuplicateSymbolError,
    IncompleteTypeError,
    InvalidScopeError,
    InvalidSymbolError,
    InvalidTypeError,
    LinkError as _DomainLinkError,
    MemoryAccessError,
    NotAValueError,
    NullPointerError,
    OutOfBoundsError,
    RegionNotImplementedError,
    ScopeDestroyedError,
    UndefinedSymbolError,
    UndefinedLabelError,
    UndefinedTypeError,
    UnresolvedTypeError,
    UnsupportedTypeError,
)
from super_execute.domain.value_objects import Linkage


# ==================== 旧异常体系（继承 AssertionError，保持旧测试约定）====================


class InterpreterError(AssertionError):
    """旧体系基类：旧测试里有大量 ``except AssertionError``。"""


class UndefinedVariable(InterpreterError):
    pass


class TypeError_(InterpreterError):
    pass


class UnsupportedError(InterpreterError):
    pass


class MemoryError_(InterpreterError):
    pass


class LinkError(InterpreterError):
    pass


class GotoException(InterpreterError):
    """旧实现用这个名字表示"标签不存在"。"""


_TRANSLATIONS: tuple[tuple[type, type], ...] = (
    (UndefinedSymbolError, UndefinedVariable),
    (UnresolvedTypeError, UndefinedVariable),
    (UndefinedTypeError, TypeError_),
    (UndefinedLabelError, GotoException),
    (DivisionByZeroError, TypeError_),
    (NotAValueError, TypeError_),
    (InvalidTypeError, TypeError_),
    (InvalidSymbolError, TypeError_),
    (InvalidScopeError, TypeError_),
    (IncompleteTypeError, TypeError_),
    (DuplicateSymbolError, LinkError),
    (_DomainLinkError, LinkError),
    (OutOfBoundsError, MemoryError_),
    (NullPointerError, MemoryError_),
    (ScopeDestroyedError, MemoryError_),
    (AllocationError, MemoryError_),
    (RegionNotImplementedError, MemoryError_),
    (MemoryAccessError, MemoryError_),
    (UnsupportedTypeError, UnsupportedError),
)


def translate(error: DomainError) -> InterpreterError:
    """把新实现的领域错误翻成旧测试期待的类型。"""
    for source, target in _TRANSLATIONS:
        if isinstance(error, source):
            return target(str(error))
    return InterpreterError(str(error))


def _symbol_value(interpreter: Any, symbol: Any) -> Any:
    """旧符号表里 ``get(name)`` 拿到的"值"。

    常量直接是值、变量从内存读，函数和类型没有值，就把符号本身给出去。
    """
    if isinstance(symbol, ConstantSymbol):
        return symbol.value
    if isinstance(symbol, VariableSymbol) and symbol.ctype is not None:
        try:
            return interpreter.memory.read(symbol.address, symbol.ctype)
        except Exception:  # 地址还没初始化好（例如装载阶段）→ 退回符号
            return symbol
    return symbol


# ==================== 旧 API ====================


def setup_global_scope() -> None:
    """旧测试每个用例前调用：重置解释器状态。"""
    compat_state.reset()


class _ScopeFacade:
    """``g_scope`` 的替身。

    旧测试拿它做三件事：``print``、``g_scope.get(name)``、``g_scope._symbols``。

    **``get`` 返回的是"值"，不是符号**——旧的符号表就存着值。所以常量给
    ``.value``、变量去内存里读，函数/类型这类没有值的给符号本身。
    """

    def _interpreter(self) -> Any:
        return compat_state.get_current()

    def get(self, name: str, default: Any = None) -> Any:
        interpreter = self._interpreter()
        if interpreter is None:
            return default
        symbol = interpreter.globals.find(name)
        if symbol is None:
            return default
        return _symbol_value(interpreter, symbol)

    @property
    def _symbols(self) -> dict[str, Any]:
        interpreter = self._interpreter()
        if interpreter is None:
            return {}
        names: dict[str, Any] = {}
        for symbols in interpreter.all_unit_symbols().values():
            for symbol in symbols:
                if getattr(symbol, "name", None):
                    names.setdefault(symbol.name, symbol)
        return names

    def __str__(self) -> str:
        interpreter = self._interpreter()
        if interpreter is None:
            return "Scope()"
        return str(interpreter.globals)

    __repr__ = __str__


g_scope = _ScopeFacade()

#: 旧测试里有 `assert len(exe_mod.g_call_stack) == 0` 这样的断言。
#: 新实现没有全局调用栈（每次调用就是 Python 的递归 + 一个作用域），
#: 所以这里给一个恒为空的列表——**这条断言在兼容层下恒真，不构成等价性证据**。
g_call_stack: list = []


# ==================== 旧全局表（按新模型实时投影）====================


def _statics(interpreter, want_functions: bool) -> dict[str, dict[str, Any]]:
    projected: dict[str, dict[str, Any]] = {}
    for path, symbols in interpreter.all_unit_symbols().items():
        selected = {}
        for symbol in symbols:
            if getattr(symbol, "linkage", None) is not Linkage.INTERNAL:
                continue
            if want_functions and isinstance(symbol, FunctionSymbol):
                selected[symbol.name] = symbol
            elif not want_functions and isinstance(symbol, VariableSymbol):
                selected[symbol.name] = symbol
        projected[path] = selected
    return projected


def _static_global_values() -> dict[str, dict[str, Any]]:
    interpreter = compat_state.get_current()
    if interpreter is None:
        return {}
    values: dict[str, dict[str, Any]] = {}
    for path, symbols in _statics(interpreter, want_functions=False).items():
        row = {}
        for name, symbol in symbols.items():
            if symbol.ctype is None:
                continue
            row[name] = interpreter.memory.read(symbol.address, symbol.ctype)
        values[path] = row
    return values


def _external_functions() -> dict[str, Any]:
    interpreter = compat_state.get_current()
    if interpreter is None:
        return {}
    table = {}
    for symbols in interpreter.all_unit_symbols().values():
        for symbol in symbols:
            if (
                isinstance(symbol, FunctionSymbol)
                and symbol.linkage is not Linkage.INTERNAL
            ):
                table.setdefault(symbol.name, symbol)
    return table


def __getattr__(name: str) -> Any:
    """模块级惰性属性：旧测试读全局表的那一刻才投影。"""
    if name == "g_static_funcs":
        interpreter = compat_state.get_current()
        return {} if interpreter is None else _statics(interpreter, want_functions=True)
    if name == "g_static_globals":
        return _static_global_values()
    if name == "g_functions":
        return _external_functions()
    if name == "g_types":
        return g_types
    raise AttributeError(f"module 'execute' has no attribute {name!r}")


class _LegacyType:
    """把新实现的 ``CType`` 包一层，把 ``is_complete`` 还原成**方法**。

    新领域模型里 ``is_complete`` 是属性（`if ctype.is_complete:`），旧 API 里是
    方法（`ctype.is_complete()`）。兼容层负责这个形状差异，不改领域模型。
    """

    __slots__ = ("_ctype",)

    def __init__(self, ctype: Any) -> None:
        self._ctype = ctype

    def is_complete(self) -> bool:
        return bool(getattr(self._ctype, "is_complete", False))

    def sizeof(self) -> int:
        return self._ctype.sizeof()

    def alignof(self) -> int:
        return self._ctype.alignof()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._ctype, name)

    def __repr__(self) -> str:
        return f"LegacyType({self._ctype!r})"


class _TypeTable:
    """``g_types`` 的替身：只需要 ``lookup_tag(kind, name)``。

    旧实现的类型表是全局扁平的；新实现把标签存在作用域的 tags 命名空间里。
    这里投影"登记过哪些标签"——**注意**：惰性模式下类型可能只注册、没布局，
    ``is_complete()`` 因此是 False，这正是旧测试要观察的状态。
    """

    def lookup_tag(self, kind: str, name: str) -> Any:
        interpreter = compat_state.get_current()
        if interpreter is None:
            return None
        ctype = interpreter.tag_registry.get((kind, name))
        return None if ctype is None else _LegacyType(ctype)

    def __str__(self) -> str:
        interpreter = compat_state.get_current()
        if interpreter is None:
            return "TypeTable()"
        return str(sorted(interpreter.tag_registry))


g_types = _TypeTable()


def execute(node, *_args, **_kwargs):  # pragma: no cover - 旧测试基本不用
    """旧模块还把 ``execute`` 当函数导出；这里给个明确的失败。"""
    raise UnsupportedError("兼容层没有实现单节点 execute()，请用 program.CProgram")
