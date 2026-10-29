"""领域值对象：地址、命名空间/作用域/符号的分类枚举。

这一层不依赖任何外部库，也不依赖 pycparser——它只描述"C 语言里一个名字、
一个地址到底是什么"。上层（application / adapters / frameworks）都可以用它。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, IntEnum

from super_execute.domain.exceptions import AddressError

# ==================== 编址常量（TASK.md 的 4 字节方案） ====================
#
#   32 位地址 = region(8) | scope_id 或高位偏移(8) | offset(16)
#
#   scope 区：region=0, scope_id=1..255, offset=0..65535   → 每作用域 64 KiB
#   heap 区 ：region=1, scope_id 恒 0,   offset=0..16 MiB-1 → 整块堆 16 MiB
#   function：region=2, scope_id 恒 0,   offset=0..16 MiB-1 → 函数表下标
#
# 后两个区把次高字节并入偏移（D1）：这样堆不会只有 64 KiB，而 scope 区仍然
# 保留 TASK.md 要的"次高字节放 scope id"。region 自己决定剩下的比特怎么解释。

_REGION_SHIFT = 24
_SCOPE_ID_SHIFT = 16

#: 地址宽度（字节）。指针的大小就是它——见 c_types.POINTER_SIZE。
ADDRESS_SIZE = 4

SCOPE_ID_MIN = 1
SCOPE_ID_MAX = 0xFF          # 256 个槽位，0 留给 NULL
_SCOPE_OFFSET_MAX = 0xFFFF   # 64 KiB
_WIDE_OFFSET_MAX = 0xFFFFFF  # 16 MiB


class AddressRegion(IntEnum):
    """地址最高字节：这段地址落在哪个内存区。

    数值与 TASK.md 的编号一致（0=scope / 1=heap / 2=function），
    因为 packed 后的整数要按这个编号拼装。
    """

    SCOPE = 0
    HEAP = 1
    FUNCTION = 2


class NamespaceKind(Enum):
    """C 的命名空间（C99 6.2.3）。这里只建模与本项目相关的两个。

    C 另外还有 label 命名空间与 member 命名空间，但都不参与词法查找：
    label 是块内局部的跳转目标，member 由结构体自己拥有（D4/D5）。
    """

    ORDINARY = "ordinary"   # 变量、函数、typedef 名、枚举常量
    TAGS = "tags"           # struct / union / enum 的标签


class ScopeKind(Enum):
    """C 的四种作用域（C99 6.2.1）。"""

    FILE = "file"           # 文件作用域：唯一能承载 internal/external 链接的一层
    FUNCTION = "function"   # 函数作用域：形参所在层
    BLOCK = "block"         # 块作用域：花括号
    PROTOTYPE = "prototype"  # 原型作用域：函数原型里的形参名


class TagKind(Enum):
    """标签的种类。C 里 struct/union/enum 共用同一个标签命名空间。"""

    STRUCT = "struct"
    UNION = "union"
    ENUM = "enum"


class SymbolKind(Enum):
    """被绑定的是"什么东西"——决定它属于哪个命名空间、有没有存储。"""

    VARIABLE = "variable"
    FUNCTION = "function"
    TYPEDEF = "typedef"
    ENUM_CONSTANT = "enum_constant"
    TAG = "tag"


class Linkage(Enum):
    """链接属性（C99 6.2.2）。只有文件作用域的符号才可能有非 NONE 的链接。"""

    NONE = "none"           # 无链接：局部变量、形参
    INTERNAL = "internal"   # 内部链接：static（D6 用它替代旧 g_static_globals 侧表）
    EXTERNAL = "external"   # 外部链接：普通全局变量/函数


@dataclass(frozen=True, order=True)
class Address:
    """一个 C 指针的值——真的只是一个地址。

    这是本次重构的核心：旧实现的"地址"是一个 Python 元组
    `('var', scope 对象, 名字)`，本质是**符号引用**，所以
      * 存不进内存、不能做指针算术、不能比较；
      * 局部变量的地址一直持有着 Scope，永远不会悬空；
      * `*(&x + 1)` 会静默读回 x（旧 execute.py:292-295）。
    换成定长整数编码后，指针就是内存里的一个 4 字节值，TASK.md 要的语义才立得住。

    NULL 被定义为 `(SCOPE, 0, 0)`，packed 后正好是整数 0——与 C 的 NULL 语义对齐。
    """

    region: AddressRegion
    scope_id: int = 0
    offset: int = 0

    def __post_init__(self) -> None:
        # 允许传整数（如 Address(1, 0, 16)），统一收敛成 IntEnum。
        try:
            region = AddressRegion(self.region)
        except ValueError as exc:
            raise AddressError(f"未知的地址区: {self.region!r}") from exc
        object.__setattr__(self, "region", region)

        if region is AddressRegion.SCOPE:
            if not 0 <= self.offset <= _SCOPE_OFFSET_MAX:
                raise AddressError(
                    f"scope 区偏移越界: {self.offset}（上限 {_SCOPE_OFFSET_MAX}）")
            if self.scope_id == 0:
                # 0 号作用域只代表 NULL；非零偏移 + 0 号作用域是无意义的地址。
                if self.offset != 0:
                    raise AddressError("scope 区地址的 scope_id 不能为 0（0 是 NULL 专用）")
            elif not SCOPE_ID_MIN <= self.scope_id <= SCOPE_ID_MAX:
                raise AddressError(
                    f"scope_id 越界: {self.scope_id}（合法范围 {SCOPE_ID_MIN}..{SCOPE_ID_MAX}）")
        else:
            if self.scope_id != 0:
                raise AddressError(f"{region.name} 区的地址没有 scope_id，必须为 0")
            if not 0 <= self.offset <= _WIDE_OFFSET_MAX:
                raise AddressError(
                    f"{region.name} 区偏移越界: {self.offset}（上限 {_WIDE_OFFSET_MAX}）")

    # ---- 查询 ----

    @property
    def is_null(self) -> bool:
        """是否 NULL 指针。"""
        return (self.region is AddressRegion.SCOPE
                and self.scope_id == 0
                and self.offset == 0)

    @property
    def packed(self) -> int:
        """按 4 字节方案拼成的无符号整数（指针真正的值）。"""
        raw = int(self.region) << _REGION_SHIFT
        if self.region is AddressRegion.SCOPE:
            raw |= self.scope_id << _SCOPE_ID_SHIFT
        return raw | self.offset

    # ---- 构造 ----

    @classmethod
    def from_packed(cls, raw: int) -> Address:
        """从 4 字节整数还原地址（与 :meth:`packed` 互逆）。"""
        if not isinstance(raw, int) or isinstance(raw, bool):
            raise AddressError(f"地址必须是整数，收到 {type(raw).__name__}")
        if not 0 <= raw <= 0xFFFFFFFF:
            raise AddressError(f"地址超出 4 字节范围: {raw}")
        try:
            region = AddressRegion(raw >> _REGION_SHIFT)
        except ValueError as exc:
            # 高字节是 3..255：保留区，当前没有对应实现
            raise AddressError(
                f"地址的高字节 {raw >> _REGION_SHIFT} 不是已知的内存区") from exc
        if region is AddressRegion.SCOPE:
            return cls(region, (raw >> _SCOPE_ID_SHIFT) & 0xFF, raw & _SCOPE_OFFSET_MAX)
        return cls(region, 0, raw & _WIDE_OFFSET_MAX)

    @classmethod
    def null(cls) -> Address:
        return NULL_ADDRESS

    # ---- 算术 ----

    def advanced(self, delta: int) -> Address:
        """指针加减：返回偏移平移后的新地址。

        C 的 `p + n` 实际是 `p + n * sizeof(*p)`，步长由元素类型决定——那是
        application 层的事（需要 CType）。值对象这里只做**字节**平移，
        并靠构造校验把越界挡在域内。
        """
        if self.is_null:
            raise AddressError("NULL 指针不能参与指针算术")
        if not isinstance(delta, int) or isinstance(delta, bool):
            raise AddressError(f"偏移量必须是整数，收到 {type(delta).__name__}")
        return Address(self.region, self.scope_id, self.offset + delta)

    def __add__(self, delta: int) -> Address:
        return self.advanced(delta)

    def __sub__(self, delta: int) -> Address:
        return self.advanced(-delta)

    def __repr__(self) -> str:
        if self.is_null:
            return "Address.NULL"
        return (f"Address({self.region.name}, scope_id={self.scope_id}, "
                f"offset={self.offset})")


#: C 的 NULL：`(SCOPE, 0, 0)`，packed == 0。
NULL_ADDRESS = Address(AddressRegion.SCOPE, 0, 0)
