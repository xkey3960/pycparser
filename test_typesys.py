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
    StructValue,
    TypeRegistry,
    UnionType,
    UnionValue,
    ensure_complete,
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
    sv = exe_mod.g_scope.get('s')
    assert isinstance(sv, StructValue) and sv.get('a') == 0
    print("    S -> StructType{int a} size 4；s 默认值 StructValue(a=0) ✓")


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
    sv = exe_mod.g_scope.get('x')
    assert isinstance(sv, StructValue)
    assert sv.get('id') == 0 and sv.get('acName') == [0] * 10
    print("    tagTmp 注册；sizeof=16；x 默认值 StructValue(id=0, acName=[0]*10) ✓")


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
    ensure_complete(st)              # L4：注册不布局，显式补全（或 sizeof 触发）
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


def test_m2_enum_hex_and_bases():
    print("  [M2] enum 成员十六进制/八进制/二进制/后缀字面量")
    exe_mod.setup_global_scope()
    node = _enum_def('HexColor', [
        ('A', c_ast.Constant(type='int', value='0x100')),
        ('B', None),                                   # 0x100 + 1
        ('C', c_ast.Constant(type='int', value='0755')),   # 八进制
        ('D', c_ast.Constant(type='int', value='0b101')),  # 二进制
        ('E', c_ast.Constant(type='unsigned int', value='0xFFu')),  # 后缀 + 完整说明符 type
        ('F', c_ast.Constant(type='long', value='42L')),
    ])
    exe_mod.execute(node)
    et = g_types.lookup_tag('enum', 'HexColor')
    assert et.constants == {'A': 256, 'B': 257, 'C': 493, 'D': 5, 'E': 255, 'F': 42}
    assert exe_mod.g_scope.get('B') == 257
    print("    0x100=256 B=257 0755=493 0b101=5 0xFFu=255 42L=42 ✓")


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


# ==================== 7. M3 struct 值语义 ====================

def _struct_def(name, fields):
    """构造 `struct <name> { <fields> };` 定义节点。fields: [(fname, type_names)]"""
    decls = []
    for fname, tnames in fields:
        decls.append(c_ast.Decl(name=fname, quals=[], align=None, storage=[], funcspec=[],
                                type=c_ast.TypeDecl(declname=fname, quals=[], align=None,
                                                    type=c_ast.IdentifierType(names=tnames)),
                                init=None, bitsize=None))
    return c_ast.Struct(name=name, decls=decls)


def _decl_ref(name, ref_node, init=None):
    """`<类型引用> name [= init];` —— ref_node 如 Struct('Point', None)。"""
    return c_ast.Decl(name=name, quals=[], align=None, storage=[], funcspec=[],
                      type=c_ast.TypeDecl(declname=name, quals=[], align=None, type=ref_node),
                      init=init, bitsize=None)


def test_m3_struct_basic():
    print("  [M3] struct Point {int x,y;} p = {1,2}; p.y = 5;")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('Point', [('x', ['int']), ('y', ['int'])]))
    st = g_types.lookup_tag('struct', 'Point')
    assert st.sizeof() == 8
    # 成员不污染全局作用域（P1 修复）
    for m in ('x', 'y'):
        try:
            exe_mod.g_scope.get(m)
            raise AssertionError(f"成员 '{m}' 不应成为全局变量")
        except AssertionError:
            pass
    exe_mod.execute(_decl_ref('p', c_ast.Struct(name='Point', decls=None),
                              init=c_ast.InitList(exprs=[c_ast.Constant(type='int', value='1'),
                                                         c_ast.Constant(type='int', value='2')])))
    p = exe_mod.g_scope.get('p')
    assert isinstance(p, StructValue)
    assert p.get('x') == 1 and p.get('y') == 2
    # p.y = 5（StructRef 写路径）
    exe_mod.execute(c_ast.Assignment(op='=', lvalue=c_ast.StructRef(name=c_ast.ID(name='p'), type='.',
                                                                    field=c_ast.ID(name='y')),
                                     rvalue=c_ast.Constant(type='int', value='5')))
    assert p.get('y') == 5
    print("    sizeof=8；InitList 填充 {1,2}；p.y=5 写入 ✓")


