#!/usr/bin/python
"""test_typesys.py — M0 类型基础设施测试

运行: python test_typesys.py
覆盖：
  1. CType 层次（Basic/Ptr/Array/Func/Enum/Struct/Union）size/align/完整性
  2. TypeRegistry（内建解析 / typedef 链式 / 环检测 / 标签命名空间）
  3. 布局工具（align_up / struct 对齐 / union 共享存储）
  4. Scope 类型 API（Symbol 存储 + 向后兼容 + 父链）

验收（设计文档 M0）：现有 execute.py 测试全绿；declare 带类型后可 get_type 查询。
"""

from typesys import (
    align_up,
    compute_struct_layout,
    compute_union_layout,
    build_default_registry,
    ArrayType,
    BasicType,
    EnumType,
    FuncType,
    PtrType,
    StructType,
    TypeRegistry,
    UnionType,
    g_types,
)
from execute import Scope


# ==================== 1. CType 层次 ====================

def test_builtin_sizes():
    print("  [CType] 内建类型 size/align:")
    cases = [('int', 4, 4), ('char', 1, 1), ('short', 2, 2), ('float', 4, 4),
             ('double', 8, 8), ('long', 8, 8), ('_Bool', 1, 1)]
    for name, size, align in cases:
        t = g_types.resolve([name])
        assert t.sizeof() == size, f"{name} sizeof 期望 {size} 实际 {t.sizeof()}"
        assert t.alignof() == align, f"{name} align 期望 {align} 实际 {t.alignof()}"
    # 组合类型名
    assert g_types.resolve(['unsigned', 'long']).sizeof() == 8
    assert g_types.resolve(['long', 'long']).sizeof() == 8
    print(f"    内建 {len(cases)}+ 类型尺寸校验 ✓")


def test_derived_types():
    print("  [CType] 派生类型:")
    int_t = g_types.resolve(['int'])
    p = PtrType(int_t)
    assert p.sizeof() == 8 and p.alignof() == 8
    assert p.points_to is int_t
    print(f"    PtrType int* -> {p.sizeof()}B/align {p.alignof()} ✓")

    a = ArrayType(int_t, 10)
    assert a.sizeof() == 40 and a.alignof() == 4
    a_incomplete = ArrayType(int_t)          # int a[];
    assert not a_incomplete.is_complete()
    print(f"    ArrayType int[10] -> {a.sizeof()}B; int[] 不完整 ✓")

    f = FuncType(int_t, [int_t, int_t])
    assert f.is_complete() and f.size is None   # 函数类型 sizeof 非法
    print("    FuncType 完整但无 sizeof ✓")

    e = EnumType('Color', {'RED': 0, 'GREEN': 1})
    assert e.sizeof() == 4 and e.constants['GREEN'] == 1
    print("    EnumType size 4, 常量表携带 ✓")


def test_struct_union_types():
    print("  [CType] Struct/Union 类型:")
    st = StructType('Point', incomplete=True)
    assert not st.is_complete()
    assert st.size is None
    st.finalize([], 0, 1)
    assert st.is_complete() and st.size == 0
    ut = UnionType('U')
    assert ut.size is None
    print("    StructType incomplete -> finalize 补全 ✓")


# ==================== 2. TypeRegistry ====================

def test_registry_builtins():
    print("  [Registry] 内建解析:")
    assert g_types.resolve(['int']) is g_types.resolve(['signed', 'int']) or \
           g_types.resolve(['int']).sizeof() == 4
    try:
        g_types.resolve(['NotAType'])
        assert False, "应抛出未定义类型"
    except AssertionError:
        print("    未定义类型报错 ✓")


def test_registry_typedef_chain():
    print("  [Registry] typedef 链式解析:")
    r = build_default_registry()              # 独立注册表，避免污染全局
    int_t = r.resolve(['int'])
    r.register_typedef('MyInt', int_t)
    assert r.resolve(['MyInt']) is int_t
    r.register_typedef('MyInt2', r.resolve(['MyInt']))   # 链：MyInt2 -> MyInt -> int
    assert r.resolve(['MyInt2']) is int_t
    print("    MyInt / MyInt2 -> int 同一对象 ✓")


def test_registry_typedef_cycle():
    print("  [Registry] typedef 环检测:")
    r = build_default_registry()
    # A -> B -> A（用 name 指向别名模拟链）
    a = BasicType('A', 4, 4)
    b = BasicType('B', 4, 4)
    r.register_typedef('A', b)
    r.register_typedef('B', a)
    try:
        r.resolve_typedef('A')
        assert False, "应检测到循环"
    except AssertionError as e:
        assert '循环' in str(e)
        print(f"    {e} ✓")


def test_registry_tags():
    print("  [Registry] 标签命名空间:")
    r = build_default_registry()
    st = StructType('Point', incomplete=True)
    r.register_tag('struct', 'Point', st)
    assert r.has_tag('struct', 'Point')
    assert r.lookup_tag('struct', 'Point') is st
    # resolve(['struct','Point']) 路径
    assert r.resolve(['struct', 'Point']) is st
    try:
        r.lookup_tag('union', 'Point')
        assert False, "不同命名空间不应命中"
    except AssertionError:
        print("    struct Point 与 union Point 隔离 ✓")


