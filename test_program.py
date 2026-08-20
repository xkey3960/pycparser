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


# ==================== L1 惰性解析 ====================

import sources


def test_proto_decl_and_link_error():
    """函数原型声明（含按值传不完整类型）：注册签名占位、定义覆盖、无定义报链接错误。"""
    print("  [Proto] 原型声明：注册签名占位；无定义调用报链接错误")
    # 1) 纯原型声明文件（无 main）：能装载，func 注册为占位（body=None）
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/proto_decl.c'], lazy=False)
    prog.load()
    # link 需要 main；直接跑 run 会报未找到入口 —— 改用 load 后检查 1a/1b 之外的原型注册
    exe_mod.setup_global_scope()
    from pycparser import parse_file
    from pycparserext import ext_c_parser
    from execute import execute
    from typesys import ensure_complete
    parser = ext_c_parser.GnuCParser()
    ast = parse_file(f'{MULTI}/proto_decl.c', use_cpp=True, cpp_path='gcc',
                     cpp_args=['-E', '-Iutils/fake_libc_include'], parser=parser, encoding=None)
    for ext in ast.ext:
        execute(ext)
    f = exe_mod.g_functions.get('func')
    assert f is not None and f.body is None          # 原型 → 签名占位
    assert f.param_names == ['a1']                   # 参数名记录
    t = exe_mod.g_types.lookup_tag('struct', 'a')
    ensure_complete(t)                               # 后置定义补全
    assert t.is_complete() and [m.name for m in t.members] == ['aaa']
    print("    原型注册占位（param a1）；struct a 后置定义补全 ✓")
    # 2) 原型（main 文件） + 跨文件定义 → 正常调用（定义覆盖占位）
    exe_mod.setup_global_scope()
    prog2 = CProgram([f'{MULTI}/proto_main.c', f'{MULTI}/proto_impl.c'], lazy=True)
    prog2.load()
    result = prog2.run()
    assert result == 42, f"期望 42，实际 {result}"
    print(f"    原型+跨文件定义: main() = {result} ✓")
    # 3) 只有原型无定义 → 链接错误
    exe_mod.setup_global_scope()
    prog3 = CProgram([f'{MULTI}/proto_main.c'], lazy=True)
    prog3.load()
    try:
        prog3.run()
        raise AssertionError("应报链接错误")
    except AssertionError as e:
        assert 'func' in str(e) and '链接错误' in str(e)
        print(f"    无定义调用: {e} ✓")


def test_l1_lazy_run_no_link():
    print("  [L1] 惰性运行：跨文件函数无需 link，坏文件不报错")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy_a.c', f'{MULTI}/lazy_b.c', f'{MULTI}/lazy_bad.c'],
                    lazy=True)
    prog.load()
    result = prog.run()                        # 不调用 link
    assert result == 42, f"期望 42，实际 {result}"
    st = sources.g_source_index.state
    assert st[f'{MULTI}/lazy_a.c'] == 'loaded'      # 被 main 调用 → 已激活
    assert st[f'{MULTI}/lazy_b.c'] == 'loaded'      # 入口文件 → 已激活
    # L4 起所有文件启动装载（全局 eager）；bad 文件激活但类型惰性检查 → 不报错
    assert st[f'{MULTI}/lazy_bad.c'] == 'loaded'
    print(f"    main() = {result}；bad 文件已激活但类型错误不触发（惰性检查）✓")


def test_l1_lazy_forward_ref_order_free():
    print("  [L1] 惰性下前向引用与文件顺序无关")
    # main 文件在前、helper 文件在后（文件顺序无关）
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy_b.c', f'{MULTI}/lazy_a.c'], lazy=True)
    prog.load()
    result = prog.run()
    assert result == 42
    print(f"    main() = {result}（调用点即时激活，无需 link 的两遍注册）✓")


