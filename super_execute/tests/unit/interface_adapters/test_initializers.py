"""初始化器：聚合初值的各种写法。

这一批是**真实报错驱动**补上的——`还没支持的表达式: InitList` 来自用户代码：

```c
typedef enum { Test1, Test2, TestMax } TestEnum;
char *g_apcTestString[TestMax] = {
    [Test1] = "Test1",
    [Test2] = "Test2",
};
```

根因是**全局**初始化走了 `eval` 而不是 `eval_init`——花括号列表不是表达式。
顺带补上了同一条链上的其它缺口：复合字面量、数组退化、嵌套设计符。
"""

import pytest

from super_execute.domain.exceptions import DomainError
from super_execute.interface_adapters.ast.interpreter import Interpreter
from pycparser.c_parser import CParser


def run(source: str):
    interpreter = Interpreter()
    interpreter.load(CParser().parse(source, "<test>"))
    return interpreter.run()


class TestGlobalAggregate:
    """全局聚合初始化：以前报 `还没支持的表达式: InitList`。"""

    def test_global_array(self):
        assert run("int g[3] = {1,2,3}; int main(void){ return g[1]; }") == 2

    def test_global_struct(self):
        source = """
            struct S { int x, y; };
            struct S g = {4, 5};
            int main(void) { return g.x * 10 + g.y; }
        """
        assert run(source) == 45

    def test_global_designated(self):
        source = """
            struct S { int x, y; };
            struct S g = { .y = 7 };
            int main(void) { return g.y; }
        """
        assert run(source) == 7

    def test_global_two_dimensional(self):
        source = """
            int g[2][2] = {{1,2},{3,4}};
            int main(void) { return g[1][1]; }
        """
        assert run(source) == 4

    def test_global_initializer_may_call_functions(self):
        assert (
            run("int a = 3; int g[2] = {1, a * 2}; int main(void){ return g[1]; }") == 6
        )

    def test_global_length_deduced_from_list(self):
        assert (
            run("int g[] = {1,2,3,4}; int main(void){ return sizeof(g)/sizeof(int); }")
            == 4
        )

    def test_global_length_deduced_from_string(self):
        assert run('char g[] = "abcd"; int main(void){ return strlen(g); }') == 4

    def test_global_two_dimensional_open_length(self):
        assert (
            run("int g[][2] = {{1,2},{3,4},{5,6}}; int main(void){ return g[2][0]; }")
            == 5
        )

    def test_global_struct_array(self):
        source = """
            struct S { int x; };
            struct S g[] = {{1},{2},{3}};
            int main(void) { return g[2].x; }
        """
        assert run(source) == 3


class TestEnumDesignators:
    """用户报错的那个形态：枚举常量当下标设计符。"""

    SOURCE = """
        typedef enum tagTestEnum {
            Test1,
            Test2,
            TestMax,
        } TestEnum;

        char *g_apcTestString[TestMax] = {
            [Test1] = "Test1",
            [Test2] = "Test2",
        };

        int main(void) {
            return strlen(g_apcTestString[Test1]) * 10
                 + strlen(g_apcTestString[Test2]);
        }
    """

    def test_enum_constant_designator(self):
        """两个字符串都是 5 个字符 → 55。"""
        assert run(self.SOURCE) == 55

    def test_designator_order_does_not_matter(self):
        assert (
            run(
                "int g[4] = { [3] = 1, [0] = 2 }; int main(void){ return g[0]*10 + g[3]; }"
            )
            == 21
        )

    def test_designator_expression(self):
        assert run("int g[4] = { [1 + 1] = 5 }; int main(void){ return g[2]; }") == 5

    def test_designator_type_drives_interpretation(self):
        """同一个 `ID` 设计符：数组里当下标，结构体里当成员名。"""
        array = (
            "typedef enum {A,B} E; int g[2] = {[B] = 9}; int main(void){ return g[1]; }"
        )
        struct = (
            "struct S{int B;}; struct S s = {.B = 9}; int main(void){ return s.B; }"
        )
        assert run(array) == 9
        assert run(struct) == 9


class TestNestedDesignators:
    def test_struct_in_struct(self):
        source = """
            struct P { int v; };
            struct S { struct P p; };
            struct S s = { .p.v = 6 };
            int main(void) { return s.p.v; }
        """
        assert run(source) == 6

    def test_array_in_array(self):
        assert (
            run("int g[2][2] = { [1][0] = 7 }; int main(void){ return g[1][0]; }") == 7
        )

    def test_three_levels(self):
        source = """
            struct A { int v; };
            struct B { struct A a; };
            struct C { struct B b; };
            struct C c = { .b.a.v = 3 };
            int main(void) { return c.b.a.v; }
        """
        assert run(source) == 3

    def test_index_then_member(self):
        source = """
            typedef enum { A, B } E;
            struct S { int v; };
            struct S g[2] = { [B].v = 8 };
            int main(void) { return g[1].v; }
        """
        assert run(source) == 8

    def test_member_designator_on_non_struct_rejected(self):
        """`int g[2] = { .x = 1 };` 不合法：数组那边会把它当**下标表达式**求值。

        两种设计符形状一样（都是 `ID`），只能按目标类型解释——所以这里的报错是
        "未定义的标识符 'x'"，而不是"这不是成员"。**报错**才是重点：不能悄悄忽略。
        """
        source = "int g[2] = { .x = 1 }; int main(void){ return 0; }"
        with pytest.raises(DomainError):
            run(source)


class TestCompoundLiteral:
    """`(T){...}` —— C99 的复合字面量。"""

    def test_as_value(self):
        source = """
            struct S { int x, y; };
            int main(void) { struct S s = (struct S){1, 2}; return s.y; }
        """
        assert run(source) == 2

    def test_address_of(self):
        source = """
            struct S { int x, y; };
            int main(void) { struct S *p = &(struct S){3, 4}; return p->x; }
        """
        assert run(source) == 3

    def test_as_function_argument(self):
        source = """
            struct S { int x; };
            int f(struct S s) { return s.x; }
            int main(void) { return f((struct S){9}); }
        """
        assert run(source) == 9

    def test_array_literal(self):
        assert run("int main(void){ int *p = (int[]){5,6}; return p[1]; }") == 6

    def test_string_literal_in_braces(self):
        assert run('int main(void){ char *p = (char[]){"hi"}; return strlen(p); }') == 2

    def test_each_evaluation_is_a_new_object(self):
        """`&(int){...}` 在循环里每次都是新对象（C 也一样）。"""
        source = """
            int main(void) {
                int *a = &(int){1};
                int *b = &(int){2};
                return (*a == 1 && *b == 2) ? 1 : 0;
            }
        """
        assert run(source) == 1


class TestArrayDecay:
    """数组在求值语境里退化成指向首元素的指针（C99 6.3.2.1）。"""

    def test_element_of_two_dimensional_array(self):
        assert (
            run('char g[][4] = {"ab","cd"}; int main(void){ return strlen(g[1]); }')
            == 2
        )

    def test_local_two_dimensional(self):
        source = """
            int main(void) {
                char g[2][4] = {"ab","cd"};
                return strlen(g[1]);
            }
        """
        assert run(source) == 2

    def test_array_member_of_struct(self):
        source = """
            struct S { char n[4]; };
            struct S g[2] = {{"ab"},{"cd"}};
            int main(void) { return strlen(g[1].n); }
        """
        assert run(source) == 2

    def test_sizeof_still_counts_whole_array(self):
        """退化只发生在求值语境；`sizeof` 拿到的还是数组本身。"""
        assert run("char g[2][4]; int main(void){ return sizeof(g); }") == 8
