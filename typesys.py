#!/usr/bin/python
"""typesys.py — C 类型系统基础设施（M0）

把 execute.py 的"无类型解释器"升级为"带类型解释器"的地基层：

- CType 层次：BasicType / PtrType / ArrayType / FuncType / EnumType / StructType / UnionType
- TypeRegistry：内建类型注册、struct/union/enum 标签命名空间、typedef 别名（链式解析 + 环检测）
- 布局工具：align_up / compute_struct_layout / compute_union_layout
- Scope 升级（Symbol 存储）在 execute.py 中完成，本模块不依赖 execute.py

设计依据：19.work-space/pycparser/设计文档-类型系统支持.md §2.2 ~ §2.4、§3.1（M0）
"""

from __future__ import annotations

from collections import namedtuple
from typing import Dict, List, Optional, Tuple

# ==================== 平台常量（64 位常见 ABI） ====================

POINTER_SIZE = 8
POINTER_ALIGN = 8

# ==================== CType 层次 ====================


class CType:
    """类型基类。size/align 为 None 表示不完整类型或 sizeof 非法（函数类型）。"""

    __slots__ = ("name", "size", "align")

    def __init__(self, name, size=None, align=None):
        self.name = name
        self.size = size
        self.align = align

    def sizeof(self):
        ensure_complete(self)   # L4：struct/union 首次需要尺寸时补全布局
        if self.size is None:
            raise AssertionError(f"类型 '{self.name}' 的 sizeof 未定义（不完整类型或函数类型）")
        return self.size

    def alignof(self):
        ensure_complete(self)   # L4：同上，首次需要对齐时补全布局
        if self.align is None:
            raise AssertionError(f"类型 '{self.name}' 的 align 未定义")
        return self.align

    def is_complete(self):
        return self.size is not None

    def __repr__(self):
        return f"<{self.__class__.__name__} {self.name} size={self.size} align={self.align}>"


class BasicType(CType):
    """基本标量类型（int/char/float/double/bool/void 等）。"""

    __slots__ = ()

    def __init__(self, name, size, align):
        super().__init__(name, size, align)


class PtrType(CType):
    """指针类型：size/align 固定为平台指针大小。"""

    __slots__ = ("points_to",)

    def __init__(self, points_to):
        super().__init__(f"{points_to.name} *", POINTER_SIZE, POINTER_ALIGN)
        self.points_to = points_to


class ArrayType(CType):
    """数组类型。count=None 表示不完整数组（int a[]），sizeof 未定义。"""

    __slots__ = ("elem_type", "count")

    def __init__(self, elem_type, count=None):
        size = elem_type.size * count if (count is not None and elem_type.size is not None) else None
        align = elem_type.align
        name = f"{elem_type.name}[{count if count is not None else ''}]"
        super().__init__(name, size, align)
        self.elem_type = elem_type
        self.count = count


class FuncType(CType):
    """函数类型：sizeof 在 C 中非法（size=None），但类型本身是完整的。"""

    __slots__ = ("ret_type", "param_types", "variadic")

    def __init__(self, ret_type, param_types=None, variadic=False):
        super().__init__(f"{ret_type.name} ()", None, None)
        self.ret_type = ret_type
        self.param_types = param_types or []
        self.variadic = variadic

    def is_complete(self):
        return True


class EnumType(CType):
    """枚举类型：size=4/align=4（64 位 ABI），携带枚举常量表 name -> int。"""

    __slots__ = ("constants",)

    def __init__(self, name, constants=None):
        super().__init__(name, 4, 4)
        self.constants = constants or {}


Member = namedtuple("Member", ["name", "type", "offset", "bitsize"])


