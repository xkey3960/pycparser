#!/usr/bin/python
"""cbuiltins.py — 解释器内置函数注册表（可扩展）

设计目标：给 execute.py 解释器提供"常用内置函数"（printf/malloc/memset 等），
并让后续新增内置函数只需**一个装饰器 + 一个函数**。

机制：
    @builtin('函数名')
    def handler(args):
        # args 是已求值的实参列表（Python 值）
        return 返回值

扩展方法（三步）：
    1. 在本文件用 @builtin('name') 定义 handler(args) -> 值；
    2. 若需全局状态（如 rand 的种子），用模块级变量；
    3. execute.py 的 _call_builtin 自动经注册表分发（无需改分发逻辑）。

内存模型说明：
    malloc/free/memset/memcpy 等基于一个 1MB 的字节堆（bump 分配器）。
    地址是堆内偏移（int）。逐字节解引用（*ptr）依赖指针模型 MEM-1，
    但堆写入/字符串操作已可工作。堆回收（first-fit）留 MEM-4。

设计依据：设计文档-内置函数.md
"""

import math
import re

# ==================== 注册表 ====================

_BUILTINS = {}


def register_builtin(name, handler):
    """注册内置函数：handler(args) -> 值。args 为已求值的实参列表。"""
    _BUILTINS[name] = handler


def builtin(name):
    """装饰器：@builtin('printf') 注册一个内置函数。"""
    def deco(f):
        register_builtin(name, f)
        return f
    return deco


def call_builtin(name, args):
    """分发内置调用；未注册 → AssertionError。"""
    h = _BUILTINS.get(name)
    if h is None:
        raise AssertionError(f"Undefined function: '{name}'")
    return h(args)


def list_builtins():
    return sorted(_BUILTINS)


# ==================== 简易堆（malloc/free 基础） ====================

_HEAP = bytearray(1024 * 1024)          # 1MB 字节堆
_HEAP_NEXT = 0                          # bump 分配游标
_ALLOCS = {}                            # addr -> size（realloc/free 校验）


def _alloc(size):
    """bump 分配：返回堆内偏移（int 地址）；越界报错。"""
    global _HEAP_NEXT
    if size < 0:
        return 0
    if _HEAP_NEXT + size > len(_HEAP):
        raise AssertionError(f"malloc: 堆空间不足（需 {size}B）")
    addr = _HEAP_NEXT
    _HEAP_NEXT += size
    _ALLOCS[addr] = size
    return addr


def _read_bytes(ptr, n):
    if ptr < 0 or ptr + n > len(_HEAP):
        raise AssertionError("内存越界读")
    return bytes(_HEAP[ptr:ptr + n])


def _write_bytes(ptr, data):
    if ptr < 0 or ptr + len(data) > len(_HEAP):
        raise AssertionError("内存越界写")
    _HEAP[ptr:ptr + len(data)] = data


def _read_cstr(ptr):
    """从堆读取 NUL 结尾字符串。"""
    end = _HEAP.find(0, ptr)
    if end < 0:
        end = len(_HEAP)
    return bytes(_HEAP[ptr:end]).decode('latin1')


def _write_cstr(ptr, s):
    data = s.encode('latin1') + b'\0'
    _write_bytes(ptr, data)
    return ptr


def _cmp_bytes(a, b):
    return (a > b) - (a < b)


def _code(c):
    """字符参数归一为 int 码（char 字面量经 ExeConstant 已是 int）。"""
    return ord(c) if isinstance(c, str) and len(c) == 1 else int(c)


