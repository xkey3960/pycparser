"""内建函数表：C 标准库里最常用的那批，用 Python 实现。

为什么不链接 libc：这是一个**解释器**，C 代码里的 `printf` 没有真实的目标平台可
调用。所以这里用 Python 复刻它们的行为，语义按 C 标准来（返回值、副作用）。

分四组：

* 输出 —— ``printf`` / ``puts`` / ``putchar`` / ``exit``
* 字符串 —— ``strlen`` / ``strcmp`` / ``strncmp`` / ``strcpy`` / ``strcat`` /
  ``memcmp`` / ``memcpy`` / ``memset``
* 内存 —— ``malloc`` / ``calloc`` / ``free``（堆区，Phase A 不回收）
* 数值与字符 —— ``abs`` / ``atoi`` / 常用 ``math.h`` / 常用 ``ctype.h``

字符串在内存里是 ``char`` 数组，所以读写要经过 ``MemoryPort``——这也是内建表
需要拿一个 ``memory`` 的原因。
"""

from __future__ import annotations

import math
from typing import Any, Callable

from super_execute.application.ports.builtin_port import ProgramExit
from super_execute.application.ports.memory_port import MemoryPort
from super_execute.domain.entities.c_types import (
    CType,
    FunctionType,
    PointerType,
)
from super_execute.domain.exceptions import NullPointerError
from super_execute.domain.services.builtin_types import (
    CHAR,
    DOUBLE,
    INT,
    UNSIGNED_LONG,
    VOID,
)
from super_execute.domain.value_objects import Address

_CHAR_PTR = PointerType(CHAR)
_VOID_PTR = PointerType(VOID)


def _fn(ret: CType, params: tuple[CType, ...] = (), *, variadic: bool = False):
    return FunctionType(ret, params, variadic=variadic)


#: 每个内建函数的签名。用来做**隐式声明**（C89 风格的"没声明也能用"）与类型推断。
SIGNATURES: dict[str, FunctionType] = {
    # 输出
    "printf": _fn(INT, (_CHAR_PTR,), variadic=True),
    "puts": _fn(INT, (_CHAR_PTR,)),
    "putchar": _fn(INT, (INT,)),
    "exit": _fn(VOID, (INT,)),
    "_exit": _fn(VOID, (INT,)),
    # 字符串
    "strlen": _fn(UNSIGNED_LONG, (_CHAR_PTR,)),
    "strcmp": _fn(INT, (_CHAR_PTR, _CHAR_PTR)),
    "strncmp": _fn(INT, (_CHAR_PTR, _CHAR_PTR, UNSIGNED_LONG)),
    "strcpy": _fn(_CHAR_PTR, (_CHAR_PTR, _CHAR_PTR)),
    "strcat": _fn(_CHAR_PTR, (_CHAR_PTR, _CHAR_PTR)),
    "memcmp": _fn(INT, (_VOID_PTR, _VOID_PTR, UNSIGNED_LONG)),
    "memcpy": _fn(_VOID_PTR, (_VOID_PTR, _VOID_PTR, UNSIGNED_LONG)),
    "memset": _fn(_VOID_PTR, (_VOID_PTR, INT, UNSIGNED_LONG)),
    # 内存
    "malloc": _fn(_VOID_PTR, (UNSIGNED_LONG,)),
    "calloc": _fn(_VOID_PTR, (UNSIGNED_LONG, UNSIGNED_LONG)),
    "free": _fn(VOID, (_VOID_PTR,)),
    # 数值
    "abs": _fn(INT, (INT,)),
    "atoi": _fn(INT, (_CHAR_PTR,)),
    "sqrt": _fn(DOUBLE, (DOUBLE,)),
    "pow": _fn(DOUBLE, (DOUBLE, DOUBLE)),
    "fabs": _fn(DOUBLE, (DOUBLE,)),
    "floor": _fn(DOUBLE, (DOUBLE,)),
    "ceil": _fn(DOUBLE, (DOUBLE,)),
    "fmod": _fn(DOUBLE, (DOUBLE, DOUBLE)),
    "sin": _fn(DOUBLE, (DOUBLE,)),
    "cos": _fn(DOUBLE, (DOUBLE,)),
    "tan": _fn(DOUBLE, (DOUBLE,)),
    "exp": _fn(DOUBLE, (DOUBLE,)),
    "log": _fn(DOUBLE, (DOUBLE,)),
    # 字符分类（返回非 0 表示真）
    "isdigit": _fn(INT, (INT,)),
    "isalpha": _fn(INT, (INT,)),
    "isalnum": _fn(INT, (INT,)),
    "isspace": _fn(INT, (INT,)),
    "isupper": _fn(INT, (INT,)),
    "islower": _fn(INT, (INT,)),
    "toupper": _fn(INT, (INT,)),
    "tolower": _fn(INT, (INT,)),
}


