#!/usr/bin/python
"""conftest.py — pytest 统一配置（QOL-5 测试统一）

作用：
  1. 每个测试前重置解释器全局状态（g_scope/g_functions/调用栈 等）
     —— 对应 execute.setup_global_scope()；
  2. 清空类型注册表的用户定义（tags/aliases），保留内建类型
     —— 解决跨文件/跨测试同名标签冲突（struct S、struct Node 等），
        各测试真正隔离，不再依赖"夹具命名全局唯一"。
  3. 恢复当前工作目录（部分测试用相对路径写 test/multi/*.c）。

用法：仓库根执行 `pytest`（见 pytest.ini）即可跑完全部测试：
  本地解释器测试（test_*.py）+ 上游 pycparser 测试（tests/）。
"""

import os

import pytest

import execute as exe_mod
from typesys import g_types


@pytest.fixture(autouse=True)
def _reset_interpreter_state():
    """每个测试前重置解释器全局状态与类型注册表（用户定义部分）。"""
    # 1) 作用域 / 函数表 / 调用栈 / static 表 / jmp 缓冲（execute 自带的复位）
    exe_mod.setup_global_scope()
    # 2) 类型注册表：清用户标签与 typedef，保留内建（builtins）
    g_types.tags.clear()
    g_types.aliases.clear()
    # 3) 工作目录兜底（pytest 从仓库根收集；个别测试可能 chdir）
    yield
    # 测试后不清理（每个测试前重置即可）
