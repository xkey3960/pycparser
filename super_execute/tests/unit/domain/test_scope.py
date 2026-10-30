"""Scope：作用域链 + 两个命名空间。

这里同时承担"回归锚点"的角色：旧实现实测出来的四条行为被固化成领域级断言，
重构后新实现必须在同一语义下成立（见 tasks/20261017-122900/TASK.md 的实证表）。
"""

import pytest

from super_execute.domain.entities.c_types import Member, StructType
from super_execute.domain.entities.namespace import Namespace
from super_execute.domain.entities.scope import Scope
from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    FunctionSymbol,
    TagSymbol,
    TypedefSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import (
    DuplicateSymbolError,
    InvalidScopeError,
    UndefinedSymbolError,
)
from super_execute.domain.services.builtin_types import (
    DOUBLE,
    INT,
    UNSIGNED_LONG,
)
from super_execute.domain.value_objects import (
    Address,
    AddressRegion,
    Linkage,
    ScopeKind,
    TagKind,
)


def _var(name, scope_id=1, offset=0, **kw):
    return VariableSymbol(name, Address(AddressRegion.SCOPE, scope_id, offset), **kw)


def _func(name, function_id=0, **kw):
    return FunctionSymbol(name, Address(AddressRegion.FUNCTION, 0, function_id), **kw)


# file_scope / function_scope / block_scope 三个夹具见 conftest.py


# ==================== 结构不变量 ====================


class TestStructure:
    def test_file_scope_is_root(self):
        scope = Scope(1, ScopeKind.FILE)
        assert scope.is_root and scope.parent is None

    def test_file_scope_cannot_have_parent(self, file_scope):
        with pytest.raises(InvalidScopeError, match="根"):
            Scope(2, ScopeKind.FILE, file_scope)

    def test_function_scope_requires_file_parent(self, file_scope):
        assert Scope(2, ScopeKind.FUNCTION, file_scope).parent is file_scope
        with pytest.raises(InvalidScopeError, match="文件作用域或翻译单元作用域"):
            Scope(2, ScopeKind.FUNCTION)

    def test_function_scope_accepts_unit_parent(self, file_scope):
        """函数挂在翻译单元下：这样本文件的 static 对该函数可见（D6）。"""
        unit = Scope(2, ScopeKind.UNIT, file_scope)
        assert Scope(3, ScopeKind.FUNCTION, unit).parent is unit

    def test_unit_scope_requires_file_parent(self, file_scope):
        assert Scope(2, ScopeKind.UNIT, file_scope).parent is file_scope
        with pytest.raises(InvalidScopeError, match="翻译单元作用域必须"):
            Scope(2, ScopeKind.UNIT)

    def test_function_scope_rejects_block_parent(self, block_scope):
        """C 的函数不嵌套：函数体看到的外部名字只能来自文件作用域。"""
        with pytest.raises(InvalidScopeError, match="文件/翻译单元作用域"):
            Scope(4, ScopeKind.FUNCTION, block_scope)

    def test_block_scope_nests_freely_and_can_be_root(self, function_scope):
        assert Scope(3, ScopeKind.BLOCK, function_scope).parent is function_scope
        assert Scope(9, ScopeKind.BLOCK).is_root  # 单测/语句表达式便利

    @pytest.mark.parametrize("scope_id", [0, -1, 256, 1000])
    def test_scope_id_range(self, scope_id):
        with pytest.raises(InvalidScopeError, match="scope_id 越界"):
            Scope(scope_id, ScopeKind.FILE)

    def test_scope_id_must_be_int(self):
        with pytest.raises(InvalidScopeError, match="整数"):
            Scope("1", ScopeKind.FILE)

    def test_parent_must_be_scope(self, file_scope):
        with pytest.raises(InvalidScopeError, match="父作用域"):
            Scope(2, ScopeKind.BLOCK, "file_scope")

    def test_both_namespaces_always_present(self, file_scope):
        assert isinstance(file_scope.ordinary, Namespace)
        assert isinstance(file_scope.tags, Namespace)
        assert len(file_scope.ordinary) == 0 and len(file_scope.tags) == 0


# ==================== 绑定路由 ====================


