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


def _run(files, entry='main', args=(), **kw):
    exe_mod.setup_global_scope()          # 重置 g_scope/g_functions（类型注册表全局保留）
    prog = CProgram(files, entry=entry, **kw)
    prog.load()
    prog.link()
    return prog.run(*args)


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


def test_t3_typedef_chain_cross_file():
    print("  [T3] 跨文件 typedef 链（相同链静默去重）")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = _run([f'{MULTI}/tdlib.c', f'{MULTI}/tdmain.c'])
    assert result == 10, f"期望 10，实际 {result}"
    assert '冲突' not in buf.getvalue(), f"相同 typedef 链不应告警: {buf.getvalue()}"
    print(f"    main() = {result}（Base→Mid 链跨文件一致，静默去重）✓")


def test_t6_typedef_conflict():
    print("  [T6] typedef 冲突：非 strict 告警 / strict 报错")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        result = _run([f'{MULTI}/cfl_a.c', f'{MULTI}/cfl_b.c'])
    assert result == 0
    assert 'typedef \'X\' 冲突' in buf.getvalue(), f"应告警 typedef 冲突: {buf.getvalue()}"
    print(f"    非 strict: main() = {result}，告警 'typedef X 冲突' ✓")
    # strict 模式 → 报错
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/cfl_a.c', f'{MULTI}/cfl_b.c'], strict=True)
    prog.load()
    try:
        prog.link()
        raise AssertionError("strict 模式应抛错")
    except AssertionError as e:
        assert 'X' in str(e) and '冲突' in str(e)
        print(f"    strict: {e} ✓")


def test_t6_func_conflict():
    print("  [T6] 函数重名（非 static 非入口）→ 报错")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/dup_a.c', f'{MULTI}/dup_b.c'])
    prog.load()
    try:
        prog.link()
        raise AssertionError("重复函数应报错")
    except AssertionError as e:
        assert 'dupf' in str(e) and '重复定义' in str(e)
        print(f"    重复函数报错: {e} ✓")


def test_t4_global_var_func_init():
    print("  [T4] 全局变量 init 调另一文件的函数: int g = helper_gv();")
    result = _run([f'{MULTI}/gv_lib.c', f'{MULTI}/gv_main.c'])
    assert result == 42, f"期望 42，实际 {result}"
    print(f"    main() = {result}（函数表先齐，全局变量 init 可调函数）✓")


def test_t7_end_to_end_three_files():
    print("  [T7] 端到端三文件：e2e_lib + e2e_util + e2e_main")
    result = _run([f'{MULTI}/e2e_lib.c', f'{MULTI}/e2e_util.c', f'{MULTI}/e2e_main.c'])
    assert result == 116, f"期望 116，实际 {result}"
    print(f"    main() = {result}（跨文件 enum + struct 返回 + 值拷贝）✓")


def test_t8_entry_args():
    print("  [T8] 入口参数：run(3, 4)")
    result = _run([f'{MULTI}/args_main.c'], args=(3, 4))
    assert result == 7, f"期望 7，实际 {result}"
    print(f"    main(3, 4) = {result} ✓")


def test_fix_repro():
    print("  [Fix] 复现用例：任意顺序类型 + 数组表达式维度 + 裸定义")
    result = _run([f'{MULTI}/repro.c'])
    assert result == 0
    result3 = _run([f'{MULTI}/repro3.c'])
    assert result3 == 5
    print(f"    repro main()={result}（u64 成员 + arr[15]）；裸定义 main()={result3} ✓")


def main():
    print("=" * 60)
    print("  program.py — 多文件支持测试（S1+S2+S3+修复）")
    print("=" * 60)
    print("\n--- 1. 双文件基础 ---")
    test_t1_two_files()
    print("\n--- 2. 前向引用 ---")
    test_t2_forward_ref()
    print("\n--- 3. main 定位 ---")
    test_t5_entry_detection()
    print("\n--- 4. 跨文件 typedef 链（T3）---")
    test_t3_typedef_chain_cross_file()
    print("\n--- 5. 冲突检测（T6）---")
    test_t6_typedef_conflict()
    test_t6_func_conflict()
    print("\n--- 6. 全局变量函数初始化（T4）---")
    test_t4_global_var_func_init()
    print("\n--- 7. 端到端三文件（T7）---")
    test_t7_end_to_end_three_files()
    print("\n--- 8. 入口参数（T8）---")
    test_t8_entry_args()
    print("\n--- 9. 修复回归 ---")
    test_fix_repro()
    print("\n" + "=" * 60)
    print("  S1 + S2 + S3 + 修复 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