class BuiltinTable:
    """``BuiltinPort`` 的实现。"""

    def __init__(self, memory: MemoryPort) -> None:
        self._memory = memory
        self._handlers: dict[str, Callable[[list[Any]], Any]] = {
            "printf": self._printf,
            "puts": self._puts,
            "putchar": self._putchar,
            "exit": self._exit,
            "_exit": self._exit,
            "strlen": self._strlen,
            "strcmp": self._strcmp,
            "strncmp": self._strncmp,
            "strcpy": self._strcpy,
            "strcat": self._strcat,
            "memcmp": self._memcmp,
            "memcpy": self._memcpy,
            "memset": self._memset,
            "malloc": self._malloc,
            "calloc": self._calloc,
            "free": self._free,
            "abs": lambda a: abs(int(_arg(a, 0))),
            "atoi": self._atoi,
            "sqrt": lambda a: math.sqrt(float(_arg(a, 0))),
            "pow": lambda a: math.pow(float(_arg(a, 0)), float(_arg(a, 1))),
            "fabs": lambda a: math.fabs(float(_arg(a, 0))),
            "floor": lambda a: math.floor(float(_arg(a, 0))),
            "ceil": lambda a: math.ceil(float(_arg(a, 0))),
            "fmod": lambda a: math.fmod(float(_arg(a, 0)), float(_arg(a, 1))),
            "sin": lambda a: math.sin(float(_arg(a, 0))),
            "cos": lambda a: math.cos(float(_arg(a, 0))),
            "tan": lambda a: math.tan(float(_arg(a, 0))),
            "exp": lambda a: math.exp(float(_arg(a, 0))),
            "log": lambda a: math.log(float(_arg(a, 0))),
        }
        for name in (
            "isdigit",
            "isalpha",
            "isalnum",
            "isspace",
            "isupper",
            "islower",
        ):
            self._handlers[name] = _char_predicate(name)
        self._handlers["toupper"] = lambda a: _to_case(a, upper=True)
        self._handlers["tolower"] = lambda a: _to_case(a, upper=False)

    # ---- 端口 ----

    def has(self, name: str) -> bool:
        return name in SIGNATURES

    def signature(self, name: str) -> FunctionType:
        return SIGNATURES[name]

    def names(self) -> list[str]:
        return sorted(SIGNATURES)

    def call(self, name: str, args: list[Any]) -> Any:
        return self._handlers[name](args)

    # ---- 内存里的字符串 ----

    def _read_cstr(self, address: Any) -> str:
        """读一个以 NUL 结尾的 C 字符串。"""
        if not isinstance(address, Address):
            raise NullPointerError(f"%s 需要一个字符串地址，收到 {address!r}")
        if address.is_null:
            raise NullPointerError("解引用 NULL 地址（字符串指针为空）")

        chars: list[str] = []
        cursor = address
        while True:
            code = self._memory.read(cursor, CHAR)
            if not code:
                return "".join(chars)
            chars.append(chr(int(code) & 0xFF))
            cursor = cursor.advanced(1)

    def _write_cstr(self, address: Any, text: str) -> Address:
        if not isinstance(address, Address) or address.is_null:
            raise NullPointerError("解引用 NULL 地址（写入目标为空）")
        cursor = address
        for char in text:
            self._memory.write(cursor, ord(char), CHAR)
            cursor = cursor.advanced(1)
        self._memory.write(cursor, 0, CHAR)  # 结尾 NUL
        return address

    # ---- 输出 ----

    def _printf(self, args: list[Any]) -> int:
        if not args:
            return 0
        template = _python_format(self._read_cstr(args[0]))
        values = [self._print_value(value) for value in args[1:]]
        try:
            # 即使没有实参也要走 % 运算：`printf("100%%")` 要输出 `100%`
            text = template % tuple(values)
        except (TypeError, ValueError) as error:
            raise ValueError(f"printf 格式与实参不匹配: {error!r}") from error
        print(text, end="")
        return len(text)

    def _puts(self, args: list[Any]) -> int:
        text = self._read_cstr(_arg(args, 0))
        print(text)
        return len(text) + 1  # C 只要求返回非负数

    def _putchar(self, args: list[Any]) -> int:
        code = int(_arg(args, 0))
        print(chr(code & 0xFF), end="")
        return code

    def _print_value(self, value: Any) -> Any:
        """把 C 值转成 Python ``%`` 能用的东西：字符串地址读成 str，其余原样。"""
        if isinstance(value, Address):
            try:
                return self._read_cstr(value)
            except Exception:  # 不是字符串就按地址打印
                return value.packed
        return value

    def _exit(self, args: list[Any]) -> Any:
        raise ProgramExit(int(_arg(args, 0)))

    # ---- 字符串 ----

    def _strlen(self, args: list[Any]) -> int:
        return len(self._read_cstr(_arg(args, 0)))

    def _strcmp(self, args: list[Any]) -> int:
        return _sign(self._read_cstr(_arg(args, 0)), self._read_cstr(_arg(args, 1)))

    def _strncmp(self, args: list[Any]) -> int:
        left = self._read_cstr(_arg(args, 0))[: int(_arg(args, 2))]
        right = self._read_cstr(_arg(args, 1))[: int(_arg(args, 2))]
        return _sign(left, right)

    def _strcpy(self, args: list[Any]) -> Address:
        destination = _arg(args, 0)
        return self._write_cstr(destination, self._read_cstr(_arg(args, 1)))

    def _strcat(self, args: list[Any]) -> Address:
        destination = _arg(args, 0)
        merged = self._read_cstr(destination) + self._read_cstr(_arg(args, 1))
        return self._write_cstr(destination, merged)

    def _memcmp(self, args: list[Any]) -> int:
        left = _read_bytes(self._memory, _arg(args, 0), int(_arg(args, 2)))
        right = _read_bytes(self._memory, _arg(args, 1), int(_arg(args, 2)))
        return _sign(left, right)

    def _memcpy(self, args: list[Any]) -> Address:
        destination = _arg(args, 0)
        payload = _read_bytes(self._memory, _arg(args, 1), int(_arg(args, 2)))
        _write_bytes(self._memory, destination, payload)
        return destination

    def _memset(self, args: list[Any]) -> Address:
        destination = _arg(args, 0)
        payload = bytes([int(_arg(args, 1)) & 0xFF]) * int(_arg(args, 2))
        _write_bytes(self._memory, destination, payload)
        return destination

    # ---- 内存 ----

    def _malloc(self, args: list[Any]) -> Address:
        size = max(int(_arg(args, 0)), 0)
        return self._memory.allocate_raw(size)

    def _calloc(self, args: list[Any]) -> Address:
        count = max(int(_arg(args, 0)), 0)
        size = max(int(_arg(args, 1)), 0)
        return self._memory.allocate_raw(count * size)

    def _free(self, args: list[Any]) -> None:
        # Phase A 的堆不回收（没有真正的分配器），free 是显式的空操作。
        return None

    def _atoi(self, args: list[Any]) -> int:
        text = self._read_cstr(_arg(args, 0)).strip()
        sign = -1 if text.startswith("-") else 1
        text = text.lstrip("+-")
        digits = ""
        for char in text:
            if not char.isdigit():
                break
            digits += char
        return sign * int(digits) if digits else 0