class StructType(CType):
    """结构体类型。members 为 Member(name, type, offset, bitsize) 列表。

    前置声明（struct S;）时 incomplete=True，之后用 finalize() 补全布局。
    L4 惰性（可选字段）：
      _deferred — 定义 AST 节点（注册时不布局，首次使用时才补全布局）
      _dupes    — 同标签的后续定义 AST 列表（重定义冲突候选，补全时检测）
    """

    __slots__ = ("members", "_deferred", "_dupes")

    def __init__(self, name, members=None, size=None, align=None, incomplete=False):
        super().__init__(name, size, align)
        self.members = members or []
        self._deferred = None
        self._dupes = []
        if incomplete:
            self.size = None
            self.align = None

    def finalize(self, members, size, align):
        """前置声明后补全定义：填入成员并更新布局。"""
        self.members = members
        self.size = size
        self.align = align

    def member_offset(self, name):
        ensure_complete(self)   # L4：成员访问前补全布局（可能激活定义文件）
        for m in self.members:
            if m.name == name:
                return m.offset
        raise AssertionError(f"struct {self.name} 无成员 '{name}'")

    def member_type(self, name):
        ensure_complete(self)
        for m in self.members:
            if m.name == name:
                return m.type
        raise AssertionError(f"struct {self.name} 无成员 '{name}'")


class UnionType(CType):
    """联合体类型：所有成员 offset=0（共享存储），size=max 成员。

    L4 惰性字段同 StructType（_deferred/_dupes，见上）。
    """

    __slots__ = ("members", "_deferred", "_dupes")

    def __init__(self, name, members=None, size=None, align=None, incomplete=False):
        super().__init__(name, size, align)
        self.members = members or []
        self._deferred = None
        self._dupes = []
        if incomplete:
            self.size = None
            self.align = None

    def finalize(self, members, size, align):
        self.members = members
        self.size = size
        self.align = align

    def member_type(self, name):
        ensure_complete(self)   # L4：成员访问前补全布局（可能激活定义文件）
        for m in self.members:
            if m.name == name:
                return m.type
        raise AssertionError(f"union {self.name} 无成员 '{name}'")


# ==================== 布局工具 ====================


def align_up(v, a):
    """向上对齐：v 对齐到 a 的整数倍（a 为 1 时不变）。"""
    if a is None or a <= 1:
        return v
    return (v + a - 1) // a * a


def compute_struct_layout(members, align_override=None):
    """计算 struct 布局（C 对齐规则）。

    members: [(name, CType, bitsize_or_None)]，bitsize 非空表示位域。
    返回 (layout, size, align)：
      - layout: [Member(name, type, offset, bitsize)]，offset 按成员对齐逐项推进
      - size:   末尾对齐到 max_align
      - align:  max(成员 align)，可被 align_override（__attribute__((aligned))）覆盖

    C99 灵活数组成员（flexible array member）：最后一个成员、类型为
    不完整数组（int b[]，count=None）→ 不占空间（offset 停在原处），
    sizeof(struct) 不含它；仅限最后一个成员（C 标准）。
    """
    offset, max_align = 0, 1
    layout = []
    for i, (name, ctype, bitsize) in enumerate(members):
        if ctype.size is None:
            # C99 灵活数组成员：不完整数组且是最后一个成员 → 不占空间
            is_flex = (isinstance(ctype, ArrayType) and ctype.count is None
                       and i == len(members) - 1)
            if not is_flex:
                raise AssertionError(f"struct 成员 '{name}' 是不完整类型，无法布局")
            layout.append(Member(name, ctype, offset, bitsize))
            continue
        # 位域（M3 简化）：先按类型对齐占位，真实打包在 M5
        align = ctype.align or 1
        offset = align_up(offset, align)
        layout.append(Member(name, ctype, offset, bitsize))
        offset += ctype.size
        max_align = max(max_align, align)
    # __attribute__((aligned(N))) 是最小对齐：不能低于自然对齐 max_align
    align = max(align_override or 1, max_align)
    # struct 大小须为对齐值的整数倍（保证数组元素对齐）
    size = align_up(offset, align)
    return layout, size, align