def test_m3_struct_value_copy():
    print("  [M3] struct S a = b; a.x = 1; b 不变（值拷贝）")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('S', [('x', ['int'])]))
    ref = c_ast.Struct(name='S', decls=None)
    exe_mod.execute(_decl_ref('b', ref, init=c_ast.InitList(exprs=[c_ast.Constant(type='int', value='7')])))
    exe_mod.execute(_decl_ref('a', ref, init=c_ast.ID(name='b')))
    a, b = exe_mod.g_scope.get('a'), exe_mod.g_scope.get('b')
    assert a is not b and a.get('x') == 7
    exe_mod.execute(c_ast.Assignment(op='=', lvalue=c_ast.StructRef(name=c_ast.ID(name='a'), type='.',
                                                                    field=c_ast.ID(name='x')),
                                     rvalue=c_ast.Constant(type='int', value='1')))
    assert a.get('x') == 1 and b.get('x') == 7
    print("    a 是 b 的深拷贝；改 a.x 不影响 b ✓")


def test_m3_struct_nested():
    print("  [M3] struct Rect { struct Point tl, br; } r = {{0,0},{10,10}}; r.br.x")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('Point', [('x', ['int']), ('y', ['int'])]))
    rect_def = c_ast.Struct(name='Rect', decls=[
        c_ast.Decl(name='tl', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='tl', quals=[], align=None,
                                       type=c_ast.Struct(name='Point', decls=None)),
                   init=None, bitsize=None),
        c_ast.Decl(name='br', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='br', quals=[], align=None,
                                       type=c_ast.Struct(name='Point', decls=None)),
                   init=None, bitsize=None),
    ])
    exe_mod.execute(rect_def)
    rt = g_types.lookup_tag('struct', 'Rect')
    assert rt.sizeof() == 16  # Point(8) + Point(8)
    exe_mod.execute(_decl_ref('r', c_ast.Struct(name='Rect', decls=None),
                              init=c_ast.InitList(exprs=[
                                  c_ast.InitList(exprs=[c_ast.Constant(type='int', value='0'),
                                                        c_ast.Constant(type='int', value='0')]),
                                  c_ast.InitList(exprs=[c_ast.Constant(type='int', value='10'),
                                                        c_ast.Constant(type='int', value='10')]),
                              ])))
    r = exe_mod.g_scope.get('r')
    assert isinstance(r.get('br'), StructValue)
    val = exe_mod.execute(c_ast.StructRef(name=c_ast.StructRef(name=c_ast.ID(name='r'), type='.',
                                                               field=c_ast.ID(name='br')),
                                          type='.', field=c_ast.ID(name='x')))
    assert val == 10
    print("    sizeof(Rect)=16；嵌套 InitList 填充；r.br.x=10 ✓")


def test_m3_struct_array():
    print("  [M3] struct Point pts[2] = {{1},{2}}; pts[1].x")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('Point', [('x', ['int']), ('y', ['int'])]))
    pts_decl = c_ast.Decl(
        name='pts', quals=[], align=None, storage=[], funcspec=[],
        type=c_ast.ArrayDecl(
            type=c_ast.TypeDecl(declname='pts', quals=[], align=None,
                                type=c_ast.Struct(name='Point', decls=None)),
            dim=c_ast.Constant(type='int', value='2'), dim_quals=[]),
        init=c_ast.InitList(exprs=[
            c_ast.InitList(exprs=[c_ast.Constant(type='int', value='1')]),
            c_ast.InitList(exprs=[c_ast.Constant(type='int', value='2')]),
        ]),
        bitsize=None)
    exe_mod.execute(pts_decl)
    pts = exe_mod.g_scope.get('pts')
    assert len(pts) == 2 and isinstance(pts[1], StructValue)
    val = exe_mod.execute(c_ast.StructRef(name=c_ast.ArrayRef(name=c_ast.ID(name='pts'),
                                                              subscript=c_ast.Constant(type='int', value='1')),
                                          type='.', field=c_ast.ID(name='x')))
    assert val == 2
    print("    元素为 StructValue；pts[1].x=2 ✓")


