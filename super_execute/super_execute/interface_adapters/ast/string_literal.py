"""字符串字面量的解码。

pycparser 把字面量原样放在 ``Constant.value`` 里，**带引号也带转义**：

    '"abc"'      → abc
    '"a\\n"'     → a<换行>
    '"\\x41"'    → A

两处要用它：推断类型（要知道 ``char[N]`` 里的 N）和求值（要把内容写进堆）。
"""

from __future__ import annotations

_SIMPLE_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    "\\": "\\",
    "'": "'",
    '"': '"',
    "?": "?",
}

_HEX = "0123456789abcdefABCDEF"
_OCT = "01234567"


def decode_string_literal(raw: str) -> str:
    """把 ``'"a\\n"'`` 这样的原始字面量解成真正的字符内容。"""
    text = raw[1:-1] if len(raw) >= 2 and raw[0] == '"' and raw[-1] == '"' else raw

    out: list[str] = []
    index = 0
    while index < len(text):
        char = text[index]
        if char != "\\":
            out.append(char)
            index += 1
            continue

        index += 1
        if index >= len(text):  # 结尾孤零零的反斜杠
            break
        escape = text[index]

        if escape in _SIMPLE_ESCAPES:
            out.append(_SIMPLE_ESCAPES[escape])
            index += 1
        elif escape == "x":
            end = index + 1
            while end < len(text) and text[end] in _HEX:
                end += 1
            out.append(chr(int(text[index + 1 : end], 16) or 0))
            index = end
        elif escape in _OCT:
            end = index
            while end < len(text) and end < index + 3 and text[end] in _OCT:
                end += 1
            out.append(chr(int(text[index:end], 8)))
            index = end
        else:  # 不认识的转义：原样保留那个字符
            out.append(escape)
            index += 1

    return "".join(out)
