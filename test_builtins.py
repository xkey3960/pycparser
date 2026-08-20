#!/usr/bin/python
"""test_builtins.py — 内置函数注册表与常用内置函数测试

运行: python test_builtins.py
覆盖：
  1. 注册表机制（register_builtin / @builtin / call_builtin / list_builtins）
  2. stdio: printf（C 格式转换）/ puts / putchar
  3. stdlib: malloc / memset / memcpy / strlen / strcmp / atoi / abs
  4. ctype / math / rand
  5. 端到端：C 文件调用 printf/malloc/memset/strlen/atoi
"""

import contextlib
import io

import cbuiltins
from cbuiltins import register_builtin, builtin, call_builtin, list_builtins

import execute as exe_mod
from program import CProgram


def _run(files, entry='main', args=()):
    exe_mod.setup_global_scope()
    prog = CProgram(files, entry=entry)
    prog.load()
    prog.link()
    return prog.run(*args)


# ==================== 1. 注册表机制 ====================

def test_registry_mechanism():
    print("  [Registry] 注册表机制:")
    assert 'printf' in list_builtins() and 'malloc' in list_builtins()
    assert call_builtin('abs', [-5]) == 5

    # 动态注册（register_builtin）
    register_builtin('test_double', lambda args: args[0] * 2)
    assert call_builtin('test_double', [21]) == 42
    # 装饰器注册
    @builtin('test_triple')
    def _triple(args):
        return args[0] * 3
    assert call_builtin('test_triple', [14]) == 42
    # 未注册 → 报错
    try:
        call_builtin('no_such_fn', [])
        raise AssertionError("应报 Undefined function")
    except AssertionError as e:
        assert 'Undefined function' in str(e)
    print(f"    动态注册/装饰器注册/未注册报错；共 {len(list_builtins())} 个内置 ✓")


# ==================== 2. stdio ====================

def test_stdio():
    print("  [stdio] printf（C 格式转换）/ puts / putchar:")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        n = call_builtin('printf', ['x=%d, s=%s, c=%c, hex=%x, p=%p\n', 5, 'hi', 65, 255, 42])
        call_builtin('puts', ['line'])
        call_builtin('putchar', [66])
    assert buf.getvalue() == 'x=5, s=hi, c=A, hex=ff, p=0x2a\nline\nB'
    assert n == len('x=5, s=hi, c=A, hex=ff, p=0x2a\n')
    # 长度修饰符（%ld / %zu）被剥离
    buf2 = io.StringIO()
    with contextlib.redirect_stdout(buf2):
        call_builtin('printf', ['%ld %zu\n', 7, 8])
    assert buf2.getvalue() == '7 8\n'
    # 引用对象（StructValue）作 %x/%p 实参 → 用对象 id 作地址值
    from typesys import StructType, StructValue
    sv = StructValue(StructType('S', members=[], size=1, align=1))
    buf3 = io.StringIO()
    with contextlib.redirect_stdout(buf3):
        call_builtin('printf', ['%x %p\n', sv, sv])
    out3 = buf3.getvalue().strip().split()
    assert len(out3) == 2 and out3[0] == out3[1].lstrip('0x')  # %x 与 %p 同一地址（%p 带 0x）
    assert all(c in '0123456789abcdef' for c in out3[0]) and out3[0]
    print(f"    printf 格式转换 ✓（含 %p/%ld/%zu；引用对象地址 %x/%p）")


# ==================== 3. stdlib/string ====================

def test_heap_string():
    print("  [stdlib] malloc/memset/memcpy/strlen/strcmp/atoi:")
    p = call_builtin('malloc', [10])
    assert p >= 8 and isinstance(p, int)   # MEM-4：首块从 8 起，0 保留作 NULL
    call_builtin('memset', [p, 65, 3])                       # AAA...
    assert bytes(cbuiltins._HEAP[p:p + 3]) == b'AAA'
    call_builtin('memcpy', [p + 3, 'BC', 2])                 # AAABC
    assert bytes(cbuiltins._HEAP[p:p + 5]) == b'AAABC'
    assert call_builtin('strlen', ['hello']) == 5
    assert call_builtin('strcmp', ['abc', 'abd']) == -1
    assert call_builtin('strcmp', ['abc', 'abc']) == 0
    assert call_builtin('strncmp', ['abc', 'abd', 2]) == 0
    assert call_builtin('atoi', ['-42']) == -42
    assert call_builtin('abs', [-7]) == 7
    call_builtin('free', [p])
    print("    堆写入/memset/memcpy/str 族/atoi/abs ✓")