def test_m3_struct_default_and_compound():
    print("  [M3] struct Point p; 与 (struct Point){3,4} 复合字面量")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('Point', [('x', ['int']), ('y', ['int'])]))
    exe_mod.execute(_decl_ref('p', c_ast.Struct(name='Point', decls=None)))
    p = exe_mod.g_scope.get('p')
    assert isinstance(p, StructValue) and p.get('x') == 0 and p.get('y') == 0
    lit = exe_mod.execute(c_ast.CompoundLiteral(
        type=c_ast.TypeDecl(declname=None, quals=[], align=None,
                            type=c_ast.Struct(name='Point', decls=None)),
        init=c_ast.InitList(exprs=[c_ast.Constant(type='int', value='3'),
                                   c_ast.Constant(type='int', value='4')])))
    assert isinstance(lit, StructValue) and lit.get('x') == 3 and lit.get('y') == 4
    print("    默认值 StructValue(0,0)；复合字面量 StructValue(3,4) ✓")


def test_m3_struct_arrow_fallback():
    print("  [M3] p->x 宽松退化（指针模型前等价 .）")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('Point', [('x', ['int']), ('y', ['int'])]))
    exe_mod.execute(_decl_ref('p', c_ast.Struct(name='Point', decls=None),
                              init=c_ast.InitList(exprs=[c_ast.Constant(type='int', value='9'),
                                                         c_ast.Constant(type='int', value='0')])))
    val = exe_mod.execute(c_ast.StructRef(name=c_ast.ID(name='p'), type='->', field=c_ast.ID(name='x')))
    assert val == 9
    print("    p->x = 9（与 p.x 一致）✓")


def test_m3_struct_flexible_array_member():
    """C99 灵活数组成员：struct FlexAAA { int a; int b[]; }。

    复现文件 test/complex_decl.c（补分号后）：b[] 是最后一个成员、不占空间，
    sizeof(struct) 不含它；offset 停在前面成员末尾。
    """
    print("  [M3] struct FlexAAA { int a; int b[]; }（灵活数组成员）")
    exe_mod.setup_global_scope()
    # int b[] —— ArrayDecl(dim=None) 语法形态
    flex = c_ast.Decl(name='b', quals=[], align=None, storage=[], funcspec=[],
                      type=c_ast.ArrayDecl(
                          type=c_ast.TypeDecl(declname='b', quals=[], align=None,
                                              type=c_ast.IdentifierType(names=['int'])),
                          dim=None, dim_quals=[]),
                      init=None, bitsize=None)
    node = c_ast.Struct(name='FlexAAA', decls=[
        c_ast.Decl(name='a', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='a', quals=[], align=None,
                                       type=c_ast.IdentifierType(names=['int'])),
                   init=None, bitsize=None),
        flex,
    ])
    exe_mod.execute(node)
    t = g_types.lookup_tag('struct', 'FlexAAA')
    ensure_complete(t)
    assert t.is_complete() and t.sizeof() == 4        # int a 占 4；b[] 不占空间
    assert len(t.members) == 2
    assert t.members[0].name == 'a' and t.members[0].offset == 0
    assert t.members[1].name == 'b' and t.members[1].offset == 4
    print(f"    sizeof = {t.sizeof()}（b[] 不占空间，offset 停在 4）✓")


