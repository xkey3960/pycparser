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


def is_builtin(name):
    """名字是否已注册的内置函数（原型占位判断用：内建实现优先）。"""
    return name in _BUILTINS


def list_builtins():
    return sorted(_BUILTINS)


# ==================== 简易堆（malloc/free 基础，MEM-4 first-fit） ====================

_HEAP = bytearray(1024 * 1024)          # 1MB 字节堆
_HEAP_NEXT = 0                          # bump 分配游标（无空闲块时增长）
_ALLOCS = {}                            # addr -> size（已分配块；free/realloc 校验）
_FREE = []                              # [(addr, size), ...] 空闲块（按 addr 升序，free 时合并）

_MIN_BLOCK = 8                          # 最小空闲块（切割剩余不足则整块使用）
_HEAP_BASE = 8                          # 首块地址（0 保留作 NULL，malloc 永不返回 0）


def _alloc(size):
    """first-fit 分配：优先复用空闲块（首个 size 足够者），无则 bump 扩展。

    返回地址永远 >= _HEAP_BASE（0 保留作 NULL）；malloc(0)/负数 → 0。
    """
    global _HEAP_NEXT
    if size < 0:
        return 0
    if size == 0:
        return 0                        # malloc(0) → NULL 语义
    if _HEAP_NEXT == 0:
        _HEAP_NEXT = _HEAP_BASE         # 首块从 base 起（0 是 NULL）
    # first-fit：找首个足够大的空闲块
    for i, (addr, free_sz) in enumerate(_FREE):
        if free_sz >= size:
            del _FREE[i]
            remain = free_sz - size
            if remain >= _MIN_BLOCK:
                _FREE.insert(i, (addr + size, remain))   # 剩余部分留作空闲
            _ALLOCS[addr] = size
            return addr
    # 无空闲块：bump 扩展
    if _HEAP_NEXT + size > len(_HEAP):
        raise AssertionError(f"malloc: 堆空间不足（需 {size}B）")
    addr = _HEAP_NEXT
    _HEAP_NEXT += size
    _ALLOCS[addr] = size
    return addr


def _free_block(addr):
    """free：移除分配记录，块入空闲表并合并相邻空闲块（减少碎片）。"""
    size = _ALLOCS.pop(addr, None)
    if size is None:
        raise AssertionError(f"free: 非法地址（未分配或已释放）: {addr}")
    # 插入空闲表（保持按 addr 升序）
    lo, hi = 0, len(_FREE)
    while lo < hi:
        mid = (lo + hi) // 2
        if _FREE[mid][0] < addr:
            lo = mid + 1
        else:
            hi = mid
    _FREE.insert(lo, (addr, size))
    # 合并相邻空闲块（左邻 / 右邻）
    if lo > 0 and _FREE[lo - 1][0] + _FREE[lo - 1][1] == addr:
        _FREE[lo - 1] = (_FREE[lo - 1][0], _FREE[lo - 1][1] + size)
        del _FREE[lo]
        lo -= 1
    if lo + 1 < len(_FREE) and addr + size == _FREE[lo + 1][0]:
        _FREE[lo] = (_FREE[lo][0], _FREE[lo][1] + _FREE[lo + 1][1])
        del _FREE[lo + 1]


def _heap_stats():
    """测试用：返回 (已分配块数, 空闲块数, 游标位置)。"""
    return len(_ALLOCS), len(_FREE), _HEAP_NEXT


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
    rest = [_printf_arg(a) for a in args[1:]]
    out = fmt % tuple(rest) if rest else fmt
    print(out, end='')
    return len(out)


def _printf_arg(v):
    """printf 实参预处理：%x/%p 遇引用对象（StructValue/UnionValue/list/Address）
    时，以对象身份 id 作地址值（MEM-1：Address 打印其地址表示）。"""
    from typesys import StructValue, UnionValue   # 延迟导入避循环
    if isinstance(v, (StructValue, UnionValue, list, dict)):
        return id(v) & 0xFFFFFFFFFFFFFFFF
    if v.__class__.__name__ == 'Address':          # execute.Address（延迟识别）
        return id(v) & 0xFFFFFFFFFFFFFFFF
    return v


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
    _free_block(ptr)
    new_addr = _alloc(size)
    if new_addr:
        _write_bytes(new_addr, data[:size])
    return new_addr


@builtin('free')
def _free(args):
    ptr = _int_arg(args[0]) if args else 0
    if ptr == 0:
        return None                  # free(NULL) 是 no-op（C 语义）
    _free_block(ptr)                 # MEM-4：回收空间 + 相邻合并
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


# ---- 可变参数（__builtin_va_list / va_start / va_arg / va_end / va_copy）----
# 按**调用帧栈**管理：每次 FuncDef 调用压入一帧（帧内 name -> 剩余实参快照），
# 返回弹帧 —— 内外层同名 ap 互不干扰。宏展开后实参是值无法写回变量，
# 故 execute.py 拦截内建调用、从 AST 取首实参 ID 名，按名操作当前帧。
# va_list 类型本身由 typesys 内建注册（__builtin_va_list，8B 句柄）。

_VA_FRAMES = []          # 调用帧栈：[{name: slot}, ...]；栈顶 = 当前活动帧


def push_va_frame(variadic_args):
    """FuncDef 调用处压帧：记录本帧可变参数源。"""
    _VA_FRAMES.append({
        '__source__': list(variadic_args) if variadic_args else [],
    })


def pop_va_frame():
    """FuncDef 返回处弹帧。"""
    if _VA_FRAMES:
        _VA_FRAMES.pop()


def _cur_frame():
    return _VA_FRAMES[-1] if _VA_FRAMES else None


def va_start_slot(ap_name):
    """按 ap 变量名初始化槽（快照本帧可变参数源）。"""
    f = _cur_frame()
    if f is None:
        f = {'__source__': []}
        _VA_FRAMES.append(f)
    f[ap_name] = list(f.get('__source__', []))


def va_arg_pop(ap_name):
    """按 ap 变量名弹出下一个可变参数。"""
    f = _cur_frame()
    slot = f.get(ap_name) if f else None
    if slot is None:
        raise AssertionError("__builtin_va_arg: va_list 未初始化或已消耗")
    if not slot:
        raise AssertionError("__builtin_va_arg: 可变参数耗尽")
    return slot.pop(0)


def va_end_slot(ap_name):
    """按 ap 变量名清理槽（当前帧）。"""
    f = _cur_frame()
    if f:
        f.pop(ap_name, None)


def va_copy_slot(dst_name, src_name):
    """复制 src 槽到 dst 槽（快照，当前帧）。"""
    f = _cur_frame()
    if f is None:
        return
    src = f.get(src_name)
    f[dst_name] = list(src) if src is not None else []
