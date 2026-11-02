"""示例代码不能腐烂：`examples/` 里的样例必须真的能跑出文档里写的数字。

README 和 `examples/run_hello.py` 都写着 `main() = 25`，
`examples/run_varargs.py` 也写着 25。这里把它们钉成测试——
改了解释器导致示例跑不动，会在这里先红，而不是等读者发现文档是错的。
"""

from pathlib import Path

import pytest
from pycparser.c_parser import CParser

from super_execute.interface_adapters.ast.interpreter import Interpreter
from super_execute.interface_adapters.ast.va_arg import GnuVaArgParser, VaArgParser

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _run_example(name: str, parser=None) -> object:
    path = EXAMPLES / name
    source = path.read_text(encoding="utf-8")
    interpreter = Interpreter()
    interpreter.load((parser or CParser)().parse(source, path.name), path.name)
    return interpreter.run()


class TestHelloExample:
    def test_hello_c_returns_25(self):
        """(1+2)+1 + (3+4)+1 + (5+6)+2 = 25。"""
        assert _run_example("hello.c") == 25

    def test_example_files_exist(self):
        assert (EXAMPLES / "hello.c").is_file()
        assert (EXAMPLES / "run_hello.py").is_file()


class TestVarArgsExample:
    """GNU 扩展 + `va_arg` 的示例：sum(2,5,6)=11 → bonus=22，grade(85)=3。"""

    def test_varargs_c_returns_25(self):
        assert _run_example("varargs.c", GnuVaArgParser) == 25

    def test_varargs_needs_va_arg_parser(self):
        """对照：标准 CParser 解析不了它——这正是示例换解析器的原因。"""
        with pytest.raises(Exception, match="Invalid expression"):
            _run_example("varargs.c", CParser)

    def test_gnu_parser_required(self):
        """`typeof` / `case 1 ... 5` 也要 GNU 解析器，VaArgParser 不够。"""
        with pytest.raises(Exception):
            _run_example("varargs.c", VaArgParser)

    def test_example_files_exist(self):
        assert (EXAMPLES / "varargs.c").is_file()
        assert (EXAMPLES / "run_varargs.py").is_file()
