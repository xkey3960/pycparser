"""可变参数：``va_start`` / ``va_arg`` / ``va_end``。

``va_arg(ap, int)`` 的第二个实参是**类型名**，标准语法分析器不认识它
（pycparser 会报 ``Invalid expression``），所以这里用**继承**的办法加了一条语法：
``VaArgParser`` 重载 ``_parse_postfix_expression``，其余全部交回父类。
上游 pycparser 一行没改。
"""

import pytest

from super_execute.domain.exceptions import InvalidTypeError, UnsupportedTypeError
from super_execute.interface_adapters.ast.interpreter import Interpreter
from super_execute.interface_adapters.ast.va_arg import VaArgExpr, VaArgParser

#: 没有走预处理器时，`va_list` 得自己声明（fake 头文件里它就是 int）
VA_LIST = "typedef int va_list;\n"


def run(source: str):
    interpreter = Interpreter()
    interpreter.load(VaArgParser().parse(VA_LIST + source, "<test>"))
    return interpreter.run()


class TestParser:
    def test_va_arg_becomes_va_arg_node(self):
        ast = VaArgParser().parse(
            VA_LIST + "int f(int n, ...) { va_list ap; return va_arg(ap, int); }"
        )
        body = ast.ext[1].body.block_items[1]
        assert isinstance(body.expr, VaArgExpr)
        assert body.expr.ap.name == "ap"

    def test_complex_type_argument(self):
        ast = VaArgParser().parse(
            VA_LIST + "int f(va_list ap) { return va_arg(ap, struct S *); }"
        )
        node = ast.ext[1].body.block_items[0].expr
        assert isinstance(node, VaArgExpr)
        assert node.type_name.type.__class__.__name__ == "PtrDecl"

    def test_normal_calls_unchanged(self):
        ast = VaArgParser().parse("int f(void) { return g(1, 2); }")
        call = ast.ext[0].body.block_items[0].expr
        assert call.__class__.__name__ == "FuncCall"

    def test_standard_parser_still_rejects_it(self):
        """对照组：标准 CParser 解析不了——这正是要自定义解析器的原因。"""
        from pycparser.c_parser import CParser

        with pytest.raises(Exception, match="Invalid expression|before"):
            CParser().parse(
                VA_LIST + "int f(int n, ...) { va_list ap; return va_arg(ap, int); }"
            )

    def test_builtin_spelling_from_real_gcc_headers(self):
        """真实 gcc 的 stdarg.h 会把 va_arg 展开成 __builtin_va_arg(ap, int)。"""
        ast = VaArgParser().parse(
            VA_LIST + "int f(va_list ap) { return __builtin_va_arg(ap, int); }"
        )
        node = ast.ext[1].body.block_items[0].expr
        assert isinstance(node, VaArgExpr)


class TestRuntime:
    def test_sum_of_varargs(self):
        source = """
            int sum(int n, ...) {
                va_list ap;
                int total = 0;
                va_start(ap, n);
                for (int i = 0; i < n; i++)
                    total += va_arg(ap, int);
                va_end(ap);
                return total;
            }
            int main(void) { return sum(3, 10, 20, 12); }
        """
        assert run(source) == 42

    def test_arguments_come_in_order(self):
        source = """
            int first(int n, ...) {
                va_list ap;
                va_start(ap, n);
                return va_arg(ap, int);
            }
            int main(void) { return first(0, 7, 8, 9); }
        """
        assert run(source) == 7

    def test_advances_each_time(self):
        source = """
            int nth(int n, ...) {
                va_list ap;
                va_start(ap, n);
                int a = va_arg(ap, int);
                int b = va_arg(ap, int);
                int c = va_arg(ap, int);
                return a * 100 + b * 10 + c;
            }
            int main(void) { return nth(0, 1, 2, 3); }
        """
        assert run(source) == 123

    def test_converts_to_requested_type(self):
        """实参是 int 3，按 double 取就是 3.0。"""
        source = """
            double half(int n, ...) {
                va_list ap;
                va_start(ap, n);
                return va_arg(ap, double) / 2.0;
            }
            int main(void) { return (int)(half(0, 3) * 10); }
        """
        assert run(source) == 15

    def test_char_pointer_argument(self):
        source = """
            int len_first(int n, ...) {
                va_list ap;
                va_start(ap, n);
                return strlen(va_arg(ap, char *));
            }
            int main(void) { return len_first(0, "hello"); }
        """
        assert run(source) == 5

    def test_va_end_is_noop(self):
        source = """
            int f(int n, ...) {
                va_list ap;
                va_start(ap, n);
                int a = va_arg(ap, int);
                va_end(ap);
                return a;
            }
            int main(void) { return f(0, 5); }
        """
        assert run(source) == 5

    def test_two_functions_keep_separate_cursors(self):
        source = """
            int count(int n, ...) {
                va_list ap;
                va_start(ap, n);
                return va_arg(ap, int);
            }
            int main(void) {
                int a = count(0, 11);
                int b = count(0, 22);
                return a + b;
            }
        """
        assert run(source) == 33

    def test_nested_calls(self):
        """内层函数调用不能破坏外层的可变参数帧。"""
        source = """
            int inner(int x) { return x * 2; }
            int outer(int n, ...) {
                va_list ap;
                va_start(ap, n);
                int first = va_arg(ap, int);
                int second = va_arg(ap, int);
                return inner(first) + second;
            }
            int main(void) { return outer(0, 3, 4); }
        """
        assert run(source) == 10


class TestErrors:
    def test_va_arg_without_va_start(self):
        source = """
            int f(int n, ...) {
                va_list ap;
                return va_arg(ap, int);
            }
            int main(void) { return f(0, 1); }
        """
        with pytest.raises(InvalidTypeError, match="va_start"):
            run(source)

    def test_taking_too_many(self):
        source = """
            int f(int n, ...) {
                va_list ap;
                va_start(ap, n);
                int a = va_arg(ap, int);
                int b = va_arg(ap, int);
                return a + b;
            }
            int main(void) { return f(0, 1); }
        """
        with pytest.raises(InvalidTypeError, match="取完"):
            run(source)


class TestWithoutVaArgParser:
    def test_plain_interpreter_rejects_va_arg_node(self):
        """没接处理器时给出明确错误（防止静默出错）。"""
        from super_execute.interface_adapters.ast.evaluator import (
            _unsupported_va_arg,
        )

        with pytest.raises(UnsupportedTypeError, match="set_va_arg_handler"):
            _unsupported_va_arg(None, None)