def compute_union_layout(members):
    """计算 union 布局：所有成员 offset=0，size=max 成员（对齐到 max_align）。

    members: [(name, CType, bitsize_or_None)]
    返回 (layout, size, align)。
    """
    size, align = 0, 1
    for name, ctype, bitsize in members:
        if ctype.size is None:
            raise AssertionError(f"union 成员 '{name}' 是不完整类型，无法布局")
        size = max(size, ctype.size)
        align = max(align, ctype.align or 1)
    layout = [Member(name, ctype, 0, bitsize) for name, ctype, bitsize in members]
    return layout, align_up(size, align), align


# ==================== TypeRegistry ====================


class TypeRegistry:
    """类型注册表：内建类型 + 标签命名空间 + typedef 别名。

    命名空间规则（与 C 一致）：
      - 标签命名空间：struct/union/enum 标签，键为 (kind, name)
      - 普通标识符命名空间：变量/函数/typedef 名/枚举常量（由 Scope 与 aliases 管理）
    """

    def __init__(self):
        self.builtins = {}      # 类型名（'int'/'unsigned long'/...）-> BasicType 单例
        self.tags = {}          # (kind, name) -> CType（StructType/UnionType/EnumType）
        self.aliases = {}       # typedef 名 -> CType（解析后的目标类型，不建包装类）

    # ---- 内建 ----

    def register_builtin(self, ctype):
        self.builtins[ctype.name] = ctype

    # ---- 标签命名空间 ----

    def register_tag(self, kind, name, ctype):
        self.tags[(kind, name)] = ctype

    def has_tag(self, kind, name):
        return (kind, name) in self.tags

    def lookup_tag(self, kind, name):
        t = self.tags.get((kind, name))
        if t is None:
            raise AssertionError(f"未定义 {kind} {name}")
        return t

    # ---- typedef 别名 ----

    def register_typedef(self, name, ctype):
        self.aliases[name] = ctype

    def resolve_typedef(self, name, seen=None):
        """链式解析 typedef 别名，返回叶子目标类型；检测循环（A->B->A 报错）。

        注意：`typedef struct Node Node;` 这类"别名与目标类型同名"是合法 C
        （别名 Node -> struct Node），此时 t.name == name，直接返回 t，
        不算循环。
        """
        seen = seen or set()
        if name in seen:
            raise AssertionError(f"typedef 循环: {' -> '.join(list(seen) + [name])}")
        seen.add(name)
        t = self.aliases.get(name)
        if t is None:
            return self.builtins.get(name)  # 叶子：内建类型（或 None=未定义）
        if t.name != name and (t.name in self.aliases or t.name in self.builtins):
            return self.resolve_typedef(t.name, seen)  # 别名指向别名，继续解析
        return t

    # ---- 统一解析：IdentifierType.names -> CType ----

    def resolve(self, names):
        """把 IdentifierType.names（如 ['int'] / ['unsigned','long'] / ['enum','Color']
        / ['MyType']）解析为 CType。

        顺序：struct/union/enum 标签 → 内建（拼接名）→ typedef（单名，可链式）。
        """
        if not names:
            raise AssertionError("空类型名")
        lowered = [n.lower() for n in names]
        if lowered[0] in ("struct", "union", "enum"):
            if len(names) < 2:
                raise AssertionError(f"类型 '{lowered[0]}' 缺少标签名")
            # 标签名大小写敏感（C 语义），保留原文；kind 关键字宽松小写
            return self.lookup_tag(lowered[0], names[1])
        joined = " ".join(lowered)
        if joined in self.builtins:
            return self.builtins[joined]
        # 任意顺序的类型说明符（long long unsigned int 等）——仅当含类型关键字时才规范化，
        # 避免把 typedef 名（如 'S'）误归一为 'int'
        canonical = canonical_type_name(names)
        if canonical is not None and canonical in self.builtins:
            return self.builtins[canonical]
        if len(names) == 1:
            t = self.resolve_typedef(names[0])
            if t is not None:
                return t
        raise AssertionError(f"未定义类型: '{joined}'")


_SPEC_KEYWORDS = frozenset({
    'signed', 'unsigned', 'short', 'long',
    'char', 'int', 'float', 'double', 'void', '_bool', 'bool',
})


