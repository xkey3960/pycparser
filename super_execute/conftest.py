"""super_execute 的测试引导。

这个包的内层目录才是可导入的 ``super_execute``（外层 ``super_execute/`` 只是
项目根）。本文件把项目根放进 ``sys.path``，这样测试里的
``import super_execute.domain...`` 在任何工作目录下都能解析：

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
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))
