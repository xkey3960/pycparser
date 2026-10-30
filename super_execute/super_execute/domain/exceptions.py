"""新领域（super_execute）的错误体系。

**没有**复用旧 ``execute.py`` 里那棵 ``InterpreterError`` 树——那棵树继承
``AssertionError``，是旧实现为了不破坏既有测试做的妥协（QOL-1）。新实现没有
这个包袱，所以直接继承 ``Exception``。

（这个文件原本还复制了一份旧异常类，属于搬骨架时的残留：新代码一个都没用到，
而且 ``LinkError`` 这个名字会和这里的重名。旧的那份留在 ``execute.py`` 里，
strangler 迁移完成前不动它。）
"""


class DomainError(Exception):
    """新领域（super_execute）的错误基类。

    带上"首次出错的位置"（``coord``）与调用链（``call_chain``），这样报错能指出
    源文件第几行、以及是怎么一路调过来的——旧实现把这件事叫 QOL-1。
    位置由**最内层**的适配器先附上，外层看到已有值就不再覆盖。
    """

    coord: object = None
    call_chain: list[str] | None = None

    def with_coord(self, coord: object) -> "DomainError":
        if self.coord is None and coord is not None:
            self.coord = coord
        return self

    def with_call_chain(self, chain: list[str] | None) -> "DomainError":
        if self.call_chain is None and chain:
            self.call_chain = list(chain)
        return self

    def __str__(self) -> str:
        message = super().__str__()
        if self.coord is not None:
            return f"{self.coord}: {message}"
        return message


# ==================== 名字与作用域 ====================


class InvalidSymbolError(DomainError, ValueError):
    """符号构造参数非法：空名字、地址落在错误的区、字段组合不合法等。"""


class InvalidScopeError(DomainError, ValueError):
    """作用域构造或状态转移非法：父子关系不成立、id 越界、链接属性放错了层等。"""


class DuplicateSymbolError(DomainError):
    """同一命名空间的同一层重复声明了同一个名字。"""


class UndefinedSymbolError(DomainError):
    """沿作用域链找不到该名字。"""


class ScopeExhaustedError(DomainError):
    """8 位作用域 id 空间用尽（D3 的直接后果）。"""


class NotAValueError(DomainError):
    """名字存在，但它不是一个可以读写值的对象（如 typedef 名、标签、枚举常量）。"""


class UnresolvedTypeError(DomainError):
    """符号上的 ctype 还是 None（类型尚未解析），无法按类型访问。"""


# ==================== 地址与内存 ====================


class AddressError(DomainError, ValueError):
    """地址编码/解码/算术越界。"""


class MemoryAccessError(DomainError):
    """内存访问错误基类（注意不能叫 MemoryError，那是 Python 内建异常）。"""


class ScopeDestroyedError(MemoryAccessError):
    """访问已销毁作用域的地址——悬空指针（D3）。"""


class OutOfBoundsError(MemoryAccessError):
    """地址落在任何已分配对象之外，或偏移越过了所在对象。"""


class AllocationError(MemoryAccessError):
    """分配失败：作用域区域已满、对齐或大小非法。"""


class RegionNotImplementedError(MemoryAccessError):
    """该地址区（如 heap）还没有实现。"""


class NullPointerError(MemoryAccessError):
    """解引用 NULL 指针。"""


# ==================== 类型 ====================


class InvalidTypeError(DomainError, ValueError):
    """类型构造或类型名使用非法。"""


class IncompleteTypeError(DomainError):
    """对不完整类型求 sizeof/alignof（如只有前置声明的 struct）。"""


class UndefinedTypeError(DomainError):
    """类型名无法解析成任何已知类型。"""


class UnsupportedTypeError(DomainError):
    """语言层面不支持的操作（sizeof 函数类型）或尚未实现的特性（位域）。"""


# ==================== 链接 ====================


class LinkError(DomainError):
    """链接错误：函数只有声明没有定义、参数个数不符、找不到入口等。"""


class DivisionByZeroError(DomainError):
    """整数除零。

    C 里这是未定义行为，但让 Python 的 ``ZeroDivisionError`` 漏到调用方是错的：
    它既不是 ``DomainError``，也没法被解释器的错误体系分类。
    """


class UndefinedLabelError(DomainError):
    """``goto`` 指向了当前函数里不存在的标签。

    标签是**函数作用域**的，所以"找不到"要等到跳出整个函数体才能确定。
    """