def test_l1_lazy_global_init_on_activation():
    print("  [L1] 全局变量在所属文件激活时初始化")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/gv_lib.c', f'{MULTI}/gv_main.c'], lazy=True)
    prog.load()
    # link 前 g 未初始化（未激活）
    assert 'g' not in exe_mod.g_scope._symbols
    result = prog.run()
    assert result == 42, f"期望 42，实际 {result}"
    # main 文件激活时全局 g = helper_gv() 已初始化
    assert exe_mod.g_scope.get('g') == 42
    print(f"    main() = {result}；激活 gv_main 时 g=helper_gv()=42 ✓")


def test_l2_cross_file_struct():
    print("  [L2] 跨文件 struct 惰性解析：main 用 struct Pt，定义在 lazy_t.c")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy_t_main.c', f'{MULTI}/lazy_t.c'], lazy=True)
    prog.load()
    result = prog.run()
    assert result == 7, f"期望 7，实际 {result}"
    assert sources.g_source_index.state[f'{MULTI}/lazy_t.c'] == 'loaded'
    st = exe_mod.g_types.lookup_tag('struct', 'Pt')
    assert st.is_complete() and st.sizeof() == 8
    print(f"    main() = {result}（struct Pt 引用时惰性装载定义文件）✓")


def test_l2_cross_file_enum():
    print("  [L2] 跨文件 enum 惰性解析：main 用 enum EColor，定义在 lazy_e.c")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy_e_main.c', f'{MULTI}/lazy_e.c'], lazy=True)
    prog.load()
    result = prog.run()
    assert result == 2, f"期望 2，实际 {result}"
    assert sources.g_source_index.state[f'{MULTI}/lazy_e.c'] == 'loaded'
    # 枚举常量随文件激活注入
    assert exe_mod.g_scope.get('EGREEN') == 1
    print(f"    main() = {result}（enum EColor 引用时惰性装载，EGREEN 随激活注入）✓")


def test_l2_genuinely_undefined_type():
    print("  [L2] 真正未定义的类型仍报错（激活后仍找不到）")
    exe_mod.setup_global_scope()
    # struct ZZMissing 无任何定义（唯一命名，避免 g_types 跨测试污染）
    prog = CProgram([f'{MULTI}/lazy_u_main.c'], lazy=True)
    prog.load()
    try:
        prog.run()
        raise AssertionError("应报错")
    except AssertionError as e:
        # 无定义 → 不完整类型 → 成员访问报"无成员"（不会静默通过）
        assert '未定义' in str(e) or '无成员' in str(e) or 'struct' in str(e)
        print(f"    {e} ✓")


# ==================== L3 默认惰性 + 冲突检测适配 ====================

def test_l3_lazy_is_default():
    print("  [L3] lazy 默认开启：不传 lazy 参数，跳过 link 直接 run")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lib.c', f'{MULTI}/main.c'])   # 无 lazy=True（默认）
    prog.load()
    result = prog.run()                                      # 不调用 link
    assert result == 57, f"期望 57，实际 {result}"
    print(f"    main() = {result}（默认 lazy，无需 link）✓")


def test_l3_lazy_conflict_on_activation():
    print("  [L3] 惰性冲突检测（用到才检）：typedef 冲突在激活时报")
    # 非 strict：main 调 b_func → 激活 lazy_cfl_b.c → typedef X 冲突告警
    exe_mod.setup_global_scope()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        prog = CProgram([f'{MULTI}/lazy_cfl_a.c', f'{MULTI}/lazy_cfl_b.c'], lazy=True)
        prog.load()
        result = prog.run()
    assert result == 1, f"期望 1，实际 {result}"
    assert 'typedef \'X\' 冲突' in buf.getvalue(), f"应告警 typedef 冲突: {buf.getvalue()}"
    print(f"    main() = {result}；激活 b 文件时告警 'typedef X 冲突' ✓")
    # strict：激活时报错
    exe_mod.setup_global_scope()
    prog2 = CProgram([f'{MULTI}/lazy_cfl_a.c', f'{MULTI}/lazy_cfl_b.c'], lazy=True, strict=True)
    prog2.load()
    try:
        prog2.run()
        raise AssertionError("strict 惰性应报错")
    except AssertionError as e:
        assert 'X' in str(e) and '冲突' in str(e)
        print(f"    strict: {e} ✓")