def canonical_type_name(names):
    """把任意顺序/省略形式的类型说明符归一化为规范名（C 语义）。

    类型说明符 = [signed|unsigned] + [short|long(long)] + [基础类型(可省略, int 隐含)]，
    顺序任意。例如：
      'long long unsigned int' → 'unsigned long long int'
      'unsigned'              → 'unsigned int'
      'long long'             → 'long long int'
      'long unsigned'         → 'unsigned long int'

    若 names 中不含任何类型关键字（如 typedef 名 'S'），返回 None（不应规范化）。
    """
    lowered = [n.lower() for n in names]
    if not any(n in _SPEC_KEYWORDS for n in lowered):
        return None
    counts = {}
    for n in lowered:
        counts[n] = counts.get(n, 0) + 1
    sign = 'unsigned' if counts.get('unsigned') else ('signed' if counts.get('signed') else '')
    short_n = 1 if counts.get('short') else 0
    long_n = min(counts.get('long', 0), 2)       # C 最多 long long
    base = None
    for b in ('char', 'float', 'double', 'void', '_bool', 'bool', 'int'):
        if counts.get(b):
            base = b
            break
    if base is None:
        base = 'int'
    parts = []
    if sign:
        parts.append(sign)
    if short_n:
        parts.append('short')
    parts.extend(['long'] * long_n)
    parts.append(base)
    return ' '.join(parts)


# ==================== 默认注册表（内建类型） ====================


def build_default_registry():
    """构建带内建类型注册的 TypeRegistry（64 位 ABI 尺寸）。"""
    reg = TypeRegistry()
    for name, size, align in [
        # 整型
        ("char", 1, 1), ("signed char", 1, 1), ("unsigned char", 1, 1),
        ("short", 2, 2), ("signed short int", 2, 2), ("short int", 2, 2), ("unsigned short", 2, 2),
        ("unsigned short int", 2, 2),
        ("int", 4, 4), ("signed", 4, 4), ("signed int", 4, 4),
        ("unsigned", 4, 4), ("unsigned int", 4, 4),
        ("long", 8, 8), ("signed long int", 8, 8), ("long int", 8, 8), ("unsigned long", 8, 8),
        ("unsigned long int", 8, 8),
        ("long long", 8, 8), ("long long int", 8, 8),
        ("signed long long", 8, 8), ("signed long long int", 8, 8),
        ("unsigned long long", 8, 8), ("unsigned long long int", 8, 8),
        # 浮点
        ("float", 4, 4), ("double", 8, 8), ("long double", 16, 16),
        # 布尔 / void
        ("_Bool", 1, 1), ("bool", 1, 1), ("void", 1, 1),
    ]:
        reg.register_builtin(BasicType(name, size, align))
    return reg


# 全局默认注册表（execute.py 及执行器共用）
g_types = build_default_registry()

# ==================== AST → CType（声明类型解析，M1） ====================

from pycparser import c_ast
from pycparserext.ext_c_parser import FuncDeclExt

# L2 惰性类型解析：引用未注册类型时按需装载定义文件
from sources import g_source_index


def _eval_constant(node):
    """常量表达式求值（数组维度等编译期上下文）。

    直接 Constant → int；否则延迟导入 execute() 求值（可处理 sizeof、算术等
    编译期常量表达式）。求值失败/非常量返回 None（按不完整数组处理）。
    延迟导入避免 typesys ↔ execute 循环依赖。
    """
    if node is None:
        return None
    if isinstance(node, c_ast.Constant):
        try:
            return int(node.value)
        except ValueError:
            return None
    try:
        from execute import execute
        val = execute(node)
        if isinstance(val, int):
            return val
    except AssertionError:
        pass
    return None


