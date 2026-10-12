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