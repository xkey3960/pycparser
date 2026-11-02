"""``va_arg`` 支持：自定义解析器 + 自定义 AST 节点。

**不改 pycparser 本体**。这个仓库的 pycparser 是手写递归下降解析器，
所以扩展方式是**继承 + 重载**：只重载 ``_parse_postfix_expression``，
看到 ``va_arg`` 紧跟 ``(`` 就自己解析那两个实参，其余全部交回父类。

为什么必须动解析器：``va_arg(ap, int)`` 的第二个实参是**类型名**，不是表达式，
标准语法分析器不认识它（实测 ``ParseError: Invalid expression, INT``）。
真实 C 里 ``va_arg`` 是预处理阶段的宏，这里是解释器，只能让语法层认识它。

两个现成的解析器：

* :class:`VaArgParser` —— 标准 C + ``va_arg``；
* :class:`GnuVaArgParser` —— GNU 扩展（``typeof`` / ``case 1 ... 5`` /
  语句表达式 ...）+ ``va_arg``，需要 ``pycparserext``。

两者共用一个 mixin，所以新增的语法只有一处。
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


class _VaArgMixin:
    """只加一条语法：``va_arg(expression, type_name)``。

    用 mixin 是为了让"标准解析器"和"GNU 扩展解析器"共用这一条规则——
    两边都只多这一处，上游代码零改动。

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


class VaArgParser(_VaArgMixin, CParser):
    """标准 C + ``va_arg``。"""


try:  # pycparserext 是可选依赖
    from pycparserext.ext_c_parser import GnuCParser as _GnuCParser
except ImportError:  # pragma: no cover - 取决于环境
    _GnuCParser = None  # type: ignore[assignment,misc]


if _GnuCParser is not None:

    class GnuVaArgParser(_VaArgMixin, _GnuCParser):  # type: ignore[misc,valid-type]
        """GNU 扩展 + ``va_arg``。

        ``GnuCParser`` 自己也重载了 ``_parse_postfix_expression``（处理
        ``__builtin_types_compatible_p``），所以 MRO 是
        ``GnuVaArgParser → _VaArgMixin → GnuCParser → CParser``：
        先看是不是 ``va_arg``，不是就交给 GNU 那一层，再交给标准层。
        """

else:  # pragma: no cover - 取决于环境

    class GnuVaArgParser:  # type: ignore[no-redef]
        """没有 ``pycparserext`` 时的占位：一构造就报清楚的错。"""

        def __init__(self, *args, **kwargs) -> None:
            raise ImportError(
                "GnuVaArgParser 需要 pycparserext（pip install pycparserext）；"
                "只用标准 C 的话请改用 VaArgParser"
            )


__all__ = ["GnuVaArgParser", "VaArgExpr", "VaArgParser"]