def _int_arg(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


# ==================== stdio.h ====================

_FMT_RE = re.compile(r'%([#0\- +]*)(\d*)(?:\.(\d+))?([lhjztL]*)([diuoxXfFeEgGcsp])')


def _pyfmt(fmt):
    """C printf 格式 → Python % 格式：去长度修饰符（%ld→%d），%p→%#x。"""
    def repl(m):
        flags, width, prec, _len, conv = m.groups()
        if conv == 'p':
            if '#' not in flags:
                flags = '#' + flags
            return f'%{flags}{width}x'
        s = '%' + flags + width
        if prec is not None:
            s += '.' + prec
        return s + conv
    return _FMT_RE.sub(repl, fmt)


@builtin('printf')
def _printf(args):
    if not args:
        return 0
    fmt = _pyfmt(str(args[0]))
    out = fmt % tuple(args[1:]) if len(args) > 1 else fmt
    print(out, end='')
    return len(out)


@builtin('puts')
def _puts(args):
    s = str(args[0]) if args else ''
    print(s)
    return len(s) + 1


@builtin('putchar')
def _putchar(args):
    c = _code(args[0]) if args else 0
    print(chr(c), end='')
    return c


@builtin('getchar')
def _getchar(args):
    return 0


@builtin('exit')
@builtin('_exit')
def _exit(args):
    raise SystemExit(_int_arg(args[0]) if args else 0)


# ==================== stdlib.h ====================

@builtin('malloc')
def _malloc(args):
    return _alloc(max(0, _int_arg(args[0])) if args else 0)


@builtin('calloc')
def _calloc(args):
    n = _int_arg(args[0]) if args else 0
    sz = _int_arg(args[1]) if len(args) > 1 else 0
    addr = _alloc(n * sz)
    return addr                      # 堆初始全零


@builtin('realloc')
def _realloc(args):
    ptr, size = _int_arg(args[0]) if args else 0, _int_arg(args[1]) if len(args) > 1 else 0
    old = _ALLOCS.get(ptr)
    if ptr == 0:
        return _alloc(size)
    if old is not None and size <= old:
        return ptr                   # 收缩：返回同地址
    data = _read_bytes(ptr, old) if old else b''
    _ALLOCS.pop(ptr, None)
    new_addr = _alloc(size)
    _write_bytes(new_addr, data[:size])
    return new_addr


@builtin('free')
def _free(args):
    ptr = _int_arg(args[0]) if args else 0
    # bump 分配器 v1 不回收空间（MEM-4 做 first-fit）；仅移除分配记录
    _ALLOCS.pop(ptr, None)
    return None


@builtin('abs')
def _abs(args):
    return abs(_int_arg(args[0])) if args else 0


@builtin('atoi')
@builtin('atol')
def _atoi(args):
    s = str(args[0]) if args else ''
    try:
        return int(s.strip())
    except ValueError:
        return 0


# ==================== string.h ====================

@builtin('memset')
def _memset(args):
    ptr = _int_arg(args[0]) if args else 0
    val = _code(args[1]) if len(args) > 1 else 0
    n = _int_arg(args[2]) if len(args) > 2 else 0
    _write_bytes(ptr, bytes([val & 0xFF]) * max(0, n))
    return ptr


@builtin('memcpy')
@builtin('memmove')
def _memcpy(args):
    dst = _int_arg(args[0]) if args else 0
    src = args[1] if len(args) > 1 else 0
    n = _int_arg(args[2]) if len(args) > 2 else 0
    data = _read_bytes(_int_arg(src), n) if isinstance(src, int) else str(src).encode('latin1')[:n]
    _write_bytes(dst, data)
    return dst


@builtin('memcmp')
def _memcmp(args):
    a = _int_arg(args[0]) if args else 0
    b = _int_arg(args[1]) if len(args) > 1 else 0
    n = _int_arg(args[2]) if len(args) > 2 else 0
    return _cmp_bytes(_read_bytes(a, n), _read_bytes(b, n))


@builtin('strlen')
def _strlen(args):
    if not args:
        return 0
    v = args[0]
    return len(v) if isinstance(v, str) else len(_read_cstr(_int_arg(v)))


@builtin('strcmp')
def _strcmp(args):
    a = args[0] if args else ''
    b = args[1] if len(args) > 1 else ''
    sa = a if isinstance(a, str) else _read_cstr(_int_arg(a))
    sb = b if isinstance(b, str) else _read_cstr(_int_arg(b))
    return (sa > sb) - (sa < sb)


@builtin('strncmp')
def _strncmp(args):
    a = args[0] if args else ''
    b = args[1] if len(args) > 1 else ''
    n = _int_arg(args[2]) if len(args) > 2 else 0
    sa = (a if isinstance(a, str) else _read_cstr(_int_arg(a)))[:n]
    sb = (b if isinstance(b, str) else _read_cstr(_int_arg(b)))[:n]
    return (sa > sb) - (sa < sb)


@builtin('strcpy')
def _strcpy(args):
    dst = _int_arg(args[0]) if args else 0
    src = args[1] if len(args) > 1 else ''
    s = src if isinstance(src, str) else _read_cstr(_int_arg(src))
    return _write_cstr(dst, s)


@builtin('strncpy')
def _strncpy(args):
    dst = _int_arg(args[0]) if args else 0
    src = args[1] if len(args) > 1 else ''
    n = _int_arg(args[2]) if len(args) > 2 else 0
    s = (src if isinstance(src, str) else _read_cstr(_int_arg(src)))[:n]
    return _write_bytes(dst, s.encode('latin1') + b'\0' * max(0, n - len(s))) or dst


@builtin('strcat')
def _strcat(args):
    dst = _int_arg(args[0]) if args else 0
    src = args[1] if len(args) > 1 else ''
    base = _read_cstr(dst)
    tail = src if isinstance(src, str) else _read_cstr(_int_arg(src))
    return _write_cstr(dst, base + tail)


# ==================== ctype.h ====================

@builtin('isdigit')
def _isdigit(args):
    c = _code(args[0]) if args else 0
    return 1 if 48 <= c <= 57 else 0


@builtin('isalpha')
def _isalpha(args):
    c = _code(args[0]) if args else 0
    return 1 if 65 <= c <= 90 or 97 <= c <= 122 else 0


@builtin('isalnum')
def _isalnum(args):
    return 1 if _isdigit(args) or _isalpha(args) else 0


@builtin('isspace')
def _isspace(args):
    c = _code(args[0]) if args else 0
    return 1 if c in (32, 9, 10, 13, 11, 12) else 0


@builtin('isupper')
def _isupper(args):
    c = _code(args[0]) if args else 0
    return 1 if 65 <= c <= 90 else 0


@builtin('islower')
def _islower(args):
    c = _code(args[0]) if args else 0
    return 1 if 97 <= c <= 122 else 0


@builtin('toupper')
def _toupper(args):
    c = _code(args[0]) if args else 0
    return c - 32 if 97 <= c <= 122 else c


@builtin('tolower')
def _tolower(args):
    c = _code(args[0]) if args else 0
    return c + 32 if 65 <= c <= 90 else c


# ==================== math.h ====================

def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


@builtin('sqrt')
def _sqrt(args):
    return math.sqrt(_num(args[0])) if args else 0.0


@builtin('pow')
def _pow(args):
    return math.pow(_num(args[0]) if args else 0, _num(args[1]) if len(args) > 1 else 0)


@builtin('fabs')
def _fabs(args):
    return abs(_num(args[0])) if args else 0.0


@builtin('floor')
def _floor(args):
    return math.floor(_num(args[0])) if args else 0


@builtin('ceil')
def _ceil(args):
    return math.ceil(_num(args[0])) if args else 0


@builtin('fmod')
def _fmod(args):
    return math.fmod(_num(args[0]) if args else 0, _num(args[1]) if len(args) > 1 else 1)


@builtin('sin')
def _sin(args):
    return math.sin(_num(args[0])) if args else 0.0


@builtin('cos')
def _cos(args):
    return math.cos(_num(args[0])) if args else 0.0


@builtin('tan')
def _tan(args):
    return math.tan(_num(args[0])) if args else 0.0


@builtin('log')
def _log(args):
    return math.log(_num(args[0])) if args else 0.0


@builtin('exp')
def _exp(args):
    return math.exp(_num(args[0])) if args else 0.0


# ==================== stdlib.h: rand ====================

_RAND_STATE = 1


@builtin('srand')
def _srand(args):
    global _RAND_STATE
    _RAND_STATE = _int_arg(args[0]) if args else 0
    return None


@builtin('rand')
def _rand(args):
    global _RAND_STATE
    _RAND_STATE = (1103515245 * _RAND_STATE + 12345) & 0x7FFFFFFF
    return (_RAND_STATE >> 16) & 0x7FFF


# ==================== GNU 内建 ====================

@builtin('__builtin_types_compatible_p')
def _builtin_types_compatible_p(args):
    # 简化：解释器内类型视为兼容
    return 1
