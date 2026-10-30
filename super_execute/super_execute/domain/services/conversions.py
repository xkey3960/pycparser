"""整型提升与寻常算术转换（C99 6.3.1）。

为什么需要它：`char + int` 的结果是 `int`，`1 / 2` 是**整型除法**（0 而不是 0.5），
而 `p + 1` 的步长又必须取指针目标的大小。这些判断都得先知道"运算结果的类型"。

简化（记录在案）：

* 只覆盖本项目的类型范围（无 ``long double``、无复数）；
* 同宽不同符号时取无符号那一边——C 的规则更细（看能否表示全部值），
  但在 LLP64 下同宽的只有 ``int/unsigned int`` 与 ``long/unsigned long``，
  这个简化不会改变本项目能跑的程序的结果。
* **值**不做宽度截断（Phase A 用 Python 整数），只有类型层面按这里走；
  Phase B 换成字节存储后截断自然发生。
"""

from __future__ import annotations

from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    EnumType,
    PointerType,
)
from super_execute.domain.exceptions import InvalidTypeError
from super_execute.domain.services.builtin_types import DOUBLE, FLOAT, INT


def array_to_pointer(ctype: CType) -> CType:
    """数组在多数表达式里退化成指向首元素的指针（C99 6.3.2.1）。

    两个地方要用：函数形参（``int f(int a[3])`` 实际上是 ``int *``），
    以及拿数组名当值用（``int *p = a;``）。
    """
    if isinstance(ctype, ArrayType):
        return PointerType(ctype.element)
    return ctype


def integer_promote(ctype: CType) -> CType:
    """比 int 窄的整型提升为 int（``char``、``short``、``_Bool``）。

    枚举也在这里提升：C 说枚举常量是 int，枚举类型的值参与算术时同样按 int 处理
    （C99 6.7.2.2p3）。少了这一条，`enum E e; e + 1` 会被判成非法运算。
    """
    if isinstance(ctype, EnumType):
        return INT
    if isinstance(ctype, BasicType) and ctype.is_complete and not ctype.is_float:
        if ctype.sizeof() < INT.sizeof():
            return INT
    return ctype


def usual_arithmetic_convert(left: CType, right: CType) -> CType:
    """两个算术类型做运算后的结果类型。"""
    left = integer_promote(left)
    right = integer_promote(right)

    if not isinstance(left, BasicType) or not isinstance(right, BasicType):
        raise InvalidTypeError(
            f"算术转换只支持基础类型，收到 {left.name} 与 {right.name}"
        )

    if left.is_float or right.is_float:
        if not (left.is_float and right.is_float):
            # 一边是浮点：另一边是整形，取浮点那一边
            return left if left.is_float else right
        return (
            DOUBLE if max(left.sizeof(), right.sizeof()) >= DOUBLE.sizeof() else FLOAT
        )

    if left.sizeof() != right.sizeof():
        return left if left.sizeof() > right.sizeof() else right

    # 同宽：有符号那边要让位
    if not left.is_signed:
        return left
    if not right.is_signed:
        return right
    return left