def type_of_decl(t):
    """把声明类型 AST 节点解析为 CType（设计文档 §2.9.1）。

    t: pycparser 类型节点（Decl.type / Typedef.type / Cast.to_type 等）。
    支持：TypeDecl（含 TypeDeclExt）、PtrDecl、ArrayDecl（含 ArrayDeclExt）、
    FuncDecl（含 FuncDeclExt）、IdentifierType（typedef 链/内建/标签）、
    内联 Struct/Union/Enum 定义或引用。
    """
    if t is None:
        return g_types.resolve(["int"])  # 兼容现状：缺省 int
    if isinstance(t, c_ast.Typename):            # sizeof(类型) / 转型目标（M5）
        return type_of_decl(t.type)
    if isinstance(t, c_ast.TypeDecl):            # 含 TypeDeclExt
        return type_of_decl(t.type)
    if isinstance(t, c_ast.PtrDecl):
        return PtrType(type_of_decl(t.type))
    if isinstance(t, c_ast.ArrayDecl):           # 含 ArrayDeclExt
        if t.dim is None:
            return ArrayType(type_of_decl(t.type), None)   # 不完整/灵活数组成员 int a[]
        dim = _eval_constant(t.dim)              # 常量/编译期表达式维度（10+5、sizeof(int)*2 等）
        if dim is None:
            raise AssertionError(
                f"数组维度不是常量表达式: {type(t.dim).__name__}")
        return ArrayType(type_of_decl(t.type), dim)
    if isinstance(t, (c_ast.FuncDecl, FuncDeclExt)):
        param_types, variadic = [], False
        args = getattr(t, "args", None)
        if args is not None and isinstance(args, c_ast.ParamList):
            for p in args.params:
                if isinstance(p, c_ast.Decl):
                    param_types.append(type_of_decl(p.type))
                elif isinstance(p, c_ast.EllipsisParam):
                    variadic = True
        return FuncType(type_of_decl(t.type), param_types, variadic)
    if isinstance(t, c_ast.IdentifierType):
        return _resolve_type_lazy(t.names)
    if isinstance(t, (c_ast.Struct, c_ast.Union, c_ast.Enum)):  # 含 StructExt
        return _register_compound(t)
    raise AssertionError(f"无法解析类型节点: {type(t).__name__}")


def _resolve_type_lazy(names):
    """解析 IdentifierType；未定义 → 触发文件惰性装载后重试（L2）。

    覆盖：typedef 名（Mid）、'enum X'/'struct X'/'union X' 标签引用。
    """
    try:
        return g_types.resolve(names)
    except AssertionError:
        lowered = [n.lower() for n in names]
        if lowered[0] in ('struct', 'union', 'enum') and len(names) >= 2:
            g_source_index.activate_for_type(lowered[0], names[1])
        elif len(names) == 1:
            g_source_index.activate_for_type('id', names[0])   # typedef 名
        return g_types.resolve(names)   # 重试；仍失败则抛原错误


def _register_compound(node):
    """处理内联 Struct/Union/Enum 定义/引用（L4：注册与布局分离）。

    - 定义（decls 非空）：只注册不完整类型标签 + 挂 _deferred AST；
      布局延后到 ensure_complete（首次需要完整类型时）——文件激活不再
      检查成员类型/维度表达式（惰性类型检查，设计文档-惰性解析.md L4）。
    - 引用 / 前置声明（decls 为 None）：注册不完整类型。
    - 匿名定义（name 为 None）：注册即布局（无法按名引用，必须当场完整）。
    - 重定义（同标签多个定义）：首个为 _deferred，其余进 _dupes，补全时检测。
    自引用（struct Node { struct Node *next; }）通过"先注册不完整再补全"解决。
    """
    if isinstance(node, c_ast.Enum):
        return _enum_from_node(node)
    if isinstance(node, c_ast.Union):
        kind, ctor, compute = "union", UnionType, compute_union_layout
    else:                                        # Struct / StructExt
        kind, ctor, compute = "struct", StructType, compute_struct_layout

    name = node.name
    # L2 惰性：引用（decls 为 None）未注册标签 → 装载定义文件后再查
    if name and node.decls is None and not g_types.has_tag(kind, name):
        g_source_index.activate_for_type(kind, name)

    # 匿名定义：无法按名引用，注册即布局（当场必须完整）
    if name is None:
        members = []
        for d in node.decls or []:
            if isinstance(d, c_ast.Decl) and d.name:
                mt = type_of_decl(d.type)
                ensure_complete(mt)          # L4 修复：成员可能是内联命名类型（只注册未布局）
                members.append((d.name, mt, d.bitsize))
        layout, size, align = compute(members)
        return ctor(None, members=layout, size=size, align=align)

    if node.decls is None:
        # 引用 / 前置声明：不完整类型
        if not g_types.has_tag(kind, name):
            st = ctor(name, incomplete=True)
            g_types.register_tag(kind, name, st)
        return g_types.lookup_tag(kind, name)

    # 定义：注册不完整 + 挂 deferred（首个定义）/ _dupes（后续定义）
    if g_types.has_tag(kind, name):
        st = g_types.lookup_tag(kind, name)
        if st.is_complete():
            return st                           # 已被补全（重定义宽松返回）
        if st._deferred is None:
            st._deferred = node                 # 首个定义
        else:
            st._dupes.append(node)              # 重定义候选（补全时检测冲突）
        return st
    st = ctor(name, incomplete=True)
    st._deferred = node
    g_types.register_tag(kind, name, st)
    return st


