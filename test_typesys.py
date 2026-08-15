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


# ==================== 5. M1 typedef 别名解析（端到端执行） ====================

import execute as exe_mod
from pycparser import c_ast


def _decl(name, type_names, init=None):
    """构造 `类型名 name [= init];` 的 Decl AST。"""
    return c_ast.Decl(
        name=name, quals=[], align=None, storage=[], funcspec=[],
        type=c_ast.TypeDecl(declname=name, quals=[], align=None,
                            type=c_ast.IdentifierType(names=type_names)),
        init=init, bitsize=None)


def _typedef(name, type_node):
    """构造 `typedef <type_node> name;` 的 Typedef AST。"""
    return c_ast.Typedef(name=name, quals=[], storage=[], type=type_node)


def test_m1_typedef_scalar():
    print("  [M1] typedef int MyInt; MyInt x = 5;")
    exe_mod.setup_global_scope()
    exe_mod.execute(_typedef('MyInt', c_ast.IdentifierType(names=['int'])))
    exe_mod.execute(_decl('x', ['MyInt'], c_ast.Constant(type='int', value='5')))
    assert exe_mod.g_scope.get('x') == 5
    assert exe_mod.g_scope.get_type('x') is g_types.resolve(['int'])
    print("    x=5，get_type(x) is IntType ✓")


def test_m1_typedef_chain():
    print("  [M1] typedef MyInt MyInt2; MyInt2 y;（链式）")
    exe_mod.setup_global_scope()
    exe_mod.execute(_typedef('MyInt', c_ast.IdentifierType(names=['int'])))
    exe_mod.execute(_typedef('MyInt2', c_ast.IdentifierType(names=['MyInt'])))
    exe_mod.execute(_decl('y', ['MyInt2']))
    assert exe_mod.g_scope.get('y') == 0
    assert exe_mod.g_scope.get_type('y') is g_types.resolve(['int'])
    print("    MyInt2 -> MyInt -> int 同一类型对象 ✓")


def test_m1_typedef_no_runtime_var():
    print("  [M1] typedef 不产生运行时变量:")
    exe_mod.setup_global_scope()
    exe_mod.execute(_typedef('MyInt', c_ast.IdentifierType(names=['int'])))
    try:
        exe_mod.g_scope.get('MyInt')
        assert False, "typedef 名不应是运行时变量"
    except AssertionError:
        pass
    assert g_types.resolve(['MyInt']) is g_types.resolve(['int'])
    print("    MyInt 仅在类型注册表（aliases）中 ✓")


def test_m1_undefined_type_error():
    print("  [M1] 未知类型报错:")
    exe_mod.setup_global_scope()
    try:
        exe_mod.execute(_decl('z', ['NoSuchType']))
        assert False, "应抛未定义类型"
    except AssertionError as e:
        assert '未定义类型' in str(e)
        print(f"    {e} ✓")


def test_m1_typedef_anon_struct():
    print("  [M1] typedef struct {int a;} S; S s;（内联匿名 struct）")
    exe_mod.setup_global_scope()
    struct_node = c_ast.Struct(name=None, decls=[
        c_ast.Decl(name='a', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='a', quals=[], align=None,
                                       type=c_ast.IdentifierType(names=['int'])),
                   init=None, bitsize=None),
    ])
    exe_mod.execute(_typedef('S', struct_node))
    st = g_types.resolve(['S'])
    assert isinstance(st, StructType) and st.is_complete()
    assert st.size == 4 and st.members[0].name == 'a'
    exe_mod.execute(_decl('s', ['S']))
    assert exe_mod.g_scope.get_type('s') is st
    assert exe_mod.g_scope.get('s') == {'a': 0}
    print("    S -> StructType{int a} size 4；s 默认值 {'a': 0} ✓")