def test_l3_lazy_func_conflict():
    print("  [L3] 惰性函数重名检测（激活时）")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy_dup_a.c', f'{MULTI}/lazy_dup_b.c'], lazy=True)
    prog.load()
    try:
        prog.run()      # main 调 b_func → 激活 dup_b → dupf 重复定义报错
        raise AssertionError("应报错")
    except AssertionError as e:
        assert 'dupf' in str(e) and '重复定义' in str(e)
        print(f"    函数重名报错: {e} ✓")


def test_l3_eager_link_still_works():
    print("  [L3] lazy=False 全量 link 仍可用（含全量冲突检测）")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/cfl_a.c', f'{MULTI}/cfl_b.c'], lazy=False)
    prog.load()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        prog.link()
        result = prog.run()
    assert result == 0
    assert 'typedef \'X\' 冲突' in buf.getvalue()
    print(f"    link+run 正常，全量冲突检测生效 ✓")


# ==================== L4 全局 eager + 类型 lazy（惰性类型检查） ====================

def test_l4_bad_struct_in_active_file_ok():
    """坏 struct（维度引用未定义符号）所在文件被激活，但只要不使用 → 不报错。

    L4 语义：启动装载全部文件（全局 eager），struct/union 只注册不布局；
    类型错误延迟到首次真正使用（ensure_complete）。
    """
    print("  [L4] 坏 struct 文件激活但不使用 → 不报错")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy4_bad.c', f'{MULTI}/lazy4_main.c'], lazy=True)
    prog.load()
    result = prog.run()                        # activate_all：全部文件装载
    assert result == 42, f"期望 42，实际 {result}"
    st = sources.g_source_index.state
    assert st[f'{MULTI}/lazy4_bad.c'] == 'loaded'   # 已激活（全局 eager）
    # 坏 struct L4Bad 注册为不完整，未布局（未使用）
    t = exe_mod.g_types.lookup_tag('struct', 'L4Bad')
    assert not t.is_complete()
    print(f"    main() = {result}；L4Bad 已注册但不完整（类型错误未触发）✓")


def test_l4_bad_struct_error_on_use():
    """坏 struct 真正被使用（sizeof）→ 用时才检（报错）。"""
    print("  [L4] 坏 struct 被 sizeof 使用 → 用时才检")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy4_use.c'], lazy=True)
    prog.load()
    try:
        prog.run()
        raise AssertionError("应报错（使用坏 struct）")
    except AssertionError as e:
        assert 'no_such_thing_l4use' in str(e) or '维度' in str(e) \
            or '无法解析' in str(e) or '未定义' in str(e) \
            or '不完整类型' in str(e) or "'arr'" in str(e)
        print(f"    sizeof 使用时报错: {e} ✓")


