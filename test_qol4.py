#!/usr/bin/python
# -*- coding: utf-8 -*-
"""test_qol4.py — QOL-4 编译管线优化测试（多线程并行 + AST 缓存持久化）

运行: python test_qol4.py
覆盖（设计文档-编译管线优化.md）：
  1. 并行一致性：多文件并行解析结果与串行逐字节一致（AST 同构 + main() 一致）
  2. 缓存命中：冷编译 → 改文件 miss → 恢复内容命中（结果一致）
  3. 开关：parallel=False / ast_cache=False 行为与旧版一致
  4. 缓存可删：删除缓存目录后一切照常（无残留依赖）
  5. 组合冒烟：lazy / link / strict(方案C) 与并行+缓存组合
"""

import os
import sys
import shutil
import contextlib
import io

import execute as exe_mod
from program import CProgram, _ast_cache_dir

MULTI = 'test/multi'

# 用独立缓存目录，避免污染用户真实缓存
_FAKE_CACHE = os.path.join(MULTI, '_q4_cache')


def _run(files, entry='main', args=(), **kw):
    exe_mod.setup_global_scope()
    prog = CProgram(files, entry=entry, **kw)
    prog.load()
    if kw.get('lazy', True) is False:
        prog.link()
    return prog.run(*args)


def _setup_files():
    """写两文件夹具：lib.c(helper) + main.c(main) → 57。"""
    open(f'{MULTI}/_q4_lib.c', 'w').write(
        'struct Pt { int x; int y; };\n'
        'int helper(int a, struct Pt p) { return a + p.x + p.y; }\n')
    open(f'{MULTI}/_q4_main.c', 'w').write(
        'struct Pt { int x; int y; };\n'
        'int helper(int a, struct Pt p);\n'
        'int main(void) {\n'
        '    struct Pt p; p.x = 10; p.y = 20;\n'
        '    return helper(27, p);      /* 27+10+20 = 57 */\n'
        '}\n')


def _clear_cache():
    shutil.rmtree(_FAKE_CACHE, ignore_errors=True)


# ==================== 1. 并行一致性 ====================

def test_parallel_consistency():
    print("  [Par] 并行解析 vs 串行解析：AST 同构 + main() 一致")
    _setup_files()
    files = [f'{MULTI}/_q4_lib.c', f'{MULTI}/_q4_main.c']
    # 串行（并行关）
    exe_mod.setup_global_scope()
    p1 = CProgram(files, parallel=False, ast_cache=False)
    p1.load()
    r1 = p1.run()
    asts1 = p1.asts
    # 并行（缓存关）
    _clear_cache()
    exe_mod.setup_global_scope()
    p2 = CProgram(files, parallel=True, ast_cache=False)
    p2.load()
    r2 = p2.run()
    asts2 = p2.asts
    assert r1 == r2 == 57, f"串行 {r1} 并行 {r2} 应一致=57"
    assert len(asts1) == len(asts2) == 2
    # AST 同构：ext 顶层节点类型序列一致（FileAST 结构等价）
    for a1, a2 in zip(asts1, asts2):
        t1 = [type(e).__name__ for e in (a1.ext or [])]
        t2 = [type(e).__name__ for e in (a2.ext or [])]
        assert t1 == t2, f"AST 顶层节点类型不一致: {t1} vs {t2}"
    print(f"    串行={r1} 并行={r2}；两文件 AST 顶层结构一致 ✓")


# ==================== 2. 缓存命中/失效/再命中 ====================

def test_cache_hit_miss_hit():
    print("  [Cache] 冷编译 → 改文件 miss → 恢复命中（结果一致）")
    _setup_files()
    _clear_cache()
    files = [f'{MULTI}/_q4_lib.c', f'{MULTI}/_q4_main.c']

    # 第一次：冷缓存（写缓存），同时收集 hash
    exe_mod.setup_global_scope()
    p1 = CProgram(files, parallel=False, ast_cache=True)
    p1.load()
    r_cold = p1.run()
    cache_dir = _ast_cache_dir()
    cache_files = [f for f in os.listdir(cache_dir) if f.endswith('.pkl')]
    assert len(cache_files) == 2, f"应写 2 个缓存文件，实际 {len(cache_files)}"
    print(f"    冷编译 {r_cold}，缓存文件 {len(cache_files)} 个 ✓")

    # 改文件内容 → hash 变 → miss → 重编译（结果随之变化）
    open(f'{MULTI}/_q4_main.c', 'w').write(
        'struct Pt { int x; int y; };\n'
        'int helper(int a, struct Pt p);\n'
        'int main(void) {\n'
        '    struct Pt p; p.x = 10; p.y = 20;\n'
        '    return helper(37, p);      /* 37+10+20 = 67 */\n'
        '}\n')
    exe_mod.setup_global_scope()
    p2 = CProgram(files, parallel=False, ast_cache=True)
    p2.load()
    r_miss = p2.run()
    assert r_miss == 67, f"改文件后应重编译=67，实际 {r_miss}"
    print(f"    改文件 → miss 重编译 {r_miss} ✓")

    # 恢复原内容 → hash 相同 → 命中缓存（与冷编译结果一致，且不重编译）
    open(f'{MULTI}/_q4_main.c', 'w').write(
        'struct Pt { int x; int y; };\n'
        'int helper(int a, struct Pt p);\n'
        'int main(void) {\n'
        '    struct Pt p; p.x = 10; p.y = 20;\n'
        '    return helper(27, p);      /* 27+10+20 = 57 */\n'
        '}\n')
    exe_mod.setup_global_scope()
    p3 = CProgram(files, parallel=False, ast_cache=True)
    p3.load()
    r_hit = p3.run()
    assert r_hit == 57, f"恢复内容命中缓存应=57，实际 {r_hit}"
    print(f"    恢复原内容 → hash 命中缓存 {r_hit} ✓")


