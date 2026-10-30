"""跑真正的 C 程序。

这是整个重构的验收场：源码 → pycparser → 适配器 → 用例 → 领域 → 内存，
一路跑到底，只看 ``main`` 的返回值对不对。
"""

import pytest
from pycparser.c_parser import CParser

from super_execute.domain.exceptions import (
    DomainError,
    LinkError,
    NullPointerError,
    UndefinedLabelError,
    UndefinedSymbolError,
    UnsupportedTypeError,
)
from super_execute.interface_adapters.ast.interpreter import Interpreter


def parse(source: str):
    return CParser().parse(source, "<test>")


def run(source: str, entry: str = "main"):
    interpreter = Interpreter()
    interpreter.load(parse(source))
    return interpreter.run(entry)


class TestGlobalInitialization:
    """全局初值可以是常量表达式，也可以调用函数（推迟到装载完之后求值）。"""

    def test_constant_expression(self):
        assert run("int g = 3 * 4; int main(void) { return g; }") == 12

    def test_initializer_calls_function(self):
        source = """
            int helper(void) { return 40; }
            int g = helper() + 2;
            int main(void) { return g; }
        """
        assert run(source) == 42

    def test_initializer_across_translation_units(self):
        """初值里的函数定义在**另一个**文件里——这才是推迟求值的原因。"""
        interpreter = Interpreter()
        interpreter.load(parse("int helper(void) { return 41; }"))
        interpreter.load(
            parse(
                "int helper(void); int g = helper() + 1; int main(void) { return g; }"
            )
        )
        assert interpreter.run() == 42

    def test_global_initialization_runs_once(self):
        source = """
            int count = 0;
            int bump(void) { count++; return count; }
            int g = bump();
            int main(void) { return g + count * 10; }
        """
        # g 只算一次：g=1、count=1 → 1 + 10 = 11
        assert run(source) == 11

    def test_array_dimension_constant_expression(self):
        assert run("int main(void) { int a[2 + 1]; return sizeof(a); }") == 12

    def test_array_dimension_using_enum(self):
        source = """
            enum { N = 4 };
            int main(void) { int a[N]; return sizeof(a) / sizeof(a[0]); }
        """
        assert run(source) == 4


class TestImplicitConversion:
    """TYPE-2：值流入某个类型时的隐式转换。"""

    def test_int_initializer_truncates(self):
        assert run("int main(void) { int x = 3.7; return x; }") == 3

    def test_return_value_truncates(self):
        assert run("int f(void) { return 3.7; } int main(void) { return f(); }") == 3

    def test_compound_assignment_truncates(self):
        assert run("int main(void) { int y = 5; y += 2.7; return y; }") == 7

    def test_argument_converted_to_parameter_type(self):
        source = """
            int half_of(double x) { return x / 2; }
            int main(void) { return half_of(5); }
        """
        assert run(source) == 2  # 5 → 5.0 / 2 = 2.5 → int 2

    def test_int_to_double_promotion(self):
        source = """
            double twice(double x) { return x * 2; }
            int main(void) { return (int)twice(3); }
        """
        assert run(source) == 6

    def test_pointer_initialized_with_zero(self):
        assert run("int main(void) { int *p = 0; return p == 0; }") == 1


class TestErrorReporting:
    """QOL-1：错误要带源码位置与调用链。"""

    def _failing(self, source):
        interpreter = Interpreter()
        interpreter.load(parse(source))
        return interpreter

    def test_error_carries_source_location(self):
        source = (
            "int inner(int a) { return a + zz; }\nint main(void) { return inner(5); }"
        )
        with pytest.raises(UndefinedSymbolError) as info:
            self._failing(source).run()
        assert "<test>:1" in str(info.value)

    def test_error_reports_call_chain(self, capsys):
        source = (
            "int inner(int a) { return a + zz; }\n"
            "int helper(int x) { return inner(x); }\n"
            "int main(void) { return helper(5); }"
        )
        with pytest.raises(UndefinedSymbolError):
            self._failing(source).run()

        out = capsys.readouterr().out
        assert "[error]" in out
        assert "调用链" in out
        assert "main" in out and "helper" in out and "inner" in out

    def test_success_prints_nothing(self, capsys):
        assert run("int main(void) { return 7; }") == 7
        assert capsys.readouterr().out == ""


