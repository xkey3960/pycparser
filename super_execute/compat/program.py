"""旧 ``program.CProgram`` 的兼容壳，跑在新解释器上。

旧测试的用法是固定的：

    exe_mod.setup_global_scope()
    prog = CProgram(files, entry='main')
    prog.load()
    prog.link()
    return prog.run()

新实现里"链接"发生在装载时（符号就地登记进作用域），所以 ``link()`` 只用来
校验入口存在——旧测试恰好断言了"没有入口时报未找到入口函数"。
"""

from __future__ import annotations

from typing import Any, Sequence

import pycparser

import compat_state
from execute import InterpreterError, LinkError, translate

from super_execute.domain.exceptions import DomainError
from super_execute.interface_adapters.ast.interpreter import Interpreter


class CProgram:
    """按旧接口装载 / 链接 / 运行一组 C 源文件。"""

    def __init__(
        self,
        files: Sequence[str],
        entry: str = "main",
        cpp_path: str = "gcc",
        cpp_args: Any = None,
        parser: Any = None,
        encoding: str | None = None,
        strict: bool = False,
        lazy: bool = True,
        **_ignored: Any,
    ) -> None:
        self.files = list(files)
        self.entry = entry
        self.cpp_path = cpp_path
        # 旧的 CProgram 默认就是这两个参数；pycparser.preprocess_file 不会自己加 -E，
        # 少了它 gcc 会去编译链接（于是报"没有 main"），而不是只做预处理。
        self.cpp_args = (
            cpp_args if cpp_args is not None else ["-E", "-Iutils/fake_libc_include"]
        )
        # 注意：这里用**朴素 CParser**，不是旧的 GnuCParser。
        # GNU 扩展（typeof / 语句表达式 / __attribute__）还没进新适配器，
        # 用朴素解析器会让那些夹具直接解析失败——这是明确的缺口，不是隐藏的错。
        self.parser = parser
        self.encoding = encoding
        self.strict = strict
        self.lazy = lazy
        self.asts: list[Any] = []
        # 装载阶段**总是**惰性（出错先记下、不中断）：旧实现的 load() 也只登记，
        # 全量检查发生在 link()。要不要报错由 link() 按 lazy 决定。
        self.interpreter = Interpreter(lazy=True)

    # ---- 装载 ----

    def load(self) -> list[Any]:
        for path in self.files:
            ast = pycparser.parse_file(
                path,
                use_cpp=True,
                cpp_path=self.cpp_path,
                cpp_args=self.cpp_args,
                parser=self.parser,
                encoding=self.encoding,
            )
            self.asts.append(ast)
            compat_state.remember_ast(path, ast)

        try:
            # 注意要和文件名一起遍历：只写 `for ast in self.asts` 会让 `path`
            # 停留在上一个循环的最后一个值，于是所有单元登记成同一个文件名
            for path, ast in zip(self.files, self.asts):
                self.interpreter.load(ast, path)
        except DomainError as error:
            raise translate(error) from None

        compat_state.set_current(self.interpreter)
        return self.asts

    # ---- 链接 ----

    def link(self) -> "CProgram":
        """``lazy=False`` 时做全量检查，把惰性装载攒下的错误抛出来。

        旧的 ``link()`` 顺带做了入口定位，但入口检查挪到了 ``run()``——
        否则"故意没有 main、只想验证冲突检测"的用例会先撞上入口错误。
        """
        if not self.lazy:
            try:
                self.interpreter.raise_pending()
            except DomainError as error:
                raise translate(error) from None
        return self

    # ---- 运行 ----

    def run(self, *args: Any) -> Any:
        if self.interpreter.globals.find(self.entry) is None:
            raise LinkError(f"未找到入口函数 '{self.entry}'")
        try:
            if args:
                return self.interpreter.call(self.entry, list(args))
            return self.interpreter.run(self.entry)
        except DomainError as error:
            raise translate(error) from None


__all__ = ["CProgram", "InterpreterError", "translate"]
