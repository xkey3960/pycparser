"""地址算术：把"成员""元素"变成"基地址 + 偏移"（裁决 D5）。

这是 C 指针模型里最容易被实现成"符号引用"的地方。旧实现用的是
``Address(('member', 对象, 字段))``—— 地址里直接抱着 Python 对象，
于是既存不进内存，也没法做指针算术。

现在只需要 ``offsetof`` 和 ``sizeof`` 两个数字：

    &s.m  ==  &s + offsetof(m)
    &a[i] ==  &a + i * sizeof(a[0])

于是"取地址"退化成整数加法，``&s.m`` 和 ``&s`` 的差值就是成员偏移——
这正是 C 里 ``container_of`` 那类写法能成立的原因。
"""

from __future__ import annotations

from super_execute.domain.entities.c_types import (
    ArrayType,
    CType,
    StructType,
    UnionType,
)
from super_execute.domain.exceptions import (
    IncompleteTypeError,
    InvalidTypeError,
    OutOfBoundsError,
)
from super_execute.domain.value_objects import Address


def member_address(base: Address, compound: CType, member_name: str) -> Address:
    """``&obj.member``：对象基地址 + 成员偏移。"""
    if not isinstance(compound, (StructType, UnionType)):
        raise InvalidTypeError(f"{compound.name} 不是结构体/联合体，不能取成员地址")
    if not compound.is_complete:
        raise IncompleteTypeError(f"{compound.name} 尚未定义，成员偏移未知")
    offset = compound.offsetof(member_name)  # 成员不存在 → InvalidTypeError
    return base + offset


def element_address(base: Address, array: CType, index: int) -> Address:
    """``&arr[i]``：数组基地址 + i * sizeof(元素)。"""
    if not isinstance(array, ArrayType):
        raise InvalidTypeError(f"{array.name} 不是数组，不能用下标取地址")
    if array.count is None:
        raise IncompleteTypeError(f"{array.name} 缺长度，无法计算元素地址")
    if not isinstance(index, int) or isinstance(index, bool):
        raise InvalidTypeError(f"下标必须是整数，收到 {type(index).__name__}")
    if not 0 <= index < array.count:
        raise OutOfBoundsError(f"下标 {index} 越界（{array.name} 长度 {array.count}）")
    return base + index * array.element.sizeof()
