"""内建类型表与类型说明符规范化。

尺寸对齐宿主 gcc（LLP64），唯一例外是指针（本项目 4 字节地址）。
"""

import pytest

from super_execute.domain.exceptions import UndefinedTypeError
from super_execute.domain.services.builtin_types import (
    BASIC_TYPES,
    basic,
    canonical_type_name,
    require_basic,
)


class TestTable:
    @pytest.mark.parametrize("name,size,align", [
        ("char", 1, 1),
        ("signed char", 1, 1),
        ("unsigned char", 1, 1),
        ("short int", 2, 2),
        ("int", 4, 4),
        ("unsigned int", 4, 4),
        ("long int", 4, 4),          # LLP64：long 是 4 字节
        ("long long int", 8, 8),
        ("float", 4, 4),
        ("double", 8, 8),
        ("_Bool", 1, 1),
    ])
    def test_sizes_match_host_gcc(self, name, size, align):
        ctype = require_basic(name)
        assert (ctype.sizeof(), ctype.alignof()) == (size, align)

    def test_void_is_listed_but_incomplete(self):
        assert basic("void") is not None
        assert basic("void").is_complete is False

    def test_lookup_miss_returns_none(self):
        assert basic("no_such_type") is None

    def test_require_basic_raises(self):
        with pytest.raises(UndefinedTypeError, match="不是内建类型"):
            require_basic("no_such_type")

    def test_table_keys_match_names(self):
        for name, ctype in BASIC_TYPES.items():
            assert ctype.name == name

    def test_unsigned_variants_are_unsigned(self):
        assert require_basic("unsigned int").is_signed is False
        assert require_basic("int").is_signed is True


class TestCanonicalization:
    @pytest.mark.parametrize("specifiers,expected", [
        (["int"], "int"),
        (["unsigned"], "unsigned int"),
        (["unsigned", "int"], "unsigned int"),
        (["int", "unsigned"], "unsigned int"),          # 顺序任意
        (["signed", "int"], "int"),
        (["long"], "long int"),
        (["long", "long"], "long long int"),
        (["long", "int"], "long int"),
        (["unsigned", "long", "long", "int"], "unsigned long long int"),
        (["short"], "short int"),
        (["unsigned", "short"], "unsigned short int"),
        (["char"], "char"),
        (["signed", "char"], "signed char"),
        (["unsigned", "char"], "unsigned char"),
        (["bool"], "_Bool"),
        (["_Bool"], "_Bool"),
        (["float"], "float"),
        (["double"], "double"),
        (["void"], "void"),
        (["SIGNED", "INT"], "int"),                     # 大小写不敏感
    ])
    def test_valid_combinations(self, specifiers, expected):
        assert canonical_type_name(specifiers) == expected

    @pytest.mark.parametrize("specifiers", [
        (["long", "double"]),        # long double 未支持
        (["short", "long"]),         # 冲突
        (["unsigned", "float"]),     # 无符号浮点不存在
        (["unsigned", "void"]),
        (["long", "long", "long"]),  # 三级 long 不存在
        (["char", "int"]),           # 两个基础类型
        (["char", "short"]),
        (["int", "int"]),            # 重复
        (["MyType"]),                # 不是说明符关键字
    ])
    def test_invalid_combinations_return_none(self, specifiers):
        assert canonical_type_name(specifiers) is None

    def test_empty(self):
        assert canonical_type_name([]) is None