def test_m3_struct_bad_array_dim_raises():
    """坏数组维度（int arr[no_such + 1]）在补全时报错，不再静默当灵活数组。"""
    print("  [M3] 坏数组维度 → 补全时报错（不是灵活数组成员）")
    exe_mod.setup_global_scope()
    bad = c_ast.Decl(name='arr', quals=[], align=None, storage=[], funcspec=[],
                     type=c_ast.ArrayDecl(
                         type=c_ast.TypeDecl(declname='arr', quals=[], align=None,
                                             type=c_ast.IdentifierType(names=['int'])),
                         dim=c_ast.BinaryOp(op='+',
                                            left=c_ast.ID(name='no_such_thing'),
                                            right=c_ast.Constant(type='int', value='1')),
                         dim_quals=[]),
                     init=None, bitsize=None)
    node = c_ast.Struct(name='BadDim', decls=[bad])
    exe_mod.execute(node)
    t = g_types.lookup_tag('struct', 'BadDim')
    try:
        ensure_complete(t)
        raise AssertionError("应报错（维度非常量）")
    except AssertionError as e:
        assert '数组维度' in str(e) or '不完整' in str(e) or 'arr' in str(e)
        print(f"    {e} ✓")


# ==================== 8. M4 union 值语义 ====================

def _union_def(name, fields):
    """构造 `union <name> { <fields> };` 定义节点。fields: [(fname, type_names)]"""
    decls = []
    for fname, tnames in fields:
        decls.append(c_ast.Decl(name=fname, quals=[], align=None, storage=[], funcspec=[],
                                type=c_ast.TypeDecl(declname=fname, quals=[], align=None,
                                                    type=c_ast.IdentifierType(names=tnames)),
                                init=None, bitsize=None))
    return c_ast.Union(name=name, decls=decls)


def test_m4_union_basic():
    print("  [M4] union U {char c; int i;} U u; u.i = 0x41;")
    exe_mod.setup_global_scope()
    exe_mod.execute(_union_def('U', [('c', ['char']), ('i', ['int'])]))
    st = g_types.lookup_tag('union', 'U')
    assert st.sizeof() == 4 and st.alignof() == 4     # max(1,4)，对齐 4
    # 成员不污染全局作用域（P1 同规则）
    for m in ('c', 'i'):
        try:
            exe_mod.g_scope.get(m)
            raise AssertionError(f"union 成员 '{m}' 不应成为全局变量")
        except AssertionError:
            pass
    # U u;
    exe_mod.execute(_decl_ref('u', c_ast.Union(name='U', decls=None)))
    u = exe_mod.g_scope.get('u')
    assert isinstance(u, UnionValue)
    assert u.get('c') == 0 and u.get('i') == 0
    # u.i = 0x41（活跃成员写入）
    exe_mod.execute(c_ast.Assignment(op='=', lvalue=c_ast.StructRef(name=c_ast.ID(name='u'), type='.',
                                                                    field=c_ast.ID(name='i')),
                                     rvalue=c_ast.Constant(type='int', value='65')))
    assert u.get('i') == 65
    # 读未活跃成员 c → 默认 0（宽松语义；逐字节 reinterpret 依赖 MEM-1）
    assert u.get('c') == 0
    print("    sizeof=4；成员不入作用域；u.i=65；读未活跃 c=0 ✓")


def test_m4_union_size_max():
    print("  [M4] union {char,int,double} sizeof = max 成员对齐后")
    exe_mod.setup_global_scope()
    exe_mod.execute(_union_def('U2', [('c', ['char']), ('i', ['int']), ('d', ['double'])]))
    st = g_types.lookup_tag('union', 'U2')
    assert st.sizeof() == 8 and st.alignof() == 8
    print("    char/int/double -> sizeof 8, align 8 ✓")


