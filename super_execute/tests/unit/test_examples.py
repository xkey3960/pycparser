"""示例代码不能腐烂：`examples/` 里的样例必须真的能跑出文档里写的数字。

README 和 `examples/run_hello.py` 都写着 `main() = 25`。这里把它钉成测试——
改了解释器导致示例跑不动，会在这里先红，而不是等读者发现文档是错的。
"""

from pathlib import Path

from pycparser.c_parser import CParser

from super_execute.interface_adapters.ast.interpreter import Interpreter

EXAMPLES = Path(__file__).resolve().parents[2] / "examples"


def _run_example(name: str) -> object:
    path = EXAMPLES / name
    source = path.read_text(encoding="utf-8")
    interpreter = Interpreter()
    interpreter.load(CParser().parse(source, path.name), path.name)
    return interpreter.run()


class TestHelloExample:
    def test_hello_c_returns_25(self):
        """(1+2)+1 + (3+4)+1 + (5+6)+2 = 25。"""
        assert _run_example("hello.c") == 25

    def test_example_files_exist(self):
        assert (EXAMPLES / "hello.c").is_file()
        assert (EXAMPLES / "run_hello.py").is_file()
