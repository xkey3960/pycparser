class ReturnException(Exception):
    """Raised to unwind the stack on a return statement."""
    def __init__(self, value=None):
        self.value = value


class BreakException(Exception):
    """Raised to exit a loop."""


class ContinueException(Exception):
    """Raised to skip to the next loop iteration."""


class GotoException(Exception):
    """goto 跳转信号（CTRL-1）：携带目标标签名，由 Compound 捕获后跳转。"""

    def __init__(self, label):
        self.label = label
        super().__init__(f"goto {label}")


class LongJmpException(Exception):
    """longjmp 跳转信号（CTRL-2）：跨栈帧 unwind 到 setjmp 调用点。"""

    def __init__(self, buf, val):
        self.buf = buf
        self.val = val
        super().__init__(f"longjmp {buf} -> {val}")

class InterpreterError(AssertionError):
    """解释器错误基类（QOL-1）。

    继承 AssertionError 保证既有 `except AssertionError` 测试零破坏。
    携带出错的 AST 节点（取 coord 定位源码），消息可在顶层附上位置。
    """

    def __init__(self, message, node=None):
        self.message = message
        self.node = node
        super().__init__(message)


class UndefinedVariable(InterpreterError):
    """未定义变量/函数（含未定义类型引用）。"""


class TypeError_(InterpreterError):
    """类型错误：指针/下标/成员访问/类型推导等。"""


class UnsupportedError(InterpreterError):
    """尚未支持的特性（goto/指定初始化器/指针相减等）。"""


class LinkError(InterpreterError):
    """链接错误：原型无定义、重复定义等。"""


class MemoryError_(InterpreterError):
    """内存/堆错误：越界、非法地址、堆空间不足等。"""


# ==================== 新领域（super_execute）====================
#
# 上面的 InterpreterError 体系继承 AssertionError，是旧 execute.py 的妥协
# （QOL-1 为了不破坏既有测试，见其 docstring）。新实现没有这个包袱，因此
# 另起一棵树：DomainError 直接继承 Exception，不再假装成断言失败。
# 旧体系保留不动，等 strangler 迁移完成后再统一（D7）。


class DomainError(Exception):
    """新领域（super_execute）的错误基类。"""


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


class AddressError(DomainError, ValueError):
    """地址编码/解码/算术越界。"""