#!/usr/bin/python
"""test_exe.py — 端到端：CProgram 装载 test/main.c 并运行（pytest 化）

原为脚本式（顶层执行），改为 pytest 可收集函数；保留原语义：
load + link + run，main() = 165。
"""

from program import CProgram
from execute import g_scope


def test_end_to_end_main_c():
    """用 CProgram 装载 test/main.c，link 后运行 main()。"""
    prog = CProgram(['test/main.c'])
    prog.load()
    prog.link()
    result = prog.run()
    assert result == 165, f"期望 165，实际 {result}"
    print(f"main() = {result}")
    print(g_scope)


if __name__ == '__main__':
    test_end_to_end_main_c()
    print("test_exe 端到端通过 ✓")