def _member_names_of_def(node):
    """定义 AST 的成员名列表（重定义冲突比对用）。"""
    if isinstance(node, (c_ast.Struct, c_ast.Union)) and node.decls:
        return [d.name for d in node.decls if isinstance(d, c_ast.Decl) and d.name]
    if isinstance(node, c_ast.Enum) and node.values:
        return [e.name for e in node.values.enumerators or []]
    return []


def _check_tag_redef_conflict(ctype, first, dupe):
    """重定义冲突检测（L4 延后到补全时）：首个定义与后续定义成员签名不同 → 冲突。"""
    from sources import _warn_or_raise
    a, b = _member_names_of_def(first), _member_names_of_def(dupe)
    if a != b:
        kind = 'union' if isinstance(ctype, UnionType) else 'struct'
        _warn_or_raise(f"{kind} '{ctype.name}' 重定义冲突: 成员 {a} vs {b}",
                       g_source_index.strict)


def ensure_complete(ctype):
    """确保类型完整（L4 惰性布局）：struct/union 按需补全布局。

    注册时只存 AST（_deferred）；需要完整类型的位置（sizeof/成员访问/
    声明变量/递归成员）调用本函数才触发布局与重定义冲突检测。
    成员类型解析可能触发其他文件激活（_resolve_type_lazy）或递归补全。
    纯前置声明（无定义）保持不完整（C 语义：sizeof 才报错）。
    """
    if ctype is None or ctype.is_complete():
        return ctype
    if not isinstance(ctype, (StructType, UnionType)):
        return ctype
    node = ctype._deferred
    if node is None:
        return ctype                        # 纯前置声明：无法补全
    # 重定义冲突检测（首次使用时才检）
    for dupe in ctype._dupes:
        _check_tag_redef_conflict(ctype, node, dupe)
    # 布局：成员类型解析（可触发其他文件激活）+ 递归补全
    members = []
    for d in node.decls or []:
        if isinstance(d, c_ast.Decl) and d.name:
            mt = type_of_decl(d.type)
            ensure_complete(mt)
            members.append((d.name, mt, d.bitsize))
    if isinstance(ctype, UnionType):
        layout, size, align = compute_union_layout(members)
    else:
        layout, size, align = compute_struct_layout(members)
    ctype.finalize(layout, size, align)
    ctype._deferred = None
    ctype._dupes = []
    return ctype


def _enum_from_node(node):
    """内联枚举：注册标签 + 返回 EnumType（枚举常量值由 ExeEnum 在 M2 注入）。"""
    # L2 惰性：引用（values 为 None）未注册枚举标签 → 装载定义文件
    if node.name and not g_types.has_tag("enum", node.name) and node.values is None:
        g_source_index.activate_for_type("enum", node.name)
    if node.name and g_types.has_tag("enum", node.name):
        return g_types.lookup_tag("enum", node.name)
    e = EnumType(node.name)
    if node.name:
        g_types.register_tag("enum", node.name, e)
    return e


