#!/usr/bin/python
"""conftest.py — 仓库根的最小 pytest 配置。

这里**以前**做两件事：每个测试前重置旧解释器的全局状态（``execute.setup_global_scope``）
和清空旧类型注册表（``typesys.g_types``）。旧解释器（execute.py / typesys.py /
program.py / sources.py / cbuiltins.py）已经下线并归档到 ``archive/``，这两条都不再适用：

* 新实现的每个 ``Interpreter`` 自己持有全部状态，测试之间天然隔离；
* 归档的旧测试改用 ``super_execute/compat/run_legacy_tests.py`` 跑在**新实现**上，
  那个运行器自己负责环境准备。

所以这个文件现在只剩说明，不再注册任何 fixture。
"""