def test_l4_tag_redef_conflict_on_use():
    """struct 重定义冲突（成员不同）：不使用不报；使用时才报（非 strict 告警 / strict 报错）。"""
    print("  [L4] struct 重定义冲突：用时才检")
    # 非 strict：只用 l4_dup_a（不碰 L4Dup）→ 不报
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy4_dup_a.c', f'{MULTI}/lazy4_dup_b.c'],
                    lazy=True, entry='l4_dup_a')
    prog.load()
    result = prog.run()
    assert result == 1
    t = exe_mod.g_types.lookup_tag('struct', 'L4Dup')
    assert not t.is_complete()          # 从未使用 → 从未补全 → 无冲突
    print(f"    main(l4_dup_a) = {result}；L4Dup 未补全（重定义未触发）✓")
    # 使用时：非 strict 告警并继续
    exe_mod.setup_global_scope()
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        prog2 = CProgram([f'{MULTI}/lazy4_dup_a.c', f'{MULTI}/lazy4_dup_b.c'],
                         lazy=True, entry='l4_dup_a')
        prog2.load()
        prog2._resolve_entry()
        # 手动触发补全（模拟真正使用 L4Dup：声明变量）
        from typesys import ensure_complete
        ensure_complete(exe_mod.g_types.lookup_tag('struct', 'L4Dup'))
    assert '重定义冲突' in buf.getvalue()
    print(f"    使用 L4Dup 时告警 'struct L4Dup 重定义冲突' ✓")
    # strict：使用时直接报错（清掉跨测试残留的 L4Dup，模拟全新程序）
    exe_mod.setup_global_scope()
    if ('struct', 'L4Dup') in exe_mod.g_types.tags:
        del exe_mod.g_types.tags[('struct', 'L4Dup')]
    prog3 = CProgram([f'{MULTI}/lazy4_dup_a.c', f'{MULTI}/lazy4_dup_b.c'],
                     lazy=True, entry='l4_dup_a', strict=True)
    prog3.load()
    prog3.run()          # 启动装载（activate_all）：注册全部类型（不布局）
    try:
        from typesys import ensure_complete
        ensure_complete(exe_mod.g_types.lookup_tag('struct', 'L4Dup'))
        raise AssertionError("strict 应报错")
    except AssertionError as e:
        assert '重定义冲突' in str(e)
        print(f"    strict: {e} ✓")


def test_l4_global_init_at_startup():
    """全局变量启动时初始化（activate_all 装载全部文件，不再按需）。"""
    print("  [L4] 全局变量启动时全部初始化（activate_all）")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/gv_lib.c', f'{MULTI}/gv_main.c'], lazy=True)
    prog.load()
    # 启动装载前未初始化
    assert 'g' not in exe_mod.g_scope._symbols
    result = prog.run()
    assert result == 42
    assert exe_mod.g_scope.get('g') == 42
    # 两个文件都装载（全局 eager，不只入口文件）
    st = sources.g_source_index.state
    assert st[f'{MULTI}/gv_lib.c'] == 'loaded'
    assert st[f'{MULTI}/gv_main.c'] == 'loaded'
    print(f"    main() = {result}；gv_lib/gv_main 均已装载，g=42 ✓")


def test_l4_link_still_full_check():
    """lazy=False 全量 link 仍全量检查：坏 struct 在 link 时报错（eager）。"""
    print("  [L4] link（eager 全量检查）仍对坏 struct 报错")
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/lazy4_use.c'], lazy=False)
    prog.load()
    try:
        prog.link()
        raise AssertionError("link 全量检查应报错（坏 struct）")
    except AssertionError as e:
        assert 'no_such_thing_l4use' in str(e) or '维度' in str(e) \
            or '无法解析' in str(e) or '未定义' in str(e) \
            or '不完整类型' in str(e) or "'arr'" in str(e)
        print(f"    link 时报错: {e} ✓")


def test_ptr_address_of():
    """& 取地址（引用语义）与 * 解引用（MEM-1 前最小支持）。"""
    print("  [Ptr] & 取地址 / * 解引用 / -> 经指针访问（引用语义）")
    src = '''
struct AAA { int x; int y; };
int main(void) {
    struct AAA a;
    a.x = 5;
    a.y = 37;
    struct AAA *pa = &a;
    pa->x = 99;              /* 经指针写回 a（StructValue 引用共享） */
    int via_ptr = pa->y;     /* 经指针读 */
    return a.x + via_ptr;    /* 99 + 37 = 136 */
}
'''
    with open('test/multi/ptr_main.c', 'w') as f:
        f.write(src)
    result = _run(['test/multi/ptr_main.c'])
    assert result == 136, f"期望 136，实际 {result}"
    print(f"    main() = {result}（pa->x 写回 a；经指针读写）✓")


