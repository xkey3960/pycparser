"""``va_arg`` 支持：自定义解析器 + 自定义 AST 节点。

**不改 pycparser 本体**。这个仓库的 pycparser 是手写递归下降解析器，
所以扩展方式是**继承 + 重载**：子类只在 ``_parse_postfix_expression`` 里
加一条"下一个 token 是 ``va_arg (`` 就走特判"，其余全部交回父类。

为什么必须动解析器：``va_arg(ap, int)`` 的第二个实参是**类型名**，不是表达式，
标准语法分析器不认识它（实测 ``ParseError: Invalid expression, INT``）。
真实 C 里 ``va_arg`` 是预处理阶段的宏，这里是解释器，只能让语法层认识它。

产出的节点是下面的 :class:`VaArgExpr`，求值/推断各自处理。
"""

from __future__ import annotations

from pycparser import c_ast
from pycparser.c_parser import CParser


class VaArgExpr(c_ast.Node):
    """``va_arg(ap, T)``。

    ``ap`` 是表达式（通常是个 ``va_list`` 变量），``type_name`` 是
    :class:`pycparser.c_ast.Typename`——**类型**，所以它不在表达式体系里。
    """

    attr_names = ()

    def __init__(self, ap: c_ast.Node, type_name: c_ast.Typename, coord=None) -> None:
        self.ap = ap
        self.type_name = type_name
        self.coord = coord

    def children(self):
        out = []
        if self.ap is not None:
            out.append(("ap", self.ap))
        if self.type_name is not None:
            out.append(("type_name", self.type_name))
        return tuple(out)


class VaArgParser(CParser):
    """在标准 C 语法上加一条 ``va_arg(expression, type_name)``。

    只重载一个方法：``_parse_postfix_expression``。看到 ``va_arg`` 紧跟 ``(``
    就自己解析这两个实参，其他情况原样交给父类——所以标准语法一点没变。

    两个名字都认：

    * ``va_arg(ap, int)`` —— 不经预处理器直接写；
    * ``__builtin_va_arg(ap, int)`` —— 经**真实 gcc 头文件**预处理后的样子
      （``stdarg.h`` 把 ``va_arg`` 展开成它，类型保留）。

    注意 ``utils/fake_libc_include`` 里的假头文件是
    ``#define va_arg(_ap, _type) __builtin_va_arg((_ap))``——它**把类型丢了**，
    所以用假头文件 + cpp 走的路径无法支持 ``va_arg``（见 README）。
    """

    _VA_ARG_NAMES = ("va_arg", "__builtin_va_arg")

    def _parse_postfix_expression(self) -> c_ast.Node:
        if (
            self._peek_type(1) == "ID"
            and self._peek(1).value in self._VA_ARG_NAMES
            and self._peek_type(2) == "LPAREN"
        ):
            return self._parse_va_arg()
        return super()._parse_postfix_expression()

    def _parse_va_arg(self) -> VaArgExpr:
        tok = self._advance()  # `va_arg` 这个标识符
        coord = self._tok_coord(tok)
        self._expect("LPAREN")
        ap = self._parse_assignment_expression()
        self._expect("COMMA")
        type_name = self._parse_type_name()  # ← 这里是类型，不是表达式
        self._expect("RPAREN")
        return VaArgExpr(ap, type_name, coord)


__all__ = ["VaArgExpr", "VaArgParser"]
