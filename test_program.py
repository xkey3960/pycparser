#!/usr/bin/python
"""test_program.py — 多文件支持测试（S1：CProgram 骨架 + main 定位）

运行: python test_program.py
覆盖（设计文档-多文件支持.md §四）：
  T1 双文件基础：lib.c(helper+struct Pt) + main.c(main) → 57
  T2 前向引用：main.c 在前、lib.c 在后 → 链接两遍注册解决
  T5 main 定位：有 main / 无 main 报错 / 多 main 警告取第一个
"""

import contextlib
import io

import execute as exe_mod
from program import CProgram

MULTI = 'test/multi'


def _run(files, entry='main'):
    exe_mod.setup_global_scope()          # 重置 g_scope/g_functions（类型注册表全局保留）
    prog = CProgram(files, entry=entry)
    prog.load()
    prog.link()
    return prog.run()


def test_t1_two_files():
    print("  [T1] 双文件：lib.c(helper/struct Pt) + main.c(main)")
    result = _run([f'{MULTI}/lib.c', f'{MULTI}/main.c'])
    assert result == 57, f"期望 57，实际 {result}"
    print(f"    main() = {result}（跨文件函数 + 类型 + struct 传参）✓")


def test_t2_forward_ref():
    print("  [T2] 前向引用：main.c 在前、lib.c 在后")
    result = _run([f'{MULTI}/main.c', f'{MULTI}/lib.c'])
    assert result == 57, f"期望 57，实际 {result}"
    print(f"    main() = {result}（链接两遍注册解决前向引用）✓")


def test_t5_entry_detection():
    print("  [T5] main 定位")
    # 无 main → 报错
    try:
        _run([f'{MULTI}/lib.c'])
        raise AssertionError("应报未找到入口")
    except AssertionError as e:
        assert '未找到入口函数' in str(e)
        print(f"    无 main 报错: {e} ✓")
    # 多 main → 警告 + 取第一个（main.c 在前，其他文件提供 helper）
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = _run([f'{MULTI}/main.c', f'{MULTI}/other_main.c', f'{MULTI}/lib.c'])
    assert result == 57, f"应取第一个 main（57），实际 {result}"
    assert '多个文件定义入口' in buf.getvalue()
    print(f"    多 main 警告 + 取第一个: main() = {result} ✓")


def main():
    print("=" * 60)
    print("  program.py — 多文件支持测试（S1）")
    print("=" * 60)
    print("\n--- 1. 双文件基础 ---")
    test_t1_two_files()
    print("\n--- 2. 前向引用 ---")
    test_t2_forward_ref()
    print("\n--- 3. main 定位 ---")
    test_t5_entry_detection()
    print("\n" + "=" * 60)
    print("  S1 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
