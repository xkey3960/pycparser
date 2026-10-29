"""内存端口：用例怎么"拿到一块存储""按地址读写"。

这是整条主线的收束点——前面两轮做的
:class:`~super_execute.domain.value_objects.Address` 和
:class:`~super_execute.domain.entities.c_types.CType` 到这里才真正连起来：

    CType 决定一块存储多大、对齐到几（sizeof / alignof）
    Address 决定它在哪个作用域、第几个字节
    MemoryPort 按地址读写，越界 / 悬空 / 类型不符都从这里报错

**为什么读写得带 CType**：这是 C 的语义决定的，不是实现偷懒。`s` 与 `s.a`
的地址可能是同一个（首成员偏移 0），只有**类型**能区分"读整个结构体"还是
"读那个 int"。所以 `read(address, ctype)` 里的 ctype 是访问类型，不是装饰。

**为什么是端口而不是直接调实现**：本轮实现（``SlotMemory``）里值还是 Python
对象，下一轮要换成真正的字节数组；用例只依赖这个接口，换实现不改用例。

**契约**（实现必须满足）：

* ``allocate`` 只接受**完整**类型；不完整类型抛 ``IncompleteTypeError``；
* ``read`` / ``write`` 的地址必须落在某个已分配对象内，否则 ``OutOfBoundsError``；
* 访问类型必须与目标对象的类型相容，否则 ``MemoryAccessError``；
* 作用域 ``destroy_scope`` 之后，属于它的地址一律 ``ScopeDestroyedError``（D3）；
* 实现可以只支持一部分地址区，其余抛 ``RegionNotImplementedError``。
"""

from typing import Any, Protocol, runtime_checkable

from super_execute.domain.entities.c_types import CType
from super_execute.domain.value_objects import Address


@runtime_checkable
class MemoryPort(Protocol):
    """对象存储的抽象。"""

    def create_scope(self, scope_id: int) -> None:
        """为某个作用域开一块存储区。"""

    def destroy_scope(self, scope_id: int) -> None:
        """销毁作用域的存储；此后经该 id 的地址访问必须报错。"""

    def is_live(self, scope_id: int) -> bool:
        """该作用域的存储是否还在。"""

    def allocate(self, scope_id: int, ctype: CType) -> Address:
        """在作用域的存储区里为 ``ctype`` 分配一块，返回它的地址。"""

    def read(self, address: Address, ctype: CType) -> Any:
        """按 ``ctype`` 读地址上的值。

        地址可以是对象的基地址，也可以是成员 / 元素的地址——具体读哪一块由
        ``ctype`` 与偏移一起决定。
        """

    def write(self, address: Address, value: Any, ctype: CType) -> None:
        """按 ``ctype`` 把值写到地址上。"""