class TestStaticIsolation:
    """D6：``static`` 是文件级的，两个文件的同名 static 互不相干。"""

    def _load(self, *sources):
        interpreter = Interpreter()
        for source in sources:
            interpreter.load(parse(source))
        return interpreter

    def test_static_globals_are_per_translation_unit(self):
        interpreter = self._load(
            "static int g = 100; int use_a(void) { g += 1; return g; }",
            "static int g = 200; int use_b(void) { g += 5; return g; }",
            "int use_a(void); int use_b(void);"
            "int main(void) { return use_a() + use_b(); }",
        )
        assert interpreter.run() == 101 + 205

    def test_static_functions_are_per_translation_unit(self):
        interpreter = self._load(
            "static int helper(void) { return 10; }"
            "int use_a(void) { return helper(); }",
            "static int helper(void) { return 20; }"
            "int use_b(void) { return helper(); }",
            "int use_a(void); int use_b(void);"
            "int main(void) { return use_a() + use_b(); }",
        )
        assert interpreter.run() == 10 + 20

    def test_static_is_invisible_from_another_unit(self):
        interpreter = self._load(
            "static int secret(void) { return 1; } int pub(void) { return secret(); }",
            "int pub(void); int main(void) { return secret(); }",
        )
        with pytest.raises(UndefinedSymbolError):
            interpreter.run()

    def test_external_symbols_still_shared(self):
        interpreter = self._load(
            "int shared = 7;",
            "extern int shared; int main(void) { return shared; }",
        )
        assert interpreter.run() == 7

    def test_two_statics_with_same_name_do_not_collide(self):
        """这正是重构前的 bug：同名的 static 全局会在同一个作用域里撞车。"""
        interpreter = self._load(
            "static int counter = 1; int a(void) { return counter; }",
            "static int counter = 2; int b(void) { return counter; }",
        )
        assert interpreter.run("a") == 1
        assert interpreter.run("b") == 2

    def test_static_initializer_sees_its_own_unit(self):
        interpreter = self._load(
            "static int base(void) { return 5; } static int value = base();"
            "int get(void) { return value; }",
        )
        assert interpreter.run("get") == 5


class TestInitializers:
    """初始化列表与指定初始化器（C99 6.7.9，也覆盖 GNU 扩展）。"""

    def test_flat_array(self):
        assert run("int main(void){ int a[3]={1,2,3}; return a[0]+a[1]+a[2]; }") == 6

    def test_length_deduced_from_initializer(self):
        source = "int main(void){ int a[]={4,5,6}; return sizeof(a)/sizeof(a[0]); }"
        assert run(source) == 3

    def test_missing_elements_are_zero(self):
        source = "int main(void){ int a[5]={1,2}; return a[2]+a[3]+a[4]; }"
        assert run(source) == 0

    def test_nested_array(self):
        source = """
            int main(void) {
                int m[2][3] = {{1,2,3},{4,5,6}};
                int sum = 0;
                for (int i = 0; i < 2; i++)
                    for (int j = 0; j < 3; j++) sum += m[i][j];
                return sum;
            }
        """
        assert run(source) == 21

    def test_struct_positional(self):
        source = """
            struct P { int x; int y; };
            int main(void) { struct P p = {3, 4}; return p.x * 10 + p.y; }
        """
        assert run(source) == 34

    def test_struct_nested_initializer(self):
        source = """
            struct In { int a; int b; };
            struct Out { struct In in; int c; };
            int main(void) {
                struct Out o = {{1, 2}, 3};
                return o.in.a + o.in.b * 10 + o.c * 100;
            }
        """
        assert run(source) == 321

    def test_designated_members_out_of_order(self):
        source = """
            struct S { int a; int b; };
            int main(void) { struct S s = { .b = 5, .a = 2 }; return s.a * 10 + s.b; }
        """
        assert run(source) == 25

    def test_designated_array_indices(self):
        source = "int main(void){ int a[3] = { [1]=7, [2]=3 }; return a[0]+a[1]*10; }"
        assert run(source) == 70

    def test_too_many_initializers(self):
        with pytest.raises(DomainError):
            run("struct S{int a;}; int main(void){ struct S s = {1,2}; return s.a; }")

    def test_unknown_designator(self):
        with pytest.raises(DomainError):
            run("struct S{int a;}; int main(void){ struct S s = {.zz=1}; return s.a; }")


class TestStatementExpressions:
    """GNU 语句表达式 `({ ... })`：值是最后一条表达式语句。"""

    def test_returns_last_expression(self):
        source = "int main(void){ int x = ({ int a=3; int b=4; a+b; }); return x; }"
        assert run(source) == 7

    def test_inner_variables_do_not_leak(self):
        source = """
            int main(void) {
                int a = 100;
                int x = ({ int a = 3; a + 1; });
                return a + x;
            }
        """
        assert run(source) == 104

    def test_side_effects_visible(self):
        source = "int main(void){ int n=0; int x = ({ n = 5; n + 1; }); return x + n; }"
        assert run(source) == 11

    def test_nested(self):
        source = "int main(void){ int x = ({ int a = 2; ({ a * 5; }); }); return x; }"
        assert run(source) == 10

    def test_no_value_when_last_is_statement(self):
        assert run("int main(void){ ({ int a = 1; }); return 42; }") == 42


