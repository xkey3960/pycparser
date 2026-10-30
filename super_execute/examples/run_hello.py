"""跑 hello.c —— 一个最小的使用示例。

    py examples/run_hello.py

做的事只有三步：

    读源码 → pycparser 解析成 AST → Interpreter 装载并运行

约定：解释器**没有输出语句**（``printf`` 还没做），所以 ``main`` 的返回值就是
程序的结果，由 Python 这边打印出来。
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

from pycparser.c_parser import CParser  # noqa: E402

from super_execute.interface_adapters.ast.interpreter import Interpreter  # noqa: E402

HERE = Path(__file__).resolve().parent


def run(path: Path, entry: str = "main") -> object:
    """读一个 .c 文件，装载，执行入口函数，返回它的返回值。"""
    source = path.read_text(encoding="utf-8")

    # 第二个参数只用于报错定位——报错里会显示 "hello.c:12:9: ..."
    ast = CParser().parse(source, path.name)

    interpreter = Interpreter()
    interpreter.load(ast, path.name)
    return interpreter.run(entry)


def main() -> int:
    result = run(HERE / "hello.c")
    print(f"hello.c 的 main() 返回 {result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
