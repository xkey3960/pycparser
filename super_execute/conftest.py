"""super_execute 的测试引导。

这个包的内层目录才是可导入的 ``super_execute``（外层 ``super_execute/`` 只是
项目根）。本文件把两样东西放进 ``sys.path``：

1. 项目根（``super_execute/``）—— 让 ``import super_execute.domain...`` 成立；
2. 它的上一级（仓库根 ``pycparser/``）—— 让适配器能用 ``import pycparser``。
   在仓库根跑 pytest 时本来就在 path 上，从 ``super_execute/`` 里跑时需要显式加。

    cd super_execute && pytest        # 项目根自己
    cd ..            && pytest        # 仓库根（testpaths 里带了 super_execute/tests）

测试目录**故意不放** ``__init__.py``：仓库自带的 ``tests/`` 也叫 tests，
两边都成包会让 pytest 把模块名解析成 ``tests.unit...`` 而撞车
（实测报 ``ModuleNotFoundError: No module named 'tests.unit'``）。
不放包的代价是测试模块按文件名导入，所以文件名必须仓库内唯一——目前没有重名。
"""

import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent
_REPO_ROOT = _PROJECT_ROOT.parent  # pycparser/，里面有 pycparser 包

for _path in (_REPO_ROOT, _PROJECT_ROOT):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