class TestMainReturnValue:
    """C99 5.1.2.2.3：``main`` 执行到结尾的 ``}`` 等价于 ``return 0;``。"""

    def test_main_without_return_returns_zero(self):
        assert run("int main(void) { int x = 1; }") == 0

    def test_main_with_empty_body_returns_zero(self):
        assert run("int main(void) { }") == 0

    def test_explicit_return_wins(self):
        assert run("int main(void) { return 7; }") == 7

    def test_only_main_gets_the_default(self):
        """别的非 void 函数落到结尾仍是未定义行为，不给默认值。"""
        interpreter = Interpreter()
        interpreter.load(
            parse("int helper(void) { int x = 1; } int main(void) { return 0; }")
        )
        assert interpreter.run("helper") is None


class TestNullDereference:
    def test_message_mentions_address(self):
        """报错要说清是"地址"层面的问题，不能只说"指针"。"""
        with pytest.raises(NullPointerError, match="地址"):
            run("int main(void) { int *p = 0; return *p; }")

    def test_uninitialized_pointer_is_null(self):
        """本实现把未初始化的指针当 NULL（有意偏差，C 里是未定义值）。"""
        with pytest.raises(NullPointerError):
            run("int main(void) { int *p; return *p; }")


class TestBasics:
    def test_arithmetic_precedence(self):
        assert run("int main(void) { return 1 + 2 * 3; }") == 7

    def test_variables_and_assignment(self):
        assert (
            run("int main(void) { int a = 5; int b = 7; a = a + b; return a; }") == 12
        )

    def test_global_variable(self):
        assert run("int g = 40; int main(void) { g = g + 2; return g; }") == 42

    def test_integer_division(self):
        assert run("int main(void) { return 7 / 2 + (-7) / 2; }") == 0

    def test_uninitialized_is_zero(self):
        assert run("int main(void) { int x; return x; }") == 0


class TestControlFlow:
    def test_if_else_taken(self):
        source = "int main(void) { int x = 10; if (x > 5) return 1; else return 2; }"
        assert run(source) == 1

    def test_if_else_not_taken(self):
        source = "int main(void) { int x = 1; if (x > 5) return 1; else return 2; }"
        assert run(source) == 2

    def test_while_sum(self):
        source = """
            int main(void) {
                int i = 0; int sum = 0;
                while (i < 5) { sum = sum + i; i++; }
                return sum;
            }
        """
        assert run(source) == 10

    def test_do_while_runs_once(self):
        source = """
            int main(void) { int n = 0; do { n++; } while (n < 0); return n; }
        """
        assert run(source) == 1

    def test_for_with_break(self):
        source = """
            int main(void) {
                int s = 0;
                for (int i = 0; i < 10; i++) { if (i == 4) break; s += i; }
                return s;
            }
        """
        assert run(source) == 6

    def test_for_with_continue(self):
        source = """
            int main(void) {
                int s = 0;
                for (int i = 0; i < 6; i++) { if (i % 2) continue; s += i; }
                return s;
            }
        """
        assert run(source) == 6

    def test_nested_loops(self):
        source = """
            int main(void) {
                int total = 0;
                for (int i = 0; i < 3; i++)
                    for (int j = 0; j < 3; j++)
                        total++;
                return total;
            }
        """
        assert run(source) == 9

    def test_while_with_break(self):
        source = """
            int main(void) {
                int i = 0;
                while (1) { if (i == 7) break; i++; }
                return i;
            }
        """
        assert run(source) == 7

    def test_while_with_continue(self):
        source = """
            int main(void) {
                int i = 0; int s = 0;
                while (i < 6) {
                    i++;
                    if (i % 2) continue;
                    s += i;
                }
                return s;
            }
        """
        assert run(source) == 12  # 2 + 4 + 6

    def test_do_while_with_break(self):
        source = """
            int main(void) {
                int i = 0;
                do { if (i == 3) break; i++; } while (1);
                return i;
            }
        """
        assert run(source) == 3