def test_mem4_first_fit():
    """MEM-4 堆管理：first-fit 复用 / 相邻合并 / 非法 free 报错 / realloc 保数据。"""
    print("  [MEM4] first-fit 堆（循环复用 / 合并 / double-free / realloc）")
    # 保存并重置堆（测试间隔离）
    import cbuiltins as _cb
    saved = (_cb._HEAP, _cb._HEAP_NEXT, _cb._ALLOCS, _cb._FREE)
    _cb._HEAP = bytearray(1024 * 1024)
    _cb._HEAP_NEXT = 0
    _cb._ALLOCS = {}
    _cb._FREE = []
    try:
        # 循环 200 次 malloc(100)/free → 游标几乎不动（bump 会耗尽）
        for i in range(200):
            q = call_builtin('malloc', [100])
            assert q != 0
            call_builtin('free', [q])
        assert _cb._HEAP_NEXT < 3000, f"游标应复用，实际 {_cb._HEAP_NEXT}"
        # 碎片复用：free 中间块 → 再分配复用其地址
        a = call_builtin('malloc', [200])
        b = call_builtin('malloc', [100])
        c = call_builtin('malloc', [50])
        call_builtin('free', [b])
        d = call_builtin('malloc', [80])
        assert d == b, f"应复用 b@{b}，实际 {d}"
        call_builtin('free', [a]); call_builtin('free', [c])
        # 相邻合并：free 相邻两块 → 分配更大的块复用合并区
        x = call_builtin('malloc', [100])
        y = call_builtin('malloc', [100])
        call_builtin('free', [x]); call_builtin('free', [y])
        z = call_builtin('malloc', [150])
        assert z == x, f"应复用合并块 {x}，实际 {z}"
        call_builtin('free', [z])
        # double-free 报错
        p2 = call_builtin('malloc', [10])
        call_builtin('free', [p2])
        try:
            call_builtin('free', [p2])
            raise AssertionError("double-free 应报错")
        except AssertionError as e:
            assert '非法地址' in str(e)
        # realloc 保留数据
        p3 = call_builtin('malloc', [10])
        call_builtin('memset', [p3, 65, 5])
        p4 = call_builtin('realloc', [p3, 50])
        assert bytes(_cb._HEAP[p4:p4 + 5]) == b'AAAAA'
        print("    循环复用 ✓ 碎片复用 ✓ 相邻合并 ✓ double-free 报错 ✓ realloc 保数据 ✓")
    finally:
        _cb._HEAP, _cb._HEAP_NEXT, _cb._ALLOCS, _cb._FREE = saved


def test_ctype_math_rand():
    print("  [ctype/math/rand] 分类/数学/随机:")
    assert call_builtin('isdigit', [ord('5')]) == 1
    assert call_builtin('isalpha', [ord('a')]) == 1
    assert call_builtin('toupper', [ord('a')]) == ord('A')
    assert call_builtin('tolower', [ord('Z')]) == ord('z')
    assert call_builtin('sqrt', [16]) == 4.0
    assert call_builtin('pow', [2, 10]) == 1024.0
    assert call_builtin('floor', [3.7]) == 3
    call_builtin('srand', [42])
    r1 = call_builtin('rand', [])
    call_builtin('srand', [42])
    r2 = call_builtin('rand', [])
    assert r1 == r2 and 0 <= r1 <= 32767
    print(f"    ctype/math/rand（srand(42) 可复现）✓")


# ==================== 4. 端到端 ====================