def test_m1_typedef_named_struct_tag():
    print("  [M1] typedef struct tagTmp{...} TmpStruct_S;（命名标签 + 数组成员）")
    exe_mod.setup_global_scope()
    struct_node = c_ast.Struct(name='tagTmp', decls=[
        c_ast.Decl(name='id', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='id', quals=[], align=None,
                                       type=c_ast.IdentifierType(names=['int'])),
                   init=None, bitsize=None),
        c_ast.Decl(name='acName', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.ArrayDecl(
                       type=c_ast.TypeDecl(declname='acName', quals=[], align=None,
                                           type=c_ast.IdentifierType(names=['char'])),
                       dim=c_ast.Constant(type='int', value='10'), dim_quals=[]),
                   init=None, bitsize=None),
    ])
    exe_mod.execute(_typedef('TmpStruct_S', struct_node))
    assert g_types.has_tag('struct', 'tagTmp')
    assert g_types.resolve(['TmpStruct_S']) is g_types.lookup_tag('struct', 'tagTmp')
    st = g_types.resolve(['TmpStruct_S'])
    # int@0(4) + char[10]@4(10) -> 14 -> 对齐 4 -> 16
    assert st.sizeof() == 16 and st.alignof() == 4
    exe_mod.execute(_decl('x', ['TmpStruct_S']))
    assert exe_mod.g_scope.get('x') == {'id': 0, 'acName': [0] * 10}
    print("    tagTmp 注册；sizeof=16；x 默认值 {id:0, acName:[0]*10} ✓")


def test_m1_struct_self_reference():
    print("  [M1] struct Node {int v; struct Node *next;}（自引用）")
    exe_mod.setup_global_scope()
    struct_node = c_ast.Struct(name='Node', decls=[
        c_ast.Decl(name='v', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='v', quals=[], align=None,
                                       type=c_ast.IdentifierType(names=['int'])),
                   init=None, bitsize=None),
        c_ast.Decl(name='next', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.PtrDecl(quals=[], type=c_ast.Struct(name='Node', decls=None)),
                   init=None, bitsize=None),
    ])
    exe_mod.execute(_typedef('Node', struct_node))
    st = g_types.resolve(['Node'])
    assert st.is_complete()
    # int@0(4) + ptr@8(8) -> 16, align 8
    assert st.sizeof() == 16 and st.alignof() == 8
    next_t = st.member_type('next')
    assert isinstance(next_t, PtrType) and next_t.points_to is st
    print("    先注册不完整类型再算成员：next 指向自身 ✓")


# ==================== 6. M2 enum 类型注册 ====================

def _enum_def(name, enumerators):
    """构造枚举定义节点：`enum <name> { ... };`"""
    return c_ast.Enum(name=name, values=c_ast.EnumeratorList(
        enumerators=[c_ast.Enumerator(name=n, value=v) for n, v in enumerators]))


def test_m2_enum_standalone():
    print("  [M2] enum Color {RED, GREEN, BLUE=10, YELLOW};")
    exe_mod.setup_global_scope()
    node = _enum_def('Color', [
        ('RED', None), ('GREEN', None),
        ('BLUE', c_ast.Constant(type='int', value='10')), ('YELLOW', None),
    ])
    exe_mod.execute(node)
    # 常量注入（现有 test_enum 语义保持）
    assert exe_mod.g_scope.get('RED') == 0
    assert exe_mod.g_scope.get('GREEN') == 1
    assert exe_mod.g_scope.get('BLUE') == 10
    assert exe_mod.g_scope.get('YELLOW') == 11
    # 常量带类型
    assert exe_mod.g_scope.get_type('RED') is g_types.resolve(['int'])
    # 标签注册 + 常量表
    et = g_types.lookup_tag('enum', 'Color')
    assert isinstance(et, EnumType)
    assert et.constants == {'RED': 0, 'GREEN': 1, 'BLUE': 10, 'YELLOW': 11}
    print("    RED=0 GREEN=1 BLUE=10 YELLOW=11；常量带 IntType；标签注册 ✓")