def test_func_ptr():
    """函数名作为函数指针传入参数 / 赋值 / 经变量调用。"""
    print("  [FnPtr] 函数名作函数指针：传参 / 赋值 / 经变量调用")
    src = '''
int inc(int x) { return x + 1; }
int dbl(int x) { return x * 2; }
int apply(int (*fp)(int), int x) { return fp(x); }
int main(void) {
    int (*fp)(int);
    fp = inc;
    int a = fp(41);              /* 42（经变量调用） */
    fp = dbl;
    int b = fp(21);              /* 42 */
    fp = &inc;
    int c = fp(9);               /* 10 */
    return a + b + c + apply(inc, 41);   /* 94 + 42 = 136 */
}
'''
    with open('test/multi/fnptr_main.c', 'w') as f:
        f.write(src)
    result = _run(['test/multi/fnptr_main.c'])
    assert result == 136, f"期望 136，实际 {result}"
    print(f"    main() = {result}（apply(inc,41)=42；fp=inc/dbl/&inc 经变量调用）✓")


def test_mem2_recursion():
    """MEM-2 栈帧与递归：递归/互递归/全局计数/局部遮蔽/调用栈弹栈。"""
    print("  [MEM2] 栈帧与递归（fact / 互递归 / 全局计数 / 调用栈）")
    src = '''
int count = 0;
int fact(int n) { if (n <= 1) return 1; return n * fact(n - 1); }
int is_odd(int n);
int is_even(int n) { if (n == 0) return 1; return is_odd(n - 1); }
int is_odd(int n) { if (n == 0) return 0; return is_even(n - 1); }
int helper(int n) {
    int t = 100;                 /* 每帧局部变量独立（递归+遮蔽） */
    if (n == 0) return t;
    return helper(n - 1) + 1;
}
void bump(int n) { if (n == 0) return; count++; bump(n - 1); }
int main(void) {
    bump(10);                    /* 递归写全局 count → 10 */
    return fact(5) + is_even(10) + helper(5) + count;   /* 120+1+105+10 = 236 */
}
'''
    with open('test/multi/mem2_recursion.c', 'w') as f:
        f.write(src)
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/mem2_recursion.c'], lazy=True)
    prog.load()
    result = prog.run()
    assert result == 236, f"期望 236，实际 {result}"
    assert len(exe_mod.g_call_stack) == 0          # 调用结束后栈清空
    assert exe_mod.g_scope.get('count') == 10      # 递归写全局生效
    print(f"    main() = {result}（fact=120+is_even=1+helper=105+count=10；调用栈已清空）✓")


def test_mem1_pointer_model():
    """MEM-1 指针模型：标量写回 / 指针算术 / p[i] / p++ / 指针比较 / -> 写。"""
    print("  [MEM1] 指针模型（Address：标量写回/算术/p[i]/p++/比较）")
    src = '''
struct AAA { int x; int y; };
int main(void) {
    /* ① 标量写回（之前做不到） */
    int x = 0;
    int *p = &x;
    *p = 5;
    int a = x;                    /* 5 */
    /* ② 指针算术按元素大小 + p[i] + 写 */
    int arr[3];
    arr[0] = 10; arr[1] = 20; arr[2] = 30;
    int *q = &arr[0];
    int *r = q + 1;               /* int* → 偏移 4 字节 */
    int b = *r;                   /* 20 */
    int c = q[2];                 /* 30 */
    *(q + 1) = 99;                /* arr[1] = 99 */
    /* ③ p++ 步长 + 指针比较 */
    int *s = &arr[0];
    int eq = (s == &arr[0]);      /* 1 */
    int ne = (s == &arr[1]);      /* 0 */
    s++;
    int d = *s;                   /* 99（arr[1] 被写） */
    /* ④ -> 写 struct 成员（经 Address） */
    struct AAA o; o.x = 1; o.y = 2;
    struct AAA *po = &o;
    po->x = 100;
    int e = o.x;                  /* 100 */
    /* ⑤ &(p->member) 成员地址（printf_pointer 场景：&pc->stAAA） */
    struct AAA inner; inner.x = 6;
    struct AAA *pin = &inner;
    struct AAA *alias2 = &inner;
    alias2 = pin;                 /* 指针复制 */
    int f = alias2->x;            /* 6 */
    return a + b + c + arr[1] + eq + (1 - ne) + d + e + f;   /* 355 + 6 = 361 */
}
'''
    with open('test/multi/mem1_ptr.c', 'w') as f:
        f.write(src)
    result = _run(['test/multi/mem1_ptr.c'])
    assert result == 361, f"期望 361，实际 {result}"
    print(f"    main() = {result}（标量写回/算术/p[i]/p++/比较/-> 写/指针别名）✓")