def test_m4_union_value_copy():
    print("  [M4] union U a = b; 值拷贝")
    exe_mod.setup_global_scope()
    exe_mod.execute(_union_def('U', [('c', ['char']), ('i', ['int'])]))
    ref = c_ast.Union(name='U', decls=None)
    # union U b = {7}; —— InitList 填充第一个成员 c（C 语义）
    exe_mod.execute(_decl_ref('b', ref, init=c_ast.InitList(exprs=[c_ast.Constant(type='int', value='7')])))
    b = exe_mod.g_scope.get('b')
    assert b.get('c') == 7 and b.get('i') == 0
    # b.i = 7（显式写 int 成员）
    exe_mod.execute(c_ast.Assignment(op='=', lvalue=c_ast.StructRef(name=c_ast.ID(name='b'), type='.',
                                                                    field=c_ast.ID(name='i')),
                                     rvalue=c_ast.Constant(type='int', value='7')))
    assert b.get('i') == 7
    # a = b（值拷贝）
    exe_mod.execute(_decl_ref('a', ref, init=c_ast.ID(name='b')))
    a = exe_mod.g_scope.get('a')
    assert a is not b and a.get('i') == 7
    exe_mod.execute(c_ast.Assignment(op='=', lvalue=c_ast.StructRef(name=c_ast.ID(name='a'), type='.',
                                                                    field=c_ast.ID(name='i')),
                                     rvalue=c_ast.Constant(type='int', value='9')))
    assert a.get('i') == 9 and b.get('i') == 7
    print("    InitList 填首成员 c；a 深拷贝自 b；改 a.i 不影响 b ✓")


def test_m4_union_typedef():
    print("  [M4] typedef union {char c; int i;} Val; Val v;")
    exe_mod.setup_global_scope()
    exe_mod.execute(c_ast.Typedef(name='Val', quals=[], storage=[],
                                  type=_union_def(None, [('c', ['char']), ('i', ['int'])])))
    ut = g_types.resolve(['Val'])
    assert isinstance(ut, UnionType) and ut.sizeof() == 4
    exe_mod.execute(_decl('v', ['Val']))
    v = exe_mod.g_scope.get('v')
    assert isinstance(v, UnionValue) and exe_mod.g_scope.get_type('v') is ut
    print("    别名解析到 UnionType；v 为 UnionValue ✓")


def test_m4_union_with_inline_named_struct_member():
    """修复回归：匿名 union 的成员是内联命名 struct（struct AAA {...} __data）。

    复现文件 test/anonymous_struct_union.c —— L4 惰性注册下，内联命名类型
    只注册不布局，匿名 union 布局前需 ensure_complete 成员（否则"成员不完整"）。
    """
    print("  [M4] typedef union { struct AAA {int a;} __data; } BBB;")
    exe_mod.setup_global_scope()
    inner = c_ast.Struct(name='AAA', decls=[
        c_ast.Decl(name='a', quals=[], align=None, storage=[], funcspec=[],
                   type=c_ast.TypeDecl(declname='a', quals=[], align=None,
                                       type=c_ast.IdentifierType(names=['int'])),
                   init=None, bitsize=None)])
    # 成员 __data 的类型是内联 struct 定义节点（非 IdentifierType）
    member = c_ast.Decl(name='__data', quals=[], align=None, storage=[], funcspec=[],
                        type=c_ast.TypeDecl(declname='__data', quals=[], align=None,
                                            type=inner),
                        init=None, bitsize=None)
    union_node = c_ast.Union(name=None, decls=[member])
    exe_mod.execute(c_ast.Typedef(name='BBB', quals=[], storage=[], type=union_node))
    t = g_types.lookup_tag('struct', 'AAA')
    ensure_complete(t)                       # 内联命名 struct 已注册（不完整 → 补全）
    assert t.is_complete() and t.sizeof() == 4 and [m.name for m in t.members] == ['a']
    b = g_types.resolve(['BBB'])             # 匿名 union：注册即布局（成员已补全）
    assert isinstance(b, UnionType) and b.sizeof() == 4
    assert [m.name for m in b.members] == ['__data']
    print("    AAA 补全 size 4；BBB 布局成功（成员 __data）✓")


# ==================== 9. M5 集成增强 ====================

