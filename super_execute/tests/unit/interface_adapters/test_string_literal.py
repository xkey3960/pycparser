"""字符串字面量的解码。

pycparser 把字面量原样放在 ``Constant.value`` 里（带引号也带转义），
所以这里的输入是**源码原样**，输出是真正要写进内存的字符。
"""

import pytest

from super_execute.interface_adapters.ast.string_literal import decode_string_literal


class TestPlain:
    def test_ascii(self):
        assert decode_string_literal('"abc"') == "abc"

    def test_empty(self):
        assert decode_string_literal('""') == ""

    def test_chinese(self):
        assert decode_string_literal('"中文"') == "中文"

    def test_spaces_and_punctuation(self):
        assert decode_string_literal('"a b!"') == "a b!"


class TestEscapes:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ('"\\n"', "\n"),
            ('"\\t"', "\t"),
            ('"\\r"', "\r"),
            ('"\\0"', "\0"),
            ('"\\\\"', "\\"),
            ('"\\""', '"'),
        ],
    )
    def test_simple_escapes(self, raw, expected):
        assert decode_string_literal(raw) == expected

    def test_hex_escape(self):
        assert decode_string_literal('"\\x41"') == "A"

    def test_octal_escape(self):
        assert decode_string_literal('"\\101"') == "A"

    def test_mixed_content(self):
        assert decode_string_literal('"a\\tb\\nc"') == "a\tb\nc"

    def test_unknown_escape_kept_as_is(self):
        """不认识的转义原样保留那个字符，不能丢掉。"""
        assert decode_string_literal('"a\\qb"') == "aqb"

    def test_trailing_backslash_does_not_crash(self):
        assert decode_string_literal('"a\\"') == "a"