def test_end_to_end():
    print("  [E2E] C 文件调用 printf/malloc/memset/strlen/atoi:")
    src = '''
char *p;

int main()
{
    p = (char*)malloc(8);
    memset(p, 'A', 3);
    printf("len=%d\\n", strlen("hello"));
    return strlen("hello") + atoi("12");
}
'''
    with open('test/multi/builtins_main.c', 'w') as f:
        f.write(src)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = _run(['test/multi/builtins_main.c'])
    assert result == 17, f"期望 17，实际 {result}"
    assert buf.getvalue() == 'len=5\n', f"printf 输出: {buf.getvalue()!r}"
    print(f"    main() = {result}，printf 输出 {buf.getvalue()!r} ✓")


def test_prototype_not_shadow_builtin():
    """头文件里的函数原型（如 memset）不应遮蔽内置函数实现。"""
    print("  [E2E] 头文件原型不遮蔽内置函数（memset 声明 + 调用）")
    # 自定义头文件声明 memset/memcpy/strlen（真实 libc 头形态），无定义
    open('test/multi/proto_builtin.h', 'w').write(
        'void *memset(void *s, int c, unsigned int n);\n'
        'void *memcpy(void *dst, const void *src, unsigned int n);\n'
        'unsigned int strlen(const char *s);\n')
    open('test/multi/proto_builtin.c', 'w').write(
        '#include "proto_builtin.h"\n'
        'char *p;\n'
        'int main(void)\n'
        '{\n'
        '    p = (char*)malloc(8);\n'
        '    memset(p, 65, 3);          /* 原型遮蔽内置？ */\n'
        '    return (int)*(p + 1);       /* 65（堆字节读取） */\n'
        '}\n')
    result = _run(['test/multi/proto_builtin.c'])
    assert result == 65, f"期望 65，实际 {result}"
    print(f"    main() = {result}（memset 原型存在时仍走内置实现，堆字节 65）✓")


def test_va_list():
    """__builtin_va_list 可变参数：va_start/va_arg/va_end + 嵌套调用隔离。"""
    print("  [va_list] 可变参数（__builtin_va_list / va_start / va_arg / va_end）")
    src = '''
#include <stdarg.h>

int sum(int n, ...)
{
    va_list ap;
    va_start(ap, n);
    int total = 0;
    for (int i = 0; i < n; i++)
        total += va_arg(ap, int);
    va_end(ap);
    return total;
}

int inner(int a, ...)
{
    va_list ap;
    va_start(ap, a);
    int v = va_arg(ap, int);
    va_end(ap);
    return v;
}

int outer(int n, ...)
{
    va_list ap;
    va_start(ap, n);
    int a = va_arg(ap, int);
    int b = inner(1, 100);        /* 嵌套调用：不应破坏外层 va */
    int c = va_arg(ap, int);
    va_end(ap);
    return a + b + c;
}

int main(void)
{
    return sum(3, 10, 20, 12) + outer(2, 11, 22) - 133;   /* 42 + 133 - 133 = 42 */
}
'''
    with open('test/multi/va_main.c', 'w') as f:
        f.write(src)
    result = _run(['test/multi/va_main.c'])
    assert result == 42, f"期望 42，实际 {result}"
    print(f"    main() = {result}（sum=42 + outer=133，嵌套隔离）✓")


def main():
    print("=" * 60)
    print("  cbuiltins.py — 内置函数测试")
    print("=" * 60)
    print("\n--- 1. 注册表机制 ---")
    test_registry_mechanism()
    print("\n--- 2. stdio ---")
    test_stdio()
    print("\n--- 3. stdlib/string ---")
    test_heap_string()
    print("\n--- 4. ctype/math/rand ---")
    test_ctype_math_rand()
    print("\n--- 5. 端到端 ---")
    test_end_to_end()
    print("\n--- 6. va_list 可变参数 ---")
    test_va_list()
    print("\n--- 7. 原型不遮蔽内置 ---")
    test_prototype_not_shadow_builtin()
    print("\n--- 8. MEM-4 first-fit 堆 ---")
    test_mem4_first_fit()
    print("\n" + "=" * 60)
    print("  内置函数全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