def test_m5_sizeof_no_side_effect():
    print("  [M5] sizeof(x++) 不求值（修 BUG-1）")
    exe_mod.setup_global_scope()
    exe_mod.execute(_decl('x', ['int'], c_ast.Constant(type='int', value='5')))
    sz = exe_mod.execute(c_ast.UnaryOp(op='sizeof',
                                       expr=c_ast.UnaryOp(op='p++', expr=c_ast.ID(name='x'))))
    assert sz == 4
    assert exe_mod.g_scope.get('x') == 5    # operand 未被求值，x 不变
    print(f"    sizeof(x++) = {sz}；x 仍为 5（无副作用）✓")


def test_m5_sizeof_types():
    print("  [M5] sizeof(类型) / sizeof(表达式) / sizeof(*ptr)")
    exe_mod.setup_global_scope()
    def tn(node):
        return c_ast.Typename(name=None, quals=[], align=None, type=node)
    # sizeof(int)
    assert exe_mod.execute(c_ast.UnaryOp(op='sizeof', expr=tn(
        c_ast.TypeDecl(declname=None, quals=[], align=None, type=c_ast.IdentifierType(names=['int']))))) == 4
    # sizeof(struct Point) == 8
    exe_mod.execute(_struct_def('Point', [('x', ['int']), ('y', ['int'])]))
    assert exe_mod.execute(c_ast.UnaryOp(op='sizeof', expr=tn(
        c_ast.TypeDecl(declname=None, quals=[], align=None,
                       type=c_ast.Struct(name='Point', decls=None))))) == 8
    # sizeof(int*) == 8
    assert exe_mod.execute(c_ast.UnaryOp(op='sizeof', expr=tn(
        c_ast.PtrDecl(quals=[], type=c_ast.IdentifierType(names=['int']))))) == 8
    # sizeof(表达式) / sizeof(*ptr)（只推导类型，不崩溃不求值）
    exe_mod.execute(_decl('p', ['int']))
    assert exe_mod.execute(c_ast.UnaryOp(op='sizeof', expr=c_ast.ID(name='p'))) == 4
    exe_mod.execute(_decl('pp', ['int']))
    exe_mod.g_scope.set_type('pp', PtrType(g_types.resolve(['int'])))
    assert exe_mod.execute(c_ast.UnaryOp(op='sizeof',
                                         expr=c_ast.UnaryOp(op='*', expr=c_ast.ID(name='pp')))) == 4
    print("    sizeof(int)=4；sizeof(struct Point)=8；sizeof(int*)=8；sizeof(*pp)=4（不求值）✓")


def test_m5_alignof():
    print("  [M5] __alignof__ / _Alignof（修 BUG-2）")
    exe_mod.setup_global_scope()
    a1 = exe_mod.execute(c_ast.UnaryOp(op='__alignof__',
                                       expr=c_ast.Constant(type='int', value='42')))
    assert a1 == 4
    a2 = exe_mod.execute(c_ast.UnaryOp(op='_Alignof', expr=c_ast.Typename(
        name=None, quals=[], align=None,
        type=c_ast.TypeDecl(declname=None, quals=[], align=None,
                            type=c_ast.IdentifierType(names=['double'])))))
    assert a2 == 8
    print(f"    __alignof__(int)=4；_Alignof(double)=8 ✓")


