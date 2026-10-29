"""默认值：一块刚分配的存储里应该有什么。

C 的自动变量是"不确定值"，但解释器不能真的留一个空洞——否则
``struct Point s; s.a = 1;`` 会因为"成员容器还不存在"而失败，
而这段代码在 C 里是完全合法的。

所以这里采用**零初始化**：标量 0、浮点 0.0、指针 NULL、数组逐个元素、
结构体/联合体逐个成员。这与 C 对静态存储期的规则一致，对自动变量则是
往确定性方向做的妥协——记录在案，不是疏漏。

（旧实现里对应的东西是 ``typesys.default_value_for``。）
"""

from __future__ import annotations

from typing import Any

from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    EnumType,
    FunctionType,
    PointerType,
    StructType,
    UnionType,
)
from super_execute.domain.exceptions import InvalidTypeError
from super_execute.domain.value_objects import NULL_ADDRESS


def default_value(ctype: CType) -> Any:
    """按类型造一个零值。"""
    if isinstance(ctype, BasicType):
        return 0.0 if ctype.is_float else 0
    if isinstance(ctype, EnumType):
        return 0
    if isinstance(ctype, PointerType):
        return NULL_ADDRESS
    if isinstance(ctype, ArrayType):
        if ctype.count is None:  # 弹性数组成员：没有静态长度
            return []
        return [default_value(ctype.element) for _ in range(ctype.count)]
    if isinstance(ctype, (StructType, UnionType)):
        if not ctype.is_complete:
            raise InvalidTypeError(f"{ctype.name} 尚未定义，无法给出默认值")
        return {member.name: default_value(member.ctype) for member in ctype.members}
    if isinstance(ctype, FunctionType):
        raise InvalidTypeError("函数类型不能直接持有存储（要用函数指针）")
    raise InvalidTypeError(f"无法为 {ctype.name} 造默认值")