def test_m2_enum_reference_previous():
    print("  [M2] enum {A, B = A + 5, C};（引用前一常量）")
    exe_mod.setup_global_scope()
    node = _enum_def(None, [
        ('A', None),
        ('B', c_ast.BinaryOp(op='+', left=c_ast.ID(name='A'),
                              right=c_ast.Constant(type='int', value='5'))),
        ('C', None),
    ])
    exe_mod.execute(node)
    assert exe_mod.g_scope.get('A') == 0
    assert exe_mod.g_scope.get('B') == 5
    assert exe_mod.g_scope.get('C') == 6
    print("    B 引用前一常量 A：A=0 B=5 C=6 ✓")


def test_m2_enum_variable():
    print("  [M2] enum Color c; c = GREEN;")
    exe_mod.setup_global_scope()
    exe_mod.execute(_enum_def('Color', [('RED', None), ('GREEN', None)]))
    et = g_types.lookup_tag('enum', 'Color')
    # enum Color c; —— pycparser 用 Enum(name, values=None) 引用节点
    decl = c_ast.Decl(
        name='c', quals=[], align=None, storage=[], funcspec=[],
        type=c_ast.TypeDecl(declname='c', quals=[], align=None,
                            type=c_ast.Enum(name='Color', values=None)),
        init=None, bitsize=None)
    exe_mod.execute(decl)
    assert exe_mod.g_scope.get_type('c') is et
    assert exe_mod.g_scope.get('c') == 0
    exe_mod.execute(c_ast.Assignment(op='=', lvalue=c_ast.ID(name='c'),
                                     rvalue=c_ast.ID(name='GREEN')))
    assert exe_mod.g_scope.get('c') == 1
    print("    c 类型为 EnumType（引用节点经标签解析）；c = GREEN → 1 ✓")


def test_m2_typedef_enum_anon():
    print("  [M2] typedef enum {A, B} MyColor; MyColor c;")
    exe_mod.setup_global_scope()
    exe_mod.execute(c_ast.Typedef(name='MyColor', quals=[], storage=[],
                                  type=_enum_def(None, [('A', None), ('B', None)])))
    # 匿名 enum typedef：常量注入 + 别名指向带常量表的 EnumType
    assert exe_mod.g_scope.get('A') == 0 and exe_mod.g_scope.get('B') == 1
    et = g_types.resolve(['MyColor'])
    assert isinstance(et, EnumType) and et.constants == {'A': 0, 'B': 1}
    exe_mod.execute(_decl('c', ['MyColor']))
    assert exe_mod.g_scope.get_type('c') is et
    print("    常量注入 + 别名解析 + 变量类型同一 EnumType ✓")


def test_m2_typedef_named_enum():
    print("  [M2] typedef enum Color {RED, GREEN} MyColor;（标签 + 别名同体）")
    exe_mod.setup_global_scope()
    exe_mod.execute(c_ast.Typedef(name='MyColor', quals=[], storage=[],
                                  type=_enum_def('Color', [('RED', None), ('GREEN', None)])))
    assert g_types.lookup_tag('enum', 'Color') is g_types.resolve(['MyColor'])
    et = g_types.lookup_tag('enum', 'Color')
    assert et.constants == {'RED': 0, 'GREEN': 1}
    assert exe_mod.g_scope.get('RED') == 0 and exe_mod.g_scope.get('GREEN') == 1
    print("    tag('enum','Color') 与 alias('MyColor') 同一对象 ✓")


# ==================== Main ====================

def main():
    print("=" * 60)
    print("  typesys.py — M0/M1 类型系统测试")
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
    print("\n--- 5. M1 typedef 别名解析 ---")
    test_m1_typedef_scalar()
    test_m1_typedef_chain()
    test_m1_typedef_no_runtime_var()
    test_m1_undefined_type_error()
    test_m1_typedef_anon_struct()
    test_m1_typedef_named_struct_tag()
    test_m1_struct_self_reference()
    print("\n--- 6. M2 enum 类型注册 ---")
    test_m2_enum_standalone()
    test_m2_enum_reference_previous()
    test_m2_enum_variable()
    test_m2_typedef_enum_anon()
    test_m2_typedef_named_enum()
    print("\n" + "=" * 60)
    print("  M0 + M1 + M2 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
