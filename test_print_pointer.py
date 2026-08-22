#!/usr/bin/python
"""test_print_pointer.py — 链式指针端到端（printf_pointer.c，pytest 化）

原为脚本式：装载 test/printf_pointer.c 并运行 main()（链式指针场景：
&A → &pc->stAAA → (AAA*)pc 强转）。
"""

import contextlib
import io

import execute as exe_mod
from program import CProgram


def test_print_pointer_chain():
    """链式指针：printf_pointer.c 运行不报错（MEM-1 链式指针场景回归）。"""
    exe_mod.setup_global_scope()
    files = ["test/printf_pointer.c"]
    entry = "main"
    prog = CProgram(files, entry=entry)
    prog.load()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = prog.run()          # 不调用 link
    assert result is not None        # 正常返回（无未定义/越界）
    out = buf.getvalue()
    assert 'error' not in out.lower(), f"不应有错误输出: {out}"
    print(f"main() = {result}（链式指针 &A → &pc->stAAA → (AAA*)pc）✓")


if __name__ == '__main__':
    test_print_pointer_chain()
    print("test_print_pointer 通过 ✓")
