"""类型等价判断。

用途只有一个：**跨文件重复定义的去重**。

真实项目里同一个结构体/typedef 会出现在多个 `.c` 里（因为头文件内容被各文件
展开）。旧实现对此的处理是"相同就静默去重、不同才报警/报错"，本项目的多文件
测试夹具（`test/multi/lib.c` 与 `main.c`）正是这种写法——两个文件都原样写着
同一份 ``typedef struct Pt { int x; int y; } Pt;``。

所以"两个类型是不是同一个"必须能比较，而且比较必须能处理自引用：

    struct Node { int v; struct Node *next; };

按值递归会无限下去，这里用 ``(id(a), id(b))`` 去重——只关心"这两个对象组成的
这一对是否已经在比了"。
"""

from __future__ import annotations

from typing import Any, Iterable

from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    EnumType,
    FunctionType,
    Member,
    PointerType,
    StructType,
    UnionType,
)


def types_equivalent(left: CType, right: CType) -> bool:
    """两个类型是否结构等价（复合类型按成员递归比，不按身份）。"""
    return _equivalent(left, right, set())


def members_equivalent(
    existing: CType, members: Iterable[Member], seen: set[tuple[int, int]] | None = None
) -> bool:
    """已有复合类型的成员是否与给定成员列表等价（用于跨文件去重）。

    ``seen`` 必须从外面传进来（内部递归时）——否则自引用结构体会在
    "指针 → 结构体 → 成员 → 指针"这一圈里反复重新开始，直到 RecursionError。
    """
    if not isinstance(existing, (StructType, UnionType)) or not existing.is_complete:
        return False
    incoming = tuple(members)
    current = existing.members
    if len(current) != len(incoming):
        return False
    seen = set() if seen is None else seen
    for old, new in zip(current, incoming):
        if old.name != new.name:
            return False
        if not _equivalent(old.ctype, new.ctype, seen):
            return False
    return True


def _equivalent(left: Any, right: Any, seen: set[tuple[int, int]]) -> bool:
    if left is right:
        return True
    if not isinstance(left, CType) or not isinstance(right, CType):
        return False

    pair = (id(left), id(right))
    if pair in seen:
        # 自引用：已经假定这一对相等，继续下去只会绕圈
        return True
    seen.add(pair)

    if isinstance(left, BasicType) and isinstance(right, BasicType):
        return left.name == right.name
    if isinstance(left, PointerType) and isinstance(right, PointerType):
        return _equivalent(left.target, right.target, seen)
    if isinstance(left, ArrayType) and isinstance(right, ArrayType):
        return left.count == right.count and _equivalent(
            left.element, right.element, seen
        )
    if isinstance(left, FunctionType) and isinstance(right, FunctionType):
        if left.variadic != right.variadic:
            return False
        if len(left.param_types) != len(right.param_types):
            return False
        if not _equivalent(left.ret, right.ret, seen):
            return False
        return all(
            _equivalent(a, b, seen) for a, b in zip(left.param_types, right.param_types)
        )
    if isinstance(left, EnumType) and isinstance(right, EnumType):
        return left.tag == right.tag
    if isinstance(left, StructType) and isinstance(right, StructType):
        return members_equivalent(
            left, right.members if right.is_complete else (), seen
        )
    if isinstance(left, UnionType) and isinstance(right, UnionType):
        return members_equivalent(
            left, right.members if right.is_complete else (), seen
        )
    return False
