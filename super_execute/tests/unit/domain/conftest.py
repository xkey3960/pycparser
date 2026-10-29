"""领域层测试的共享夹具。

作用域的父链在多个测试文件里都要用（Scope / 类型解析），放在这里避免
同一条链在各文件里各写一份、而后逐渐漂开。

    file#1  ←  function#2  ←  block#3

id 用固定值而不是分配器，是为了让 ``describe()`` 的断言可以写死；
分配器自己的行为由 test_scope_id_allocator.py 单独覆盖。
"""

import pytest

from super_execute.domain.entities.scope import Scope
from super_execute.domain.value_objects import ScopeKind


@pytest.fixture
def file_scope():
    """根：文件作用域 #1。"""
    return Scope(1, ScopeKind.FILE)


@pytest.fixture
def function_scope(file_scope):
    """函数作用域 #2，挂在文件作用域下。"""
    return Scope(2, ScopeKind.FUNCTION, file_scope)


@pytest.fixture
def block_scope(function_scope):
    """块作用域 #3，挂在函数作用域下。"""
    return Scope(3, ScopeKind.BLOCK, function_scope)
