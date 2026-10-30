"""旧 ``execute`` 模块的兼容壳。

旧测试只用到两样东西：``setup_global_scope()`` 和几个异常类型。
异常这里做一次**翻译**：新实现的错误是 ``DomainError`` 树，旧测试期望
``InterpreterError``（继承 ``AssertionError``）及其子类。翻译放在
``program.CProgram.run`` 里做，这样 ``except UndefinedVariable`` 之类的断言还能用。
"""

from __future__ import annotations

import compat_state

from super_execute.domain.exceptions import (
    AllocationError,
    DomainError,
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
    UnresolvedTypeError,
    UnsupportedTypeError,
    UndefinedSymbolError,
    UndefinedTypeError,
)


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


_TRANSLATIONS: tuple[tuple[type, type], ...] = (
    (UndefinedSymbolError, UndefinedVariable),
    (UnresolvedTypeError, UndefinedVariable),
    (UndefinedTypeError, TypeError_),
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
            # 有 message 属性就用它（新错误的 message 与 str() 一致）
            return target(str(error))
    return InterpreterError(str(error))


# ==================== 旧 API ====================


def setup_global_scope() -> None:
    """旧测试每个用例前调用：重置解释器状态。"""
    compat_state.reset()


class _ScopeFacade:
    """``g_scope`` 的占位：旧测试只把它 ``print`` 出来，不读内容。"""

    def __str__(self) -> str:
        interpreter = compat_state.get_current()
        if interpreter is None:
            return "Scope()"
        return str(interpreter.globals)

    __repr__ = __str__


g_scope = _ScopeFacade()

#: 旧测试里有 `assert len(exe_mod.g_call_stack) == 0` 这样的断言。
#: 新实现没有全局调用栈（每次调用就是 Python 的递归 + 一个作用域），
#: 所以这里给一个恒为空的列表——**这条断言在兼容层下恒真，不构成等价性证据**。
g_call_stack: list = []


def execute(node, *_args, **_kwargs):  # pragma: no cover - 旧测试基本不用
    """旧模块还把 ``execute`` 当函数导出；这里给个明确的失败。"""
    raise UnsupportedError("兼容层没有实现单节点 execute()，请用 program.CProgram")