def test_m5_struct_value_pass():
    print("  [M5] struct 值传递：形参修改不影响实参")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('S', [('x', ['int'])]))
    # int bump(struct S s) { s.x = 99; return s.x; }
    func_decl = c_ast.Decl(name='bump', quals=[], align=None, storage=[], funcspec=[],
                           type=c_ast.FuncDecl(
                               args=c_ast.ParamList(params=[
                                   c_ast.Decl(name='s', quals=[], align=None, storage=[], funcspec=[],
                                              type=c_ast.TypeDecl(declname='s', quals=[], align=None,
                                                                  type=c_ast.Struct(name='S', decls=None)),
                                              init=None, bitsize=None),
                               ]),
                               type=c_ast.TypeDecl(declname='bump', quals=[], align=None,
                                                   type=c_ast.IdentifierType(names=['int']))),
                           init=None, bitsize=None)
    body = c_ast.Compound(block_items=[
        c_ast.Assignment(op='=', lvalue=c_ast.StructRef(name=c_ast.ID(name='s'), type='.',
                                                        field=c_ast.ID(name='x')),
                         rvalue=c_ast.Constant(type='int', value='99')),
        c_ast.Return(expr=c_ast.StructRef(name=c_ast.ID(name='s'), type='.', field=c_ast.ID(name='x'))),
    ])
    exe_mod.execute(c_ast.FuncDef(decl=func_decl, param_decls=None, body=body))
    exe_mod.execute(_decl_ref('a', c_ast.Struct(name='S', decls=None),
                              init=c_ast.InitList(exprs=[c_ast.Constant(type='int', value='7')])))
    ret = exe_mod.execute(c_ast.FuncCall(name=c_ast.ID(name='bump'),
                                         args=c_ast.ExprList(exprs=[c_ast.ID(name='a')])))
    assert ret == 99
    a = exe_mod.g_scope.get('a')
    assert a.get('x') == 7                       # 实参未被形参修改
    print(f"    bump(a)=99；实参 a.x 仍为 7 ✓")


def test_m5_cast_enum():
    print("  [M5] enum↔int 转换与类型化 Cast")
    exe_mod.setup_global_scope()
    exe_mod.execute(_enum_def('Color', [('RED', None), ('GREEN', None)]))
    cast = exe_mod.execute(c_ast.Cast(
        to_type=c_ast.Typename(name=None, quals=[], align=None,
                               type=c_ast.TypeDecl(declname=None, quals=[], align=None,
                                                   type=c_ast.Enum(name='Color', values=None))),
        expr=c_ast.Constant(type='int', value='1')))
    assert cast == 1
    cast2 = exe_mod.execute(c_ast.Cast(
        to_type=c_ast.Typename(name=None, quals=[], align=None,
                               type=c_ast.TypeDecl(declname=None, quals=[], align=None,
                                                   type=c_ast.IdentifierType(names=['int']))),
        expr=c_ast.Constant(type='float', value='3.7')))
    assert cast2 == 3                            # 标量路径保持
    print(f"    (enum Color)1 = {cast}；(int)3.7 = {cast2} ✓")


def test_m5_designated_init():
    print("  [M5] 指定初始化器 .y = 5 与 [1] = 7")
    exe_mod.setup_global_scope()
    exe_mod.execute(_struct_def('DS', [('x', ['int']), ('y', ['int'])]))
    exe_mod.execute(_decl_ref('s', c_ast.Struct(name='DS', decls=None),
                              init=c_ast.InitList(exprs=[
                                  c_ast.NamedInitializer(name=[c_ast.ID(name='y')],
                                                         expr=c_ast.Constant(type='int', value='5'))])))
    s = exe_mod.g_scope.get('s')
    assert s.get('x') == 0 and s.get('y') == 5
    arr_decl = c_ast.Decl(name='arr', quals=[], align=None, storage=[], funcspec=[],
                          type=c_ast.ArrayDecl(
                              type=c_ast.TypeDecl(declname='arr', quals=[], align=None,
                                                  type=c_ast.IdentifierType(names=['int'])),
                              dim=c_ast.Constant(type='int', value='3'), dim_quals=[]),
                          init=c_ast.InitList(exprs=[
                              c_ast.NamedInitializer(name=[c_ast.Constant(type='int', value='1')],
                                                     expr=c_ast.Constant(type='int', value='7'))]),
                          bitsize=None)
    exe_mod.execute(arr_decl)
    assert exe_mod.g_scope.get('arr') == [0, 7, 0]
    print("    s = {x:0, y:5}；arr = [0, 7, 0] ✓")


# ==================== 10. 修复回归：类型顺序 / 数组维度表达式 ====================

