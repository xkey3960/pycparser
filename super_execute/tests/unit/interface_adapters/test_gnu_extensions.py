"""GNU 扩展解析器（pycparserext）下的适配。

为什么需要单独一组：新实现本身不解析源码，但**节点形状**会因解析器而变。
朴素 ``CParser`` 产出 ``c_ast.FuncDecl``，``GnuCParser`` 产出 ``FuncDeclExt``——
后者**不是** ``c_ast.FuncDecl`` 的子类（其余 Ext 节点 ``TypeDeclExt`` /
``ArrayDeclExt`` / ``StructExt`` 都是子类），所以适配器必须显式认它。

没装 pycparserext 时整组跳过：那是可选依赖，降级到朴素解析器仍能跑大部分 C。
"""

import pytest

from super_execute.domain.entities.c_types import (
    ArrayType,
    FunctionType,
    PointerType,
    StructType,
)
from super_execute.interface_adapters.ast.interpreter import Interpreter

pytest.importorskip("pycparserext", reason="没装 pycparserext，GNU 扩展不可用")

from pycparserext.ext_c_parser import GnuCParser  # noqa: E402


def parse(source: str):
    return GnuCParser().parse(source, "<gnu>")


def run(source: str):
    interpreter = Interpreter()
    interpreter.load(parse(source))
    return interpreter.run()


class TestFunctionDeclarator:
    """``FuncDeclExt`` 不是 ``c_ast.FuncDecl`` 的子类，必须显式认。"""

    def test_function_declarator_yields_function_type(self, builder):
        ctype = builder.build(parse("int g(int a);").ext[0].type)
        assert isinstance(ctype, FunctionType)
        assert ctype.ret.name == "int"

    def test_ordinary_program_still_runs(self):
        source = """
            int add(int a, int b) { return a + b; }
            int main(void) { return add(20, 22); }
        """
        assert run(source) == 42


class TestTypeOf:
    """``typeof``：``TypeOfExpression`` / ``TypeOfDeclaration`` 两种形状。"""

    def test_typeof_in_sizeof(self):
        assert run("int main(void){ int x = 5; return sizeof(typeof(x)); }") == 4

    def test_typeof_in_declaration(self):
        source = """
            int main(void) {
                double d = 2.5;
                typeof(d) copy = d * 2;
                return (int)copy;
            }
        """
        assert run(source) == 5

    def test_typeof_pointer_declaration(self):
        source = """
            int main(void) {
                int *p;
                typeof(p) q = 0;
                return q == 0;
            }
        """
        assert run(source) == 1


class TestOffsetOf:
    """``offsetof`` 的经典写法：``&((T *)0)->m``。"""

    def test_offset_of_second_member(self):
        source = """
            struct P { int a; int b; };
            int main(void) { return (int)(unsigned long)&((struct P *)0)->b; }
        """
        assert run(source) == 4

    def test_offset_of_first_member_is_zero(self):
        source = """
            struct P { int a; int b; };
            int main(void) { return (int)(unsigned long)&((struct P *)0)->a; }
        """
        assert run(source) == 0

    def test_container_of_pattern(self):
        """由成员指针反推外层结构体指针——offsetof 的真实用途。"""
        # 宏要预处理，这里直接写展开后的形式
        source = """
            struct Node { int value; struct Node *next; };
            struct List { int count; struct Node node; };

            int main(void) {
                struct List list;
                list.count = 7;
                list.node.value = 42;

                struct Node *np = &list.node;
                unsigned long off = (unsigned long)&((struct List *)0)->node;
                struct List *lp = (struct List *)((char *)np - off);
                return lp->count * 10 + lp->node.value % 42;
            }
        """
        assert run(source) == 70  # offsetof(List, node) 是 4

    def test_null_pointer_arithmetic_still_rejected(self):
        """offsetof 是特例，普通的空指针算术不能因此放行。"""
        with pytest.raises(Exception, match="NULL"):
            run("int main(void){ int *p = 0; return *(p + 1); }")


class TestAttributes:
    def test_attribute_is_ignored(self):
        source = """
            struct S { int a; int b; } __attribute__((packed));
            int main(void) { struct S s; s.a = 3; s.b = 4; return s.a + s.b; }
        """
        assert run(source) == 7


class TestDeclaratorShapes:
    def test_array_of_struct(self, builder):
        ctype = builder.build(parse("struct P { int x; } arr[3];").ext[0].type)
        assert isinstance(ctype, ArrayType)
        assert ctype.count == 3
        assert isinstance(ctype.element, StructType)

    def test_function_pointer_declarator(self, builder):
        ctype = builder.build(parse("int (*fp)(int);").ext[0].type)
        assert isinstance(ctype, PointerType)
        assert ctype.target.name.startswith("int")