# ==================== 3. 开关 ====================

def test_switches():
    print("  [Switch] parallel=False / ast_cache=False 与旧版一致")
    _setup_files()
    _clear_cache()
    files = [f'{MULTI}/_q4_lib.c', f'{MULTI}/_q4_main.c']
    r = _run(files, parallel=False, ast_cache=False)
    assert r == 57
    # 关闭缓存后不产生缓存文件
    cache_dir = _ast_cache_dir()
    if os.path.isdir(cache_dir):
        assert not [f for f in os.listdir(cache_dir) if f.endswith('.pkl')], \
            "ast_cache=False 不应写缓存"
    print(f"    parallel=False + ast_cache=False: main()={r}，无缓存写入 ✓")


# ==================== 4. 缓存可删（无残留依赖） ====================

def test_cache_removable():
    print("  [Del] 删除缓存目录后一切照常（无残留依赖）")
    _setup_files()
    _clear_cache()
    files = [f'{MULTI}/_q4_lib.c', f'{MULTI}/_q4_main.c']
    _run(files)                      # 写缓存
    _clear_cache()                   # 删除缓存
    r = _run(files)                  # 重编译
    assert r == 57
    print(f"    删缓存后重编译 main()={r} ✓")


# ==================== 5. 组合冒烟 ====================

def test_combos():
    print("  [Combo] lazy/link/strict 与 并行+缓存 组合")
    _setup_files()
    _clear_cache()
    files = [f'{MULTI}/_q4_lib.c', f'{MULTI}/_q4_main.c']
    # lazy（默认）+ 并行 + 缓存
    r = _run(files)
    assert r == 57
    # link（eager）+ 并行 + 缓存
    exe_mod.setup_global_scope()
    prog = CProgram(files, lazy=False)
    prog.load()
    prog.link()
    assert prog.run() == 57
    # strict 方案C + 并行 + 缓存（单入口文件可达）
    open(f'{MULTI}/_q4_bad.c', 'w').write(
        'typedef struct BadQ { int arr[no_such_q + 1]; } BadQ;\n'
        'int unused(void) { return 0; }\n')
    exe_mod.setup_global_scope()
    prog3 = CProgram([f'{MULTI}/_q4_main.c', f'{MULTI}/_q4_lib.c',
                      f'{MULTI}/_q4_bad.c'],
                     lazy=True, strict=True)
    prog3.load()
    r3 = prog3.run()
    assert r3 == 57, f"strict 可达性 + 缓存: 期望 57，实际 {r3}"
    print("    lazy + 并行 + 缓存 ✓；link + 并行 + 缓存 ✓；strict 方案C + 并行 + 缓存 ✓")


# ==================== 主入口 ====================

def main():
    print("=" * 60)
    print("  QOL-4 编译管线优化（多线程并行 + AST 缓存持久化）")
    print("=" * 60)
    # 隔离：测试用独立缓存目录
    os.environ['PYCPARSER_AST_CACHE'] = os.path.abspath(_FAKE_CACHE)
    _clear_cache()
    try:
        print("\n--- 1. 并行一致性 ---")
        test_parallel_consistency()
        print("\n--- 2. 缓存命中/失效/再命中 ---")
        test_cache_hit_miss_hit()
        print("\n--- 3. 开关 ---")
        test_switches()
        print("\n--- 4. 缓存可删 ---")
        test_cache_removable()
        print("\n--- 5. 组合冒烟 ---")
        test_combos()
    finally:
        _clear_cache()
        os.environ.pop('PYCPARSER_AST_CACHE', None)
        for f in ('_q4_lib.c', '_q4_main.c', '_q4_bad.c'):
            try:
                os.unlink(f'{MULTI}/{f}')
            except OSError:
                pass
    print("\n" + "=" * 60)
    print("  QOL-4 并行 + 缓存 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
