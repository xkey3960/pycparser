"""C 的整数算术细节。

看起来只是两个小函数，但它们是**求值器**和**常量折叠器**唯一的共识点：
`7/2` 是 3 而不是 3.5，`-7/2` 是 -3 而不是 -4（Python 的 `//` 向下取整），
`-7%3` 是 -1 而不是 2。两边各写一份迟早漂开，所以放这里。
"""

from __future__ import annotations

from super_execute.domain.exceptions import DivisionByZeroError


def c_div(left: int, right: int) -> int:
    """C 的整数除法：向零截断。"""
    if right == 0:
        raise DivisionByZeroError("除数为 0")
    quotient = abs(left) // abs(right)
    return quotient if (left >= 0) == (right >= 0) else -quotient


def c_mod(left: int, right: int) -> int:
    """C 的取模：结果与被除数同号。"""
    if right == 0:
        raise DivisionByZeroError("除数为 0")
    return left - c_div(left, right) * right