class TestDeclaration:
    def test_variable_goes_to_ordinary(self, function_scope):
        function_scope.declare(_var("x", 2, 0))
        assert "x" in function_scope.ordinary
        assert "x" not in function_scope.tags

    def test_tag_goes_to_tags(self, function_scope):
        function_scope.declare(TagSymbol("P", TagKind.STRUCT))
        assert "P" in function_scope.tags
        assert "P" not in function_scope.ordinary

    def test_declare_all(self, function_scope):
        function_scope.declare_all(_var("x", 2, 0), _var("y", 2, 4))
        assert {"x", "y"} <= set(function_scope.ordinary.names())

    def test_duplicate_in_same_layer_rejected(self, function_scope):
        function_scope.declare(_var("x", 2, 0))
        with pytest.raises(DuplicateSymbolError):
            function_scope.declare(_var("x", 2, 4))

    def test_same_name_in_different_layers_is_shadowing(self, file_scope, block_scope):
        file_scope.declare(_var("x", 1, 0))
        block_scope.declare(_var("x", 3, 0))  # 不报错：不同层
        assert block_scope.find("x").address.scope_id == 3

    @pytest.mark.parametrize("linkage", [Linkage.INTERNAL, Linkage.EXTERNAL])
    def test_linkage_only_on_file_scope(self, block_scope, linkage):
        """D6：internal/external 链接只能出现在文件作用域，替代旧的 g_static_* 侧表。"""
        with pytest.raises(InvalidScopeError, match="文件/翻译单元作用域"):
            block_scope.declare(_var("x", 3, 0, linkage=linkage))

    @pytest.mark.parametrize("linkage", [Linkage.INTERNAL, Linkage.EXTERNAL])
    def test_linkage_allowed_on_file_scope(self, file_scope, linkage):
        file_scope.declare(_var("g", 1, 0, linkage=linkage))
        assert file_scope.find("g").linkage is linkage


# ==================== 查找 ====================


class TestLookup:
    def test_find_walks_chain(self, file_scope, block_scope):
        file_scope.declare(_var("g", 1, 0))
        assert block_scope.find("g") is file_scope.find("g")

    def test_inner_shadows_outer(self, file_scope, block_scope):
        file_scope.declare(_var("x", 1, 0))
        block_scope.declare(_var("x", 3, 0))
        assert block_scope.find("x").address.scope_id == 3  # 内层优先
        assert file_scope.find("x").address.scope_id == 1  # 外层不变

    def test_require_raises_with_search_path(self, block_scope):
        with pytest.raises(UndefinedSymbolError) as info:
            block_scope.require("nope")
        message = str(info.value)
        assert "nope" in message
        assert "block#3" in message and "file#1" in message  # 错误消息带查找路径

    def test_tags_are_searched_separately(self, file_scope, block_scope):
        """标签与普通标识符是两个命名空间：查 find('P') 查不到标签 P。"""
        block_scope.declare(TagSymbol("P", TagKind.STRUCT))
        assert block_scope.find("P") is None
        assert block_scope.find_tag("P") is not None

    def test_same_name_in_both_namespaces(self, block_scope):
        block_scope.declare(_var("P", 3, 0))
        block_scope.declare(TagSymbol("P", TagKind.STRUCT))
        assert block_scope.find("P").kind.value == "variable"
        assert block_scope.find_tag("P").kind.value == "tag"

    def test_require_tag(self, block_scope):
        with pytest.raises(UndefinedSymbolError, match="标签"):
            block_scope.require_tag("Nope")

    def test_contains_uses_chain(self, file_scope, block_scope):
        file_scope.declare(_var("g", 1, 0))
        assert "g" in block_scope
        assert "nope" not in block_scope

    def test_only_ordinary_for_contains(self, block_scope):
        block_scope.declare(TagSymbol("S", TagKind.STRUCT))
        assert "S" not in block_scope


# ==================== 回归锚点：旧实现实测出的四条 ====================


