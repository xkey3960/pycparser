"""兼容壳之间共享的"当前程序"状态。

旧的 ``execute`` 模块靠一堆模块级全局（``g_scope`` / ``g_functions``）串起来，
``setup_global_scope()`` 负责把它们重置。新实现把这些状态收进了
:class:`~super_execute.interface_adapters.ast.interpreter.Interpreter` 实例，
所以这里只需要记住"当前实例"。
"""

from __future__ import annotations

from typing import Any

_current: Any = None
_loaded: dict[str, Any] = {}


def set_current(interpreter: Any) -> None:
    global _current
    _current = interpreter


def get_current() -> Any:
    return _current


def remember_ast(name: str, ast: Any) -> None:
    _loaded[name] = ast


def loaded_asts() -> dict[str, Any]:
    return dict(_loaded)


def reset() -> None:
    global _current
    _current = None
    _loaded.clear()
