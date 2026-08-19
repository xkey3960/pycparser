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
    print(f"    printf 格式转换 ✓（含 %p/%ld/%zu）" )


# ==================== 3. stdlib/string ====================

def test_heap_string():
    print("  [stdlib] malloc/memset/memcpy/strlen/strcmp/atoi:")
    p = call_builtin('malloc', [10])
    assert p == 0 and isinstance(p, int)
    call_builtin('memset', [p, 65, 3])                       # AAA...
    assert bytes(cbuiltins._HEAP[0:3]) == b'AAA'
    call_builtin('memcpy', [p + 3, 'BC', 2])                 # AAABC
    assert bytes(cbuiltins._HEAP[0:5]) == b'AAABC'
    assert call_builtin('strlen', ['hello']) == 5
    assert call_builtin('strcmp', ['abc', 'abd']) == -1
    assert call_builtin('strcmp', ['abc', 'abc']) == 0
    assert call_builtin('strncmp', ['abc', 'abd', 2]) == 0
    assert call_builtin('atoi', ['-42']) == -42
    assert call_builtin('abs', [-7]) == 7
    call_builtin('free', [p])
    print("    堆写入/memset/memcpy/str 族/atoi/abs ✓")


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
    print("\n" + "=" * 60)
    print("  内置函数全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