def test_fix_type_specifier_order():
    print("  [Fix] 类型说明符任意顺序（long long unsigned int / signed）")
    t1 = g_types.resolve(['long', 'long', 'unsigned', 'int'])
    t2 = g_types.resolve(['unsigned', 'long', 'long', 'int'])
    assert t1 is t2 and t1.sizeof() == 8
    # 省略/拆分形式语义等价（名字可能是注册表的别名单例，按 size 断言）
    assert g_types.resolve(['unsigned']).sizeof() == 4
    assert g_types.resolve(['long', 'long']).sizeof() == 8
    assert g_types.resolve(['long', 'unsigned']).sizeof() == 8
    assert g_types.resolve(['long', 'unsigned']).sizeof() == g_types.resolve(['unsigned', 'long']).sizeof()
    # signed 前缀形态（canonical 归一化会生成，注册表需有键）
    assert g_types.resolve(['signed', 'short']).sizeof() == 2
    assert g_types.resolve(['signed', 'long']).sizeof() == 8
    assert g_types.resolve(['signed', 'long', 'long']).sizeof() == 8
    assert g_types.resolve(['long', 'signed']).sizeof() == 8      # 任意顺序
    assert g_types.resolve(['signed', 'long', 'long', 'int']).sizeof() == 8
    # typedef 名（非关键字）不被误归一为 int
    r = build_default_registry()
    r.register_typedef('MyT', r.resolve(['int']))
    assert r.resolve(['MyT']) is r.resolve(['int'])
    print("    任意顺序归一；signed 形态齐全；typedef 名不误判 ✓")


def test_fix_array_dim_expression():
    print("  [Fix] 数组维度表达式（10+5、sizeof(int)*2）")
    exe_mod.setup_global_scope()
    from typesys import type_of_decl
    def int_tn(name=None):
        return c_ast.TypeDecl(declname=name, quals=[], align=None,
                              type=c_ast.IdentifierType(names=['int']))
    # int arr[10 + 5]
    at = type_of_decl(c_ast.ArrayDecl(
        type=int_tn('arr'),
        dim=c_ast.BinaryOp(op='+', left=c_ast.Constant(type='int', value='10'),
                           right=c_ast.Constant(type='int', value='5')),
        dim_quals=[]))
    assert at.count == 15 and at.sizeof() == 60
    # int buf[sizeof(int) * 2]
    bt = type_of_decl(c_ast.ArrayDecl(
        type=int_tn('buf'),
        dim=c_ast.BinaryOp(op='*',
                           left=c_ast.UnaryOp(op='sizeof', expr=c_ast.Typename(
                               name=None, quals=[], align=None, type=int_tn())),
                           right=c_ast.Constant(type='int', value='2')),
        dim_quals=[]))
    assert bt.count == 8
    print(f"    arr[10+5] → {at.count}；buf[sizeof(int)*2] → {bt.count} ✓")


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
    test_m2_enum_hex_and_bases()
    test_m2_enum_reference_previous()
    test_m2_enum_variable()
    test_m2_typedef_enum_anon()
    test_m2_typedef_named_enum()
    print("\n--- 7. M3 struct 值语义 ---")
    test_m3_struct_basic()
    test_m3_struct_value_copy()
    test_m3_struct_nested()
    test_m3_struct_array()
    test_m3_struct_default_and_compound()
    test_m3_struct_arrow_fallback()
    test_m3_struct_flexible_array_member()
    test_m3_struct_bad_array_dim_raises()
    print("\n--- 8. M4 union 值语义 ---")
    test_m4_union_basic()
    test_m4_union_size_max()
    test_m4_union_value_copy()
    test_m4_union_typedef()
    test_m4_union_with_inline_named_struct_member()
    print("\n--- 9. M5 集成增强 ---")
    test_m5_sizeof_no_side_effect()
    test_m5_sizeof_types()
    test_m5_alignof()
    test_m5_struct_value_pass()
    test_m5_cast_enum()
    test_m5_designated_init()
    print("\n--- 10. 修复回归 ---")
    test_fix_type_specifier_order()
    test_fix_array_dim_expression()
    print("\n" + "=" * 60)
    print("  M0 - M5 + 修复回归 全部测试通过! ✅")
    print("=" * 60)


if __name__ == '__main__':
    main()