def test_chain_ptr_member_addr():
    """链式指针 + 强转：&(p->member) 与 (AAA*)pc 强转 reinterpret（printf_pointer.c）。"""
    print("  [Ptr2] 链式指针：&(p->member) / (AAA*)pc 强转 reinterpret")
    result = _run([f'{MULTI}/chain_ptr.c'])
    assert result == 7, f"期望 7，实际 {result}"
    print(f"    main() = {result}（b.pstAAA=(AAA*)pc；pa=pa->pstNext 按 AAA 解释 → 7）✓")


def test_type2_implicit_conversion():
    """TYPE-2 隐式类型转换：整数提升 / 二元提升 / 赋值 / 参数 / 返回 / 复合赋值。"""
    print("  [TYPE2] 隐式类型转换（提升/赋值/参数/返回）")
    src = '''
double half(double x) { return x / 2; }
int trunc_int(void) { return 3.7; }          /* 返回转换 → 3 */
int main(void) {
    char c = 5;
    short s = 3;
    int a = sizeof(c + 1);                    /* 整数提升 char→int → 4 */
    int b = sizeof(s + s);                    /* 提升 short→int → 4 */
    double d = 1 + 2.5;                       /* int+double → double 3.5 */
    int x = 3.7;                              /* 赋值转换 → 3 */
    int h = (int)(half(5) * 4);               /* 参数 int→double：5.0/2=2.5 → 10 */
    int t = trunc_int();                      /* 返回转换 → 3 */
    int y = 5;
    y += 2.7;                                 /* 复合赋值 → 7 */
    return (a + b) + (int)(d * 2) + x + h + t + y;   /* 8 + 7 + 3 + 10 + 3 + 7 = 38 */
}
'''
    with open('test/multi/type2_conv.c', 'w') as f:
        f.write(src)
    result = _run(['test/multi/type2_conv.c'])
    assert result == 38, f"期望 38，实际 {result}"
    print(f"    main() = {result}（提升 sizeof=4/4、int+double=3.5、int x=3.7→3、参数/返回/复合赋值）✓")


def test_type3_constant_folding():
    """TYPE-3 常量折叠：case 标签表达式 / 枚举 case / 字符 case / case range / 位域宽度。"""
    print("  [TYPE3] 常量折叠（case 表达式/枚举/字符/range/位域宽度）")
    src = '''
enum Color { RED, GREEN, BLUE };
int pick(int x) {
    switch (x) {
        case 1 + 2: return 10;       /* 折叠为 3 */
        case GREEN: return 20;       /* 枚举常量 1 */
        case 'A': return 30;         /* 字符 65 */
        default: return 99;
    }
}
int rng(int x) {
    switch (x) {
        case 1 ... 5: return 1;      /* case range */
        default: return 0;
    }
}
struct Bits { int a : 4 + 4; int b : 3; };   /* 位域宽度折叠 4+4 → 8 */
int main(void) {
    return pick(3) + pick(1) + pick(65) + pick(9) + rng(3) + rng(9)
           + sizeof(struct Bits);    /* 10+20+30+99 + 1+0 + 8 = 168 */
}
'''
    with open('test/multi/type3_fold.c', 'w') as f:
        f.write(src)
    result = _run(['test/multi/type3_fold.c'])
    assert result == 168, f"期望 168，实际 {result}"
    print(f"    main() = {result}（case 1+2/GREEN/'A'/range、位域 4+4→8）✓")