def _arg(args: list[Any], index: int) -> Any:
    """取第 index 个实参；缺参数时按 C 的可变参数惯例给 0。"""
    return args[index] if index < len(args) else 0


def _sign(left: Any, right: Any) -> int:
    return (left > right) - (left < right)


def _read_bytes(memory: MemoryPort, address: Any, count: int) -> bytes:
    if not isinstance(address, Address) or address.is_null:
        raise NullPointerError("解引用 NULL 地址（缓冲区为空）")
    values = [memory.read(address.advanced(index), CHAR) for index in range(count)]
    return bytes(int(value) & 0xFF for value in values)


def _write_bytes(memory: MemoryPort, address: Any, payload: bytes) -> None:
    if not isinstance(address, Address) or address.is_null:
        raise NullPointerError("解引用 NULL 地址（写入目标为空）")
    for index, byte in enumerate(payload):
        memory.write(address.advanced(index), byte, CHAR)


def _char_predicate(name: str) -> Callable[[list[Any]], int]:
    method = {
        "isdigit": "isdigit",
        "isalpha": "isalpha",
        "isalnum": "isalnum",
        "isspace": "isspace",
        "isupper": "isupper",
        "islower": "islower",
    }[name]

    def handler(args: list[Any]) -> int:
        char = chr(int(_arg(args, 0)) & 0xFF)
        return 1 if getattr(char, method)() else 0

    return handler


def _to_case(args: list[Any], *, upper: bool) -> int:
    char = chr(int(_arg(args, 0)) & 0xFF)
    return ord(char.upper() if upper else char.lower())


_PY_FORMATS = "%diouxXeEfFgGcsp"


def _python_format(template: str) -> str:
    """C 的 printf 格式串 → Python 的 ``%`` 格式串。

    - 去掉长度修饰符：``%ld`` → ``%d``、``%lld`` → ``%d``
    - ``%p`` 转成 ``%#x``（地址本来就是个整数）
    - ``%%`` 原样保留
    """
    out: list[str] = []
    index = 0
    length = len(template)
    while index < length:
        char = template[index]
        if char != "%":
            out.append(char)
            index += 1
            continue

        index += 1
        if index < length and template[index] == "%":
            out.append("%%")
            index += 1
            continue

        spec = ["%"]
        while index < length and template[index] in "-+ #0":
            spec.append(template[index])
            index += 1
        while index < length and template[index].isdigit():
            spec.append(template[index])
            index += 1
        if index < length and template[index] == ".":
            spec.append(".")
            index += 1
            while index < length and template[index].isdigit():
                spec.append(template[index])
                index += 1
        # 长度修饰符丢掉
        while index < length and template[index] in "hljztLq":
            index += 1
        if index >= length:
            out.append("".join(spec))
            break

        conversion = template[index]
        index += 1
        if conversion == "p":
            if "#" not in spec:
                spec.insert(1, "#")
            spec.append("x")
        elif conversion in _PY_FORMATS:
            spec.append(conversion)
        else:
            spec.append("%")
            spec.append(conversion)
        out.append("".join(spec))
    return "".join(out)