class TestFunctions:
    def test_recursion(self):
        source = """
            int fac(int n) { if (n <= 1) return 1; return n * fac(n - 1); }
            int main(void) { return fac(5); }
        """
        assert run(source) == 120

    def test_mutual_recursion(self):
        source = """
            int is_even(int n);
            int is_odd(int n) { if (n == 0) return 0; return is_even(n - 1); }
            int is_even(int n) { if (n == 0) return 1; return is_odd(n - 1); }
            int main(void) { return is_even(10); }
        """
        assert run(source) == 1

    def test_argument_passing_does_not_leak(self):
        source = """
            int bump(int x) { x = x + 1; return x; }
            int main(void) { int a = 5; bump(a); return a; }
        """
        assert run(source) == 5

    def test_argument_order_matters(self):
        """用非交换运算钉住形参顺序（加法区分不出来）。"""
        source = """
            int sub(int a, int b) { return a - b; }
            int main(void) { return sub(10, 3); }
        """
        assert run(source) == 7

    def test_three_arguments_in_order(self):
        source = """
            int mix(int a, int b, int c) { return a * 100 + b * 10 + c; }
            int main(void) { return mix(1, 2, 3); }
        """
        assert run(source) == 123

    def test_forward_declaration(self):
        source = """
            int add(int a, int b);
            int main(void) { return add(2, 3); }
            int add(int a, int b) { return a + b; }
        """
        assert run(source) == 5

    def test_void_function(self):
        source = """
            int g = 0;
            void set(void) { g = 99; }
            int main(void) { set(); return g; }
        """
        assert run(source) == 99

    def test_declaration_without_definition(self):
        interpreter = Interpreter()
        interpreter.load(
            CParser().parse("int f(int); int main(void) { return f(1); }", "<t>")
        )
        with pytest.raises(LinkError, match="只有声明没有定义"):
            interpreter.run()

    def test_unknown_function(self):
        with pytest.raises(UndefinedSymbolError):
            run("int main(void) { return nope(); }")

    def test_too_many_arguments(self):
        source = """
            int f(int a) { return a; }
            int main(void) { return f(1, 2); }
        """
        with pytest.raises(LinkError, match="只接受"):
            run(source)


class TestStructsAndPointers:
    def test_struct_members(self):
        source = """
            struct Point { int x; int y; };
            int main(void) {
                struct Point p; p.x = 3; p.y = 4;
                return p.x * p.x + p.y * p.y;
            }
        """
        assert run(source) == 25

    def test_struct_passed_by_value(self):
        source = """
            struct Point { int x; int y; };
            int sum(struct Point p) { return p.x + p.y; }
            int main(void) {
                struct Point p; p.x = 10; p.y = 20;
                return sum(p);
            }
        """
        assert run(source) == 30

    def test_struct_assignment_copies(self):
        """`q = p` 之后改 q 不能影响 p（C 的值语义）。"""
        source = """
            struct Point { int x; int y; };
            int main(void) {
                struct Point p; p.x = 10; p.y = 5;
                struct Point q = p;
                q.x = 100;
                return p.x + q.x;
            }
        """
        assert run(source) == 110  # 10 + 100；若共享则是 200

    def test_struct_parameter_mutation_does_not_leak(self):
        source = """
            struct Point { int x; int y; };
            int bump(struct Point p) { p.x = 999; return p.x; }
            int main(void) {
                struct Point p; p.x = 1; p.y = 2;
                bump(p);
                return p.x;
            }
        """
        assert run(source) == 1

    def test_pointer_and_arrow(self):
        """对应仓库里 test/multi/ptr_main.c 的同款程序：99 + 37 = 136。"""
        source = """
            struct AAA { int x; int y; };
            int main(void) {
                struct AAA a;
                a.x = 5;
                a.y = 37;
                struct AAA *pa = &a;
                pa->x = 99;
                int via_ptr = pa->y;
                return a.x + via_ptr;
            }
        """
        assert run(source) == 136

    def test_array_fill_and_sum(self):
        source = """
            int main(void) {
                int a[4]; int i; int s = 0;
                for (i = 0; i < 4; i++) { a[i] = i * 2; }
                for (i = 0; i < 4; i++) { s += a[i]; }
                return s;
            }
        """
        assert run(source) == 12

    def test_pointer_arithmetic(self):
        source = """
            int main(void) {
                int a[3]; a[0] = 10; a[1] = 20; a[2] = 30;
                int *p = a;
                return *(p + 2) + p[1];
            }
        """
        assert run(source) == 50

    def test_swap_through_pointers(self):
        source = """
            void swap(int *a, int *b) { int t = *a; *a = *b; *b = t; }
            int main(void) {
                int x = 1; int y = 2;
                swap(&x, &y);
                return x * 10 + y;
            }
        """
        assert run(source) == 21