def test_qol1_error_traceback():
    """QOL-1 错误回溯：源码位置（coord）+ 调用链 + 异常分类。"""
    print("  [QOL1] 错误回溯（coord 定位 + 调用链 + 分类）")
    src = '''
int inner(int a) {
    return a + zz;               /* 第 3 行：未定义 zz */
}
int helper(int x) {
    return inner(x) + 1;         /* 第 6 行调用 */
}
int main(void) {
    return helper(5);            /* 第 9 行调用 */
}
'''
    with open('test/multi/qol1_err.c', 'w') as f:
        f.write(src)
    exe_mod.setup_global_scope()
    prog = CProgram([f'{MULTI}/qol1_err.c'], lazy=True)
    prog.load()
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            prog.run()
        raise AssertionError("应报未定义变量")
    except AssertionError as e:
        # 异常分类（InterpreterError 子类）+ 源码位置
        assert isinstance(e, exe_mod.UndefinedVariable), type(e).__name__
        assert 'qol1_err.c:3' in str(e), f"应含源码位置: {str(e)}"
        assert "Undefined variable: 'zz'" in str(e)
    out = buf.getvalue()
    # 错误报告：coord + 调用链（main → helper → inner）
    assert '[error]' in out and 'qol1_err.c:3' in out, out
    assert '调用链' in out, out
    assert 'helper' in out and 'inner' in out, out
    print(f"    [error] {out.strip().splitlines()[0]}（coord 定位）")
    print("    调用链 main → helper → inner ✓（异常分类 UndefinedVariable）")


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
    print("\n--- 10. L1 惰性解析 ---")
    test_proto_decl_and_link_error()
    test_l1_lazy_run_no_link()
    test_l1_lazy_forward_ref_order_free()
    test_l1_lazy_global_init_on_activation()
    print("\n--- 11. L2 类型引用钩子 ---")
    test_l2_cross_file_struct()
    test_l2_cross_file_enum()
    test_l2_genuinely_undefined_type()
    print("\n--- 12. L3 默认惰性 + 冲突检测适配 ---")
    test_l3_lazy_is_default()
    test_l3_lazy_conflict_on_activation()
    test_l3_lazy_func_conflict()
    test_l3_eager_link_still_works()
    print("\n--- 13. L4 全局 eager + 类型 lazy ---")
    test_l4_bad_struct_in_active_file_ok()
    test_l4_bad_struct_error_on_use()
    test_l4_tag_redef_conflict_on_use()
    test_l4_global_init_at_startup()
    test_l4_link_still_full_check()
    print("\n--- 14. 指针（& / * / -> 最小支持）---")
    test_ptr_address_of()
    print("\n--- 15. 函数指针 ---")
    test_func_ptr()
    print("\n--- 16. MEM-2 栈帧与递归 ---")
    test_mem2_recursion()
    print("\n--- 17. MEM-1 指针模型 ---")
    test_mem1_pointer_model()
    print("\n--- 17b. 链式指针成员地址 ---")
    test_chain_ptr_member_addr()
    print("\n--- 18. TYPE-2 隐式类型转换 ---")
    test_type2_implicit_conversion()
    print("\n--- 19. TYPE-3 常量折叠 ---")
    test_type3_constant_folding()
    print("\n--- 20. QOL-1 错误回溯 ---")
    test_qol1_error_traceback()
    print("\n" + "=" * 60)
    print("  S1-S3 + 修复 + L1/L2/L3/L4 + 指针 + 函数指针 + 栈帧 + 指针模型 + 类型转换 + 常量折叠 + 错误回溯 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
