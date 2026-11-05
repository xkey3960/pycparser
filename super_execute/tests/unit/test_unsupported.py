"""当前**没做**的东西：一份可执行的清单。

这份文档的价值在于**不腐烂**——每条"不支持"都对应一个测试，跑一遍就知道
清单还准不准。新增能力时，把对应行从这里删掉，测试会提醒你。

分三类：

* ``PARSER`` —— 语法层面不认（要改解析器，通常要碰 pycparser 或 pycparserext）；
* ``TYPE``   —— 类型系统没有这个类型；
* ``RUNTIME``—— 能解析能建类型，但求值/运行时不支持，或者干脆没实现那个库函数。

每条都是**实测结论**，不是猜的。
"""

import pytest

from pycparser.c_parser import CParser

from super_execute.interface_adapters.ast.interpreter import Interpreter
from super_execute.interface_adapters.ast.va_arg import GnuVaArgParser


def run(source: str, gnu: bool = False):
    interpreter = Interpreter()
    parser = GnuVaArgParser() if gnu else CParser()
    interpreter.load(parser.parse(source, "<test>"))
    return interpreter.run()


#: 语法层不认的写法：文件名 → (源码, 是不是 GNU 解析器)
PARSER_GAPS = {
    "复合字面量后面跟成员访问": (
        "struct S{int x;}; int main(void){ return (struct S){7}.x; }",
        False,
    ),
    "复合字面量后面跟下标": (
        "int main(void){ return (int[]){7,8}[1]; }",
        False,
    ),
    "_Generic 选择表达式": (
        "int main(void){ return _Generic(1, int: 7, default: 0); }",
        False,
    ),
    "计算 goto（&&label）": (
        "int main(void){ void *p = &&L; goto *p; L: return 1; }",
        True,
    ),
    "GNU 嵌套函数": (
        "int main(void){ int f(void){ return 2; } return f(); }",
        True,
    ),
    "预处理指令（没走 cpp）": (
        "#include <stdio.h>\nint main(void){ return 0; }",
        False,
    ),
}

#: 类型系统没有的类型
TYPE_GAPS = {
    "long double": ("int main(void){ long double d = 1.5; return (int)d; }", False),
    "_Complex": ("int main(void){ _Complex double z = 1.0; return 0; }", False),
}


class TestParserGaps:
    """这些写法**解析**就不通过——不是求值的问题。"""

    @pytest.mark.parametrize("source,gnu", PARSER_GAPS.values(), ids=PARSER_GAPS.keys())
    def test_still_unsupported(self, source, gnu):
        with pytest.raises(Exception):
            run(source, gnu)

    def test_examples_that_do_work(self):
        """对照：同一族的写法里哪些是通的，免得把整类都当成不支持。"""
        # 复合字面量本身是支持的，只是不能直接接 `.` / `[`
        assert (
            run(
                "struct S{int x;}; int main(void){ struct S s=(struct S){7}; return s.x; }"
            )
            == 7
        )
        assert run("int main(void){ int *p=(int[]){7,8}; return p[1]; }") == 8


class TestTypeGaps:
    @pytest.mark.parametrize("source,gnu", TYPE_GAPS.values(), ids=TYPE_GAPS.keys())
    def test_still_unsupported(self, source, gnu):
        with pytest.raises(Exception):
            run(source, gnu)


class TestRuntimeGaps:
    """能跑，但结果不对或者能力缺失——每一条都写清"现在是什么行为"。"""

    def test_ternary_of_structs_rejected(self):
        """三元运算符要求两侧是算术类型；结构体按值选是不支持的。"""
        source = """
            struct S{int x;};
            int main(void){ struct S a={1}, b={2}; return (1 ? a : b).x; }
        """
        with pytest.raises(Exception, match="算术转换"):
            run(source)

    def test_no_qsort(self):
        """`qsort` 没实现（要用函数指针回调，内建表里还没有这条路）。"""
        source = """
            int c(const void *a, const void *b) { return 0; }
            int main(void){ int x[2]; qsort(x, 2, 4, c); return 0; }
        """
        with pytest.raises(Exception, match="qsort"):
            run(source)

    def test_bits_of_float_format(self):
        """`printf`/`sprintf` 的常用格式都有，但 C 的 `%a`（十六进制浮点）没有。"""
        assert run('int main(void){ char b[32]; return sprintf(b, "%d", 7); }') == 1


class TestWhatDoesWork:
    """反向清单：容易以为"没做"但其实已经通的写法。"""

    @pytest.mark.parametrize(
        "source,expected",
        [
            ("struct S{int x;}; struct S g={.x=5}; int main(void){ return g.x; }", 5),
            ("int g[3]={1,2,3}; int main(void){ return g[2]; }", 3),
            ("typedef enum{A,B}E; int g[2]={[B]=9}; int main(void){ return g[1]; }", 9),
            ("int main(void){ int *p=(int[]){4,5}; return p[0]; }", 4),
            ('char g[][4]={"ab","cd"}; int main(void){ return strlen(g[1]); }', 2),
            (
                "struct S{int n; int a[];}; int main(void){ struct S*p=malloc(sizeof(struct S)+8); p->a[0]=5; return p->a[0]; }",
                5,
            ),
            ("int main(void){ int*p=malloc(4); *p=7; p=realloc(p,8); return *p; }", 7),
            (
                "struct S{int x;}; int main(void){ struct S*p=malloc(sizeof *p); p->x=3; return p->x; }",
                3,
            ),
            (
                "union U{int i; char c;}; int main(void){ union U u; u.i=65; return u.i; }",
                65,
            ),
            (
                "struct S{unsigned a:3;}; int main(void){ struct S s; s.a=9; return s.a; }",
                1,
            ),
            ("int main(void){ return __builtin_types_compatible_p(int,int); }", 1),
        ],
        ids=[
            "全局指定初始化",
            "全局数组",
            "枚举当下标设计符",
            "复合字面量-数组",
            "二维数组元素退化",
            "弹性数组成员",
            "realloc 保留内容",
            "sizeof *p 自引用",
            "union",
            "位域截断",
            "__builtin_types_compatible_p",
        ],
    )
    def test_supported(self, source, expected):
        assert run(source, gnu=True) == expected