class TestScoping:
    def test_block_shadowing(self):
        source = """
            int main(void) {
                int x = 1;
                { int x = 2; }
                return x;
            }
        """
        assert run(source) == 1

    def test_block_variable_not_visible_outside(self):
        with pytest.raises(UndefinedSymbolError):
            run("int main(void) { { int inner = 9; } return inner; }")

    def test_for_scope_does_not_leak(self):
        with pytest.raises(UndefinedSymbolError):
            run("int main(void) { for (int i = 0; i < 1; i++) {} return i; }")

    def test_local_shadows_global(self):
        source = """
            int g = 7;
            int main(void) { int g = 1; return g; }
        """
        assert run(source) == 1

    def test_callee_cannot_see_caller_locals(self):
        """函数作用域挂在**文件作用域**下，不是挂在调用者的作用域下。"""
        source = """
            int f(void) { return y; }
            int main(void) { int y = 5; return f(); }
        """
        with pytest.raises(UndefinedSymbolError):
            run(source)

    def test_typedef_inside_function(self):
        source = """
            int main(void) {
                typedef int MyInt;
                MyInt x = 5;
                return x;
            }
        """
        assert run(source) == 5


class TestMultiUnit:
    def test_two_units_share_globals_and_functions(self):
        interpreter = Interpreter()
        interpreter.load(CParser().parse("int helper(void) { return 40; }", "<a>"))
        interpreter.load(
            CParser().parse(
                "int helper(void); int main(void) { return helper() + 2; }", "<b>"
            )
        )
        assert interpreter.run() == 42


class TestUnsupported:
    def test_switch_not_supported(self):
        source = """
            int main(void) {
                int x = 1;
                switch (x) { case 1: return 1; }
                return 0;
            }
        """
        with pytest.raises(UnsupportedTypeError):
            run(source)


class TestGoto:
    """CTRL-1：标签是函数作用域的，可以前跳、回跳、从循环/嵌套块里跳出去。"""

    def test_forward_jump(self):
        source = """
            int main(void) {
                int x = 0;
                goto skip;
                x = 100;
            skip:
                x += 5;
                return x;
            }
        """
        assert run(source) == 5

    def test_backward_jump_as_loop(self):
        source = """
            int main(void) {
                int i = 0, sum = 0;
            loop:
                sum += i;
                i++;
                if (i < 5) goto loop;
                return sum;
            }
        """
        assert run(source) == 10

    def test_jump_out_of_loop(self):
        source = """
            int main(void) {
                int i;
                for (i = 0; i < 100; i++) {
                    if (i == 7) goto done;
                }
            done:
                return i;
            }
        """
        assert run(source) == 7

    def test_jump_out_of_nested_block(self):
        source = """
            int main(void) {
                int x = 0;
                if (1) { goto out; }
                x = 99;
            out:
                return x + 1;
            }
        """
        assert run(source) == 1

    def test_undefined_label(self):
        with pytest.raises(UndefinedLabelError):
            run("int main(void) { goto nowhere; return 0; }")


class TestFunctionPointers:
    """FnPtr：函数名当值就是它的地址，经变量可以照常调用。"""

    def test_call_through_variable(self):
        source = """
            int inc(int x) { return x + 1; }
            int main(void) { int (*fp)(int) = inc; return fp(41); }
        """
        assert run(source) == 42

    def test_reassign_pointer(self):
        source = """
            int inc(int x) { return x + 1; }
            int dbl(int x) { return x * 2; }
            int main(void) {
                int (*fp)(int);
                fp = inc;
                int a = fp(10);
                fp = dbl;
                int b = fp(10);
                return a + b;
            }
        """
        assert run(source) == 31

    def test_address_of_function(self):
        source = """
            int inc(int x) { return x + 1; }
            int main(void) { int (*fp)(int) = &inc; return fp(9); }
        """
        assert run(source) == 10

    def test_pointer_as_parameter(self):
        source = """
            int inc(int x) { return x + 1; }
            int apply(int (*fp)(int), int x) { return fp(x); }
            int main(void) { return apply(inc, 41); }
        """
        assert run(source) == 42

    def test_dereference_form(self):
        source = """
            int inc(int x) { return x + 1; }
            int main(void) { int (*fp)(int) = inc; return (*fp)(9); }
        """
        assert run(source) == 10

    def test_calling_null_pointer_fails(self):
        source = """
            int main(void) { int (*fp)(int) = 0; return fp(1); }
        """
        with pytest.raises(DomainError):
            run(source)