def default_value_for(ctype):
    """按 CType 生成默认值（设计文档 §2.7.4 的 default_value）。

    M3 范围：标量 / 枚举 / 指针 / 数组 / 结构体（StructValue）/ 联合体（UnionValue）。
    """
    if isinstance(ctype, EnumType):
        return 0
    if isinstance(ctype, PtrType):
        return 0                                # 指针模型（MEM-1）落地前用 0 占位
    if isinstance(ctype, ArrayType):
        n = ctype.count or 0
        return [default_value_for(ctype.elem_type) for _ in range(n)]
    if isinstance(ctype, StructType):
        ensure_complete(ctype)   # L4：声明变量需构造默认值 → 补全布局
        return StructValue(ctype)
    if isinstance(ctype, UnionType):
        ensure_complete(ctype)
        return UnionValue(ctype)
    if isinstance(ctype, BasicType):
        name = ctype.name
        if "float" in name or "double" in name:
            return 0.0
        if name in ("_Bool", "bool"):
            return False
        return 0
    return 0


# ==================== 结构体/联合体值对象（M3） ====================


class StructValue:
    """struct 实例（值语义）：携带类型 + 字段值表。

    - 值拷贝：copy() 深拷贝（memcpy 语义），赋值不共享；
    - 成员访问：get/set 校验成员名（未知成员报错）；
    - 与 dict 区分：是"struct 实例"而非普通映射。
    """

    __slots__ = ("type", "fields")

    def __init__(self, type):
        self.type = type
        self.fields = {}
        for m in type.members or []:
            self.fields[m.name] = default_value_for(m.type)

    def get(self, name):
        if name not in self.fields:
            raise AssertionError(f"struct {self.type.name} 无成员 '{name}'")
        return self.fields[name]

    def set(self, name, value):
        if name not in self.fields:
            raise AssertionError(f"struct {self.type.name} 无成员 '{name}'")
        self.fields[name] = value

    def copy(self):
        new = StructValue(self.type)
        for k, v in self.fields.items():
            new.fields[k] = deep_copy_value(v)
        return new

    def __repr__(self):
        return f"<struct {self.type.name} {self.fields}>"


class UnionValue:
    """union 实例（活跃成员模型）：只记录已写入的成员值。

    读未写入成员返回其默认值（宽松）；逐字节 reinterpret 语义依赖
    内存模型（MEM-1），留待 M5。
    """

    __slots__ = ("type", "fields")

    def __init__(self, type):
        self.type = type
        self.fields = {}
        for m in type.members or []:
            self.fields[m.name] = default_value_for(m.type)

    def get(self, name):
        if name not in self.fields:
            raise AssertionError(f"union {self.type.name} 无成员 '{name}'")
        return self.fields[name]

    def set(self, name, value):
        if name not in self.fields:
            raise AssertionError(f"union {self.type.name} 无成员 '{name}'")
        self.fields[name] = value

    def copy(self):
        new = UnionValue(self.type)
        for k, v in self.fields.items():
            new.fields[k] = deep_copy_value(v)
        return new

    def __repr__(self):
        return f"<union {self.type.name} {self.fields}>"


def deep_copy_value(v):
    """递归深拷贝（struct/union/数组/标量）。"""
    if isinstance(v, (StructValue, UnionValue)):
        return v.copy()
    if isinstance(v, list):
        return [deep_copy_value(x) for x in v]
    if isinstance(v, dict):
        return {k: deep_copy_value(x) for k, x in v.items()}
    return v


