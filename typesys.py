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
        if self.size is None:
            raise AssertionError(f"类型 '{self.name}' 的 sizeof 未定义（不完整类型或函数类型）")
        return self.size

    def alignof(self):
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
    """

    __slots__ = ("members",)

    def __init__(self, name, members=None, size=None, align=None, incomplete=False):
        super().__init__(name, size, align)
        self.members = members or []
        if incomplete:
            self.size = None
            self.align = None

    def finalize(self, members, size, align):
        """前置声明后补全定义：填入成员并更新布局。"""
        self.members = members
        self.size = size
        self.align = align

    def member_offset(self, name):
        for m in self.members:
            if m.name == name:
                return m.offset
        raise AssertionError(f"struct {self.name} 无成员 '{name}'")

    def member_type(self, name):
        for m in self.members:
            if m.name == name:
                return m.type
        raise AssertionError(f"struct {self.name} 无成员 '{name}'")


class UnionType(CType):
    """联合体类型：所有成员 offset=0（共享存储），size=max 成员。"""

    __slots__ = ("members",)

    def __init__(self, name, members=None, size=None, align=None, incomplete=False):
        super().__init__(name, size, align)
        self.members = members or []
        if incomplete:
            self.size = None
            self.align = None

    def finalize(self, members, size, align):
        self.members = members
        self.size = size
        self.align = align

    def member_type(self, name):
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
    """
    offset, max_align = 0, 1
    layout = []
    for name, ctype, bitsize in members:
        if ctype.size is None:
            raise AssertionError(f"struct 成员 '{name}' 是不完整类型，无法布局")
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
        """链式解析 typedef 别名，返回叶子目标类型；检测循环（A->B->A 报错）。"""
        seen = seen or set()
        if name in seen:
            raise AssertionError(f"typedef 循环: {' -> '.join(list(seen) + [name])}")
        seen.add(name)
        t = self.aliases.get(name)
        if t is None:
            return self.builtins.get(name)  # 叶子：内建类型（或 None=未定义）
        if t.name in self.aliases or t.name in self.builtins:
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
        if len(names) == 1:
            t = self.resolve_typedef(names[0])
            if t is not None:
                return t
        raise AssertionError(f"未定义类型: '{joined}'")


# ==================== 默认注册表（内建类型） ====================


def build_default_registry():
    """构建带内建类型注册的 TypeRegistry（64 位 ABI 尺寸）。"""
    reg = TypeRegistry()
    for name, size, align in [
        # 整型
        ("char", 1, 1), ("signed char", 1, 1), ("unsigned char", 1, 1),
        ("short", 2, 2), ("short int", 2, 2), ("unsigned short", 2, 2),
        ("unsigned short int", 2, 2),
        ("int", 4, 4), ("signed", 4, 4), ("signed int", 4, 4),
        ("unsigned", 4, 4), ("unsigned int", 4, 4),
        ("long", 8, 8), ("long int", 8, 8), ("unsigned long", 8, 8),
        ("unsigned long int", 8, 8),
        ("long long", 8, 8), ("long long int", 8, 8),
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