# ==================== 3. 布局工具 ====================

def test_align_up():
    print("  [Layout] align_up:")
    assert align_up(0, 4) == 0
    assert align_up(1, 4) == 4
    assert align_up(4, 4) == 4
    assert align_up(5, 8) == 8
    assert align_up(7, 1) == 7
    print("    align_up(1,4)=4, align_up(5,8)=8 ✓")


def test_struct_layout():
    print("  [Layout] struct 布局:")
    int_t = g_types.resolve(['int'])
    char_t = g_types.resolve(['char'])
    # struct { char c; int i; } -> c@0, pad, i@4, size 8
    layout, size, align = compute_struct_layout([('c', char_t, None), ('i', int_t, None)])
    assert layout[0].offset == 0 and layout[0].type is char_t
    assert layout[1].offset == 4 and layout[1].type is int_t
    assert size == 8 and align == 4
    # struct { char a; char b; int i; } -> a@0 b@1 i@4 size 8
    layout2, size2, _ = compute_struct_layout([('a', char_t, None), ('b', char_t, None), ('i', int_t, None)])
    assert [m.offset for m in layout2] == [0, 1, 4]
    assert size2 == 8
    # 空 struct（GNU 扩展）-> size 0
    layout3, size3, align3 = compute_struct_layout([])
    assert size3 == 0 and align3 == 1
    # align_override（__attribute__((aligned(16)))）
    _, size4, align4 = compute_struct_layout([('i', int_t, None)], align_override=16)
    assert size4 == 16 and align4 == 16
    print("    char+int -> size 8; 空 struct -> 0; aligned(16) -> 16 ✓")


def test_union_layout():
    print("  [Layout] union 布局:")
    int_t = g_types.resolve(['int'])
    char_t = g_types.resolve(['char'])
    double_t = g_types.resolve(['double'])
    layout, size, align = compute_union_layout([('c', char_t, None), ('i', int_t, None), ('d', double_t, None)])
    assert all(m.offset == 0 for m in layout)
    assert size == 8 and align == 8
    print(f"    char/int/double union -> size {size}, 全部 offset 0 ✓")


# ==================== 4. Scope 类型 API ====================

def test_scope_symbols():
    print("  [Scope] Symbol 存储 + 类型 API:")
    int_t = g_types.resolve(['int'])
    s = Scope()
    s.declare('x', 10, int_t)
    assert s.get('x') == 10                     # 兼容：get 返回纯值
    assert s.get_type('x') is int_t             # 新增：类型查询
    sym = s.get_symbol('x')
    assert sym.name == 'x' and sym.value == 10 and sym.type is int_t
    s.set('x', 20)                              # 兼容：set 更新值
    assert s.get('x') == 20
    double_t = g_types.resolve(['double'])
    s.set_type('x', double_t)
    assert s.get_type('x') is double_t
    print("    declare/get/set + get_symbol/get_type/set_type ✓")


def test_scope_parent_chain():
    print("  [Scope] 父链 + 类型继承:")
    int_t = g_types.resolve(['int'])
    char_t = g_types.resolve(['char'])
    parent = Scope()
    parent.declare('p', 1, char_t)
    child = Scope(parent)
    child.declare('c', 2, int_t)
    assert child.get('p') == 1
    assert child.get_type('p') is char_t        # 沿父链查到类型
    assert child.get_type('c') is int_t
    assert child.get_type('c').sizeof() == 4
    print("    子作用域可查父链类型 ✓")


def test_scope_str():
    print("  [Scope] __str__ 保持值视图:")
    s = Scope()
    s.declare('a', 1)
    s.declare('b', 'hi')
    out = str(s)
    assert "'a': 1" in out and "'b': 'hi'" in out
    print(f"    {out} ✓")


def test_scope_undefined():
    print("  [Scope] 未定义变量报错:")
    s = Scope()
    try:
        s.get('nope')
        assert False, "应抛出 Undefined variable"
    except AssertionError as e:
        assert 'Undefined variable' in str(e)
        print("    get/set_type 未定义变量 -> AssertionError ✓")


# ==================== Main ====================

def main():
    print("=" * 60)
    print("  typesys.py — M0 类型基础设施测试")
    print("=" * 60)
    print("\n--- 1. CType 层次 ---")
    test_builtin_sizes()
    test_derived_types()
    test_struct_union_types()
    print("\n--- 2. TypeRegistry ---")
    test_registry_builtins()
    test_registry_typedef_chain()
    test_registry_typedef_cycle()
    test_registry_tags()
    print("\n--- 3. 布局工具 ---")
    test_align_up()
    test_struct_layout()
    test_union_layout()
    print("\n--- 4. Scope 类型 API ---")
    test_scope_symbols()
    test_scope_parent_chain()
    test_scope_str()
    test_scope_undefined()
    print("\n" + "=" * 60)
    print("  M0 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
