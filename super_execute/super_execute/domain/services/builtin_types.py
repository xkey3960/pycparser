"""C 的内建基础类型表 + 类型说明符的规范化。

尺寸取自本项目声明的目标（LLP64 标量 + **4 字节指针**）：

    char 1/1   short 2/2   int 4/4   long 4/4(LLP64)   long long 8/8
    float 4/4  double 8/8  _Bool 1/1  void 不完整       指针 4/4

除指针外，这些数字与宿主 gcc（x86_64-w64-mingw32）一致，因此结构体布局的
黄金值可以直接用 gcc 生成来对照（指针宽度是刻意的偏离，见 c_types 的模块
docstring）。
"""

from __future__ import annotations

from typing import Sequence

from super_execute.domain.entities.c_types import BasicType
from super_execute.domain.exceptions import UndefinedTypeError

VOID = BasicType("void", None, None)
CHAR = BasicType("char", 1, 1)
SIGNED_CHAR = BasicType("signed char", 1, 1)
UNSIGNED_CHAR = BasicType("unsigned char", 1, 1, signed=False)
SHORT = BasicType("short int", 2, 2)
UNSIGNED_SHORT = BasicType("unsigned short int", 2, 2, signed=False)
INT = BasicType("int", 4, 4)
UNSIGNED_INT = BasicType("unsigned int", 4, 4, signed=False)
LONG = BasicType("long int", 4, 4)
UNSIGNED_LONG = BasicType("unsigned long int", 4, 4, signed=False)
LONG_LONG = BasicType("long long int", 8, 8)
UNSIGNED_LONG_LONG = BasicType("unsigned long long int", 8, 8, signed=False)
FLOAT = BasicType("float", 4, 4, is_float=True)
DOUBLE = BasicType("double", 8, 8, is_float=True)
BOOL = BasicType("_Bool", 1, 1, signed=False)

#: 规范化名 → 单例。
BASIC_TYPES: dict[str, BasicType] = {
    t.name: t
    for t in (
        VOID,
        CHAR,
        SIGNED_CHAR,
        UNSIGNED_CHAR,
        SHORT,
        UNSIGNED_SHORT,
        INT,
        UNSIGNED_INT,
        LONG,
        UNSIGNED_LONG,
        LONG_LONG,
        UNSIGNED_LONG_LONG,
        FLOAT,
        DOUBLE,
        BOOL,
    )
}

#: 参与类型说明符组合的关键字（long double 等组合不在本轮范围内）。
#: 注意 ``bool`` 不在这里：C 里它来自 <stdbool.h> 的宏，不是关键字。真正走预处理器
#: 之后 ``bool`` 已经被展开成 ``_Bool``，剩下的只可能是用户自己 typedef 的名字。
SPECIFIER_KEYWORDS = frozenset(
    {
        "void",
        "char",
        "short",
        "int",
        "long",
        "float",
        "double",
        "signed",
        "unsigned",
        "_bool",
    }
)

_BASES = ("void", "char", "float", "double", "_bool", "int")


def basic(name: str) -> BasicType | None:
    """按规范化名取内建类型；不是内建返回 None。"""
    return BASIC_TYPES.get(name)


def require_basic(name: str) -> BasicType:
    ctype = BASIC_TYPES.get(name)
    if ctype is None:
        raise UndefinedTypeError(f"不是内建类型: '{name}'")
    return ctype


def canonical_type_name(names: Sequence[str]) -> str | None:
    """把类型说明符序列归一化成一个规范名（C99 6.7.2 的简化版）。

    C 允许说明符任意顺序、``int`` 可省略，于是下面这些都是 ``unsigned int``：

        unsigned ∙ int unsigned ∙ unsigned int ∙ signed unsigned int? （不合法）

    返回 None 表示"这不是一组纯粹的类型说明符"（例如混进了 typedef 名），
    由调用方改用标识符查找路径。非法组合同样返回 None。
    """
    words = [str(word).lower() for word in names]
    if not words:
        return None
    # 混入了非说明符关键字（很可能是 typedef 名）→ 不走内建路径
    if any(word not in SPECIFIER_KEYWORDS for word in words):
        return None

    unsigned = "unsigned" in words
    signed_kw = "signed" in words
    short = "short" in words
    long_count = words.count("long")
    if unsigned and signed_kw:
        return None  # "signed unsigned int" 非法
    if (
        words.count("unsigned") > 1
        or words.count("signed") > 1
        or words.count("short") > 1
    ):
        return None  # 说明符重复，如 "unsigned unsigned"
    bases_present = {word for word in words if word in _BASES}
    if len(bases_present) > 1:
        return None  # 例如 "char int" 这种非法组合
    if any(words.count(word) > 1 for word in bases_present):
        return None  # 例如 "int int"
    base = next(iter(bases_present), None)

    if base is None:
        # 只有 signed/unsigned/short/long，基准类型隐含为 int
        base = "int"

    if base == "void":
        return None if (unsigned or short or long_count) else "void"

    if base == "float":
        return None if (unsigned or short or long_count) else "float"

    if base == "_bool":
        return None if (unsigned or short or long_count) else "_Bool"

    if base == "double":
        # long double 未支持：显式返回 None，让上层报"未定义类型"
        return None if (unsigned or short or long_count) else "double"

    if base == "char":
        if short or long_count:
            return None
        if unsigned:
            return "unsigned char"
        if "signed" in words:
            return "signed char"
        return "char"

    # 整数族：int / short / long / long long
    if short and long_count:
        return None
    if long_count > 2:
        return None
    if short:
        core = "short int"
    elif long_count == 2:
        core = "long long int"
    elif long_count == 1:
        core = "long int"
    else:
        core = "int"
    return f"unsigned {core}" if unsigned else core
