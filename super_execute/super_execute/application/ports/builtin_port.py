"""内建函数端口。

C 程序离不开 `printf` / `strlen` / `malloc` 这些库函数，本解释器不链接 libc，
而是用 Python 实现一份最小集合。这一层只定义**契约**：

* ``has`` / ``signature`` —— 解释器据此做"隐式声明"（像 C89 那样：没声明也能用）；
* ``call`` —— 真正执行，返回 C 语义下的值。

实现放在 ``frameworks/builtins/``，所以 domain / application 不依赖任何具体内建。
"""

from __future__ import annotations

from typing import Any, Protocol

from super_execute.domain.entities.c_types import FunctionType


class ProgramExit(Exception):
    """``exit(code)``：终止程序。

    它不是"错误"，所以不继承 ``DomainError``——``Interpreter.run`` 会捕获它，
    直接把 ``code`` 当作程序结果返回。
    """

    def __init__(self, code: int) -> None:
        super().__init__(code)
        self.code = code


class BuiltinPort(Protocol):
    """内建函数表。"""

    def has(self, name: str) -> bool:
        """有没有这个内建函数。"""

    def signature(self, name: str) -> FunctionType:
        """它的签名（返回类型 + 形参类型），用于隐式声明与类型推断。"""

    def call(self, name: str, args: list[Any]) -> Any:
        """按 C 语义执行，返回结果值。"""

    def names(self) -> list[str]:
        """全部内建函数名（调试与文档用）。"""
