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

from typing import Any

from super_execute.domain.entities.c_types import (
    ArrayType,
    BasicType,
    CType,
    EnumType,
    PointerType,
)
from super_execute.domain.exceptions import InvalidTypeError
from super_execute.domain.services.builtin_types import DOUBLE, FLOAT, INT
from super_execute.domain.value_objects import NULL_ADDRESS, Address


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


def convert_value(value: Any, ctype: CType) -> Any:
    """把值转成 ``ctype`` 应该存的样子（赋值 / 初始化 / 传参 / 返回共用）。

    C 里几乎每一处"值流入某个类型"的地方都会做隐式转换，最容易漏的是这三处：

        int x = 3.7;      → 3    （浮点转整型向零截断）
        int f(void){ return 3.7; }   → 3
        int y = 5; y += 2.7;         → 7（先算 7.7 再转回 int）

    本项目 Phase A 用 Python 整数存值，所以**窄化截断没有做**（`char c = 300`
    不会回绕成 44）——那是 Phase B 换成字节存储之后自然发生的事。这里只处理
    浮点↔整型、整数↔指针（0 变 NULL）、以及枚举按 int 存。
    """
    if isinstance(ctype, BasicType):
        if not ctype.is_complete:  # void
            return None
        if isinstance(value, Address):
            return float(value.packed) if ctype.is_float else value.packed
        return float(value) if ctype.is_float else int(value)

    if isinstance(ctype, EnumType):
        return int(value)

    if isinstance(ctype, PointerType):
        if isinstance(value, Address):
            return value
        if value in (0, None):
            return NULL_ADDRESS  # 整数 0 就是空指针
        if isinstance(value, (int, float)):
            return value  # 其它整数当地址用（不常见，但 C 允许）

    # 复合值（struct/union/array）按值传递，转换没有额外动作（拷贝在写入时做）
    return value