class TestRegressionAnchors:
    """这四条对应 TASK.md 里的实证表，是本轮重构的验收底线。"""

    def test_contract_1_block_typedef_does_not_leak(self, file_scope):
        """实证 1：块内 `typedef double T;` 出块后必须恢复外层 `typedef int T;`。

        旧实现返回 80（块内 typedef 覆盖了全局），正确值是 40。
        """
        file_scope.declare(TypedefSymbol("T", ctype=INT))
        block = Scope(2, ScopeKind.BLOCK, file_scope)
        block.declare(TypedefSymbol("T", ctype=DOUBLE))

        assert block.find("T").ctype is DOUBLE  # 块内遮蔽
        assert file_scope.find("T").ctype is INT  # 出块后不泄漏

    def test_contract_2_sibling_functions_have_independent_tags(self, file_scope):
        """实证 2：两个函数各自定义 `struct P` 必须互不干扰。

        旧实现两次 `sizeof(struct P)` 都返回前一个布局（4+4=8），正确是 4+12=16。
        """
        p1 = StructType("P")
        p1.define([Member("x", INT)])
        p2 = StructType("P")
        p2.define([Member("a", INT), Member("b", INT), Member("c", INT)])

        f1 = Scope(2, ScopeKind.FUNCTION, file_scope)
        f2 = Scope(3, ScopeKind.FUNCTION, file_scope)
        f1.declare(TagSymbol("P", TagKind.STRUCT, ctype=p1))
        f2.declare(TagSymbol("P", TagKind.STRUCT, ctype=p2))

        assert f1.find_tag("P").ctype is p1
        assert f2.find_tag("P").ctype is p2
        assert f1.find_tag("P").ctype.sizeof() + f2.find_tag("P").ctype.sizeof() == 16
        assert file_scope.find_tag("P") is None  # 函数内标签不上升

    def test_contract_3_function_local_tag_invisible_outside(
        self, file_scope, function_scope
    ):
        """实证 3：函数内定义的标签不该出现在文件作用域。"""
        function_scope.declare(TagSymbol("Inner", TagKind.STRUCT))
        assert function_scope.find_tag("Inner") is not None
        assert file_scope.find_tag("Inner") is None

    def test_contract_4_local_variable_invisible_after_block(
        self, file_scope, block_scope
    ):
        """实证 4：块内变量出块即不可见（旧实现这条本来是对的，作为回归保护）。"""
        block_scope.declare(_var("inner", 3, 0))
        assert block_scope.find("inner") is not None
        with pytest.raises(UndefinedSymbolError):
            file_scope.require("inner")


# ==================== 链的结构信息 ====================


class TestChain:
    def test_chain_order_is_inner_to_root(
        self, file_scope, function_scope, block_scope
    ):
        assert block_scope.chain() == (block_scope, function_scope, file_scope)

    def test_depth(self, file_scope, function_scope, block_scope):
        assert file_scope.depth == 0
        assert function_scope.depth == 1
        assert block_scope.depth == 2

    def test_describe(self, block_scope):
        assert block_scope.describe() == "block#3 -> function#2 -> file#1"

    def test_repr_counts_symbols(self, block_scope):
        block_scope.declare(_var("x", 3, 0))
        assert "block#3" in repr(block_scope) and "ordinary=1" in repr(block_scope)

    def test_function_and_constant_symbols_coexist(self, file_scope):
        """普通命名空间里可以放五种绑定中的四种。"""
        file_scope.declare(_func("main", 0))
        file_scope.declare(ConstantSymbol("MAX", 100))
        file_scope.declare(TypedefSymbol("size_t", UNSIGNED_LONG))
        file_scope.declare(_var("g", 1, 0))
        assert len(file_scope.ordinary) == 4


# ==================== 地址归属与覆盖式绑定（review 批次 B） ====================


class TestAddressOwnership:
    """地址里的 scope_id 就是"存储属于哪个作用域"，对不上就是错的绑定。"""

    def test_variable_address_must_belong_to_scope(self, block_scope):
        with pytest.raises(InvalidScopeError, match="属于作用域 #99"):
            block_scope.declare(_var("x", 99, 0))

    def test_matching_address_is_accepted(self, block_scope):
        block_scope.declare(_var("x", 3, 0))
        assert block_scope.find("x") is not None

    def test_redeclare_overwrites(self, block_scope):
        block_scope.declare(_var("x", 3, 0))
        block_scope.redeclare(_var("x", 3, 8))
        assert block_scope.find("x").address.offset == 8

    def test_redeclare_keeps_linkage_check(self, block_scope):
        """redeclare 不能成为绕过链接属性校验的后门。"""
        with pytest.raises(InvalidScopeError, match="文件/翻译单元作用域"):
            block_scope.redeclare(_var("z", 3, 0, linkage=Linkage.INTERNAL))

    def test_redeclare_checks_address_ownership(self, block_scope):
        with pytest.raises(InvalidScopeError, match="属于作用域"):
            block_scope.redeclare(_var("z", 42, 0))

    def test_redeclare_on_file_scope_with_linkage(self, file_scope):
        file_scope.redeclare(_var("g", 1, 0, linkage=Linkage.EXTERNAL))
        assert file_scope.find("g").linkage is Linkage.EXTERNAL


class TestPrototypeScope:
    """原型作用域是四种 C 作用域里唯一没被测过的一支。"""

    def test_prototype_nests_under_function(self, function_scope):
        proto = Scope(7, ScopeKind.PROTOTYPE, function_scope)
        assert proto.parent is function_scope
        assert proto.depth == 2

    def test_prototype_can_be_root_for_tests(self):
        assert Scope(8, ScopeKind.PROTOTYPE).is_root

    def test_contains_guards_non_string(self, block_scope):
        assert [] not in block_scope
        assert None not in block_scope