def coerce_to_type(value, ctype):
    """把初始化值转换为目标类型（设计文档 §2.7.4 的 coerce_to_type）。

    - StructType：StructValue → copy（值拷贝）；list（InitList）→ 按成员顺序填充；
      dict → 按名填充；其他 → 全默认
    - UnionType：同上（活跃成员模型）
    - ArrayType：list → 校验/截断到维度 + 元素递归转换；其他 → 元素默认值列表
    - 标量/枚举/指针：原样返回（隐式类型转换在 M5 / TYPE-2）
    """
    if isinstance(ctype, StructType):
        ensure_complete(ctype)   # L4：构造实例前补全布局（可能激活定义文件）
        if isinstance(value, StructValue):
            return value.copy()
        sv = StructValue(ctype)
        if isinstance(value, list):
            for i, m in enumerate(ctype.members):
                if i < len(value):
                    sv.set(m.name, coerce_to_type(value[i], m.type))
        elif isinstance(value, dict):
            for k, v in value.items():
                if k in sv.fields:
                    sv.set(k, coerce_to_type(v, ctype.member_type(k)))
        return sv
    if isinstance(ctype, UnionType):
        ensure_complete(ctype)
        if isinstance(value, UnionValue):
            return value.copy()
        uv = UnionValue(ctype)
        if isinstance(value, list):
            for i, m in enumerate(ctype.members):
                if i < len(value):
                    uv.set(m.name, coerce_to_type(value[i], m.type))
        elif isinstance(value, dict):
            for k, v in value.items():
                if k in uv.fields:
                    uv.set(k, coerce_to_type(v, ctype.member_type(k)))
        return uv
    if isinstance(ctype, ArrayType):
        if isinstance(value, list):
            n = ctype.count
            if n is not None:
                elems = [coerce_to_type(v, ctype.elem_type) for v in value[:n]]
                elems += [default_value_for(ctype.elem_type)
                          for _ in range(max(0, n - len(elems)))]
                return elems
            return [coerce_to_type(v, ctype.elem_type) for v in value]
        if isinstance(value, dict):               # 指定初始化器 [idx] = v（M5）
            n = ctype.count or 0
            elems = [default_value_for(ctype.elem_type) for _ in range(n)]
            for k, v in value.items():
                if isinstance(k, int) and 0 <= k < n:
                    elems[k] = coerce_to_type(v, ctype.elem_type)
            return elems
        return [default_value_for(ctype.elem_type)] * (ctype.count or 0)
    return value


# ==================== 结构等价判定（S2 冲突检测） ====================


def types_equivalent(t1, t2):
    """结构等价判定（设计文档-多文件支持.md §3.3）。

    同对象 → True；不同实例按同构比对：BasicType 比 name+size、指针/数组/函数
    递归、enum 比常量表、struct/union 比成员（名 + 递归类型）。

    L4 惰性补充：任一侧是不完整 struct/union（未补全布局，members 空）时，
    无法比成员 → 按标签名判定（同标签名视为同一类型；跨文件同名标签本身
    由补全时的重定义冲突检测负责）。
    """
    if t1 is t2:
        return True
    if isinstance(t1, BasicType) and isinstance(t2, BasicType):
        return t1.name == t2.name and t1.size == t2.size
    if isinstance(t1, PtrType) and isinstance(t2, PtrType):
        return types_equivalent(t1.points_to, t2.points_to)
    if isinstance(t1, ArrayType) and isinstance(t2, ArrayType):
        return t1.count == t2.count and types_equivalent(t1.elem_type, t2.elem_type)
    if isinstance(t1, FuncType) and isinstance(t2, FuncType):
        return (types_equivalent(t1.ret_type, t2.ret_type)
                and len(t1.param_types) == len(t2.param_types)
                and all(types_equivalent(a, b)
                        for a, b in zip(t1.param_types, t2.param_types)))
    if isinstance(t1, EnumType) and isinstance(t2, EnumType):
        return t1.constants == t2.constants
    if isinstance(t1, (StructType, UnionType)) and isinstance(t2, (StructType, UnionType)):
        if type(t1) is not type(t2):
            return False
        if not (t1.is_complete() and t2.is_complete()):
            return t1.name == t2.name   # L4：不完整时按标签名判定
        if len(t1.members) != len(t2.members):
            return False
        return all(a.name == b.name and types_equivalent(a.type, b.type)
                   for a, b in zip(t1.members, t2.members))
    return False
