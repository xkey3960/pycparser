"""跑 varargs.c —— 用 GNU 扩展解析器 + ``va_arg``。

    py examples/run_varargs.py

和 ``run_hello.py`` 的区别只有一行：解析器换成 :class:`GnuVaArgParser`。

为什么要换：``va_arg(ap, int)`` 的第二个实参是**类型名**，标准 C 语法不认识它
（pycparser 会报 ``Invalid expression``）。``GnuVaArgParser`` 是
``GnuCParser`` 的子类，只多认这一条语法，GNU 扩展（``typeof`` /
``case 1 ... 5`` / 语句表达式）照常可用。

这个 C 程序同时用到了：

* 可变参数 —— ``sum(3, 1, 2, 3)`` 走 ``va_start`` / ``va_arg`` / ``va_end``
* GNU 区间分支 —— ``case 90 ... 100:``
* GNU 语句表达式 —— ``({ int t = ...; t * 2; })``
* GNU ``typeof`` —— ``typeof(int) bonus``
* 内建函数 —— ``printf``（不用 ``#include``）
"""

from __future__ import annotations

import sys
from pathlib import Path

# 让这个脚本从任意目录都能跑：把项目根和仓库根放进 sys.path
_PROJECT_ROOT = Path(__file__).resolve().parent.parent  # super_execute/
_REPO_ROOT = _PROJECT_ROOT.parent  # pycparser/（里面有 pycparser 包）
for _path in (_REPO_ROOT, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from super_execute.interface_adapters.ast.interpreter import Interpreter  # noqa: E402
from super_execute.interface_adapters.ast.va_arg import GnuVaArgParser  # noqa: E402

HERE = Path(__file__).resolve().parent


def run(path: Path, entry: str = "main") -> object:
    """读一个 .c 文件，装载，执行入口函数，返回它的返回值。"""
    source = path.read_text(encoding="utf-8")

    # 第二个参数只用于报错定位——报错里会显示 "varargs.c:12:9: ..."
    ast = GnuVaArgParser().parse(source, path.name)

    interpreter = Interpreter()
    interpreter.load(ast, path.name)
    return interpreter.run(entry)


def main() -> int:
    result = run(HERE / "varargs.c")
    print(f"varargs.c 的 main() 返回 {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
