"""Namespace：一层命名空间的"名字 → 符号"映射。"""

import pytest

from super_execute.domain.entities.namespace import Namespace
from super_execute.domain.entities.symbol import (
    ConstantSymbol,
    TagSymbol,
    VariableSymbol,
)
from super_execute.domain.exceptions import (
    DuplicateSymbolError,
    InvalidSymbolError,
    UndefinedSymbolError,
)
from super_execute.domain.value_objects import (
    Address,
    AddressRegion,
    NamespaceKind,
    TagKind,
)


def _var(name, scope_id=1, offset=0):
    return VariableSymbol(name, Address(AddressRegion.SCOPE, scope_id, offset))


@pytest.fixture
def ordinary():
    return Namespace(NamespaceKind.ORDINARY)


@pytest.fixture
def tags():
    return Namespace(NamespaceKind.TAGS)


class TestDeclareAndLookup:
    def test_declare_then_local(self, ordinary):
        symbol = ordinary.declare(_var("x"))
        assert ordinary.local("x") is symbol

    def test_declare_is_local_only(self, ordinary):
        """Namespace 不做回溯——链是 Scope 的职责。"""
        ordinary.declare(_var("x"))
        assert ordinary.local("y") is None

    def test_require_local_raises_when_missing(self, ordinary):
        with pytest.raises(UndefinedSymbolError, match="ordinary"):
            ordinary.require_local("x")

    def test_duplicate_declare_rejected(self, ordinary):
        ordinary.declare(_var("x"))
        with pytest.raises(DuplicateSymbolError, match="x"):
            ordinary.declare(_var("x"))

    def test_redeclare_overwrites(self, ordinary):
        """extern / 函数原型 / tentative definition 靠它实现（合法性由用例裁决）。"""
        first = ordinary.declare(_var("x", offset=0))
        second = ordinary.redeclare(_var("x", offset=8))
        assert ordinary.local("x") is second
        assert ordinary.local("x") is not first


class TestNamespaceSeparation:
    def test_symbol_must_match_namespace_kind(self, ordinary, tags):
        """标签符号不能塞进普通命名空间，反之亦然。"""
        with pytest.raises(InvalidSymbolError, match="tags"):
            ordinary.declare(TagSymbol("S", TagKind.STRUCT))
        with pytest.raises(InvalidSymbolError, match="ordinary"):
            tags.declare(_var("x"))

    def test_only_symbols_accepted(self, ordinary):
        with pytest.raises(InvalidSymbolError, match="Symbol"):
            ordinary.declare("x")

    def test_same_name_in_both_namespaces(self, ordinary, tags):
        """C 的两个命名空间互不干扰：变量 x 与标签 x 可以同时存在。"""
        ordinary.declare(_var("x"))
        tags.declare(TagSymbol("x", TagKind.STRUCT))
        assert ordinary.local("x").kind.value == "variable"
        assert tags.local("x").kind.value == "tag"


class TestRemoval:
    def test_remove_returns_symbol(self, ordinary):
        symbol = ordinary.declare(_var("x"))
        assert ordinary.remove("x") is symbol
        assert ordinary.local("x") is None

    def test_remove_missing_raises(self, ordinary):
        with pytest.raises(UndefinedSymbolError):
            ordinary.remove("nope")

    def test_clear(self, ordinary):
        ordinary.declare(_var("x"))
        ordinary.declare(_var("y"))
        ordinary.clear()
        assert len(ordinary) == 0


class TestContainerProtocol:
    def test_names_are_insertion_ordered(self, ordinary):
        ordinary.declare(_var("b"))
        ordinary.declare(_var("a"))
        assert ordinary.names() == ("b", "a")

    def test_len_contains_iter(self, ordinary):
        ordinary.declare(_var("x"))
        ordinary.declare(ConstantSymbol("N", 1))
        assert len(ordinary) == 2
        assert "x" in ordinary and "N" in ordinary and "z" not in ordinary
        assert {s.name for s in ordinary} == {"x", "N"}

    def test_repr_lists_names(self, ordinary):
        ordinary.declare(_var("x"))
        assert "x" in repr(ordinary)

    def test_contains_guards_non_string(self, ordinary):
        """`[] in ns` 应该是"不在里面"，而不是 TypeError。"""
        ordinary.declare(_var("x"))
        assert [] not in ordinary
        assert None not in ordinary
        assert 3 not in ordinary
