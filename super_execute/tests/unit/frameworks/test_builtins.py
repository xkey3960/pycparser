"""内建函数：C 标准库最小实现的单元测试。

分两层测：

* 直接调 ``BuiltinTable`` —— 精确控制参数与内存，测字符串/内存函数的语义；
* 通过 ``Interpreter`` 跑 C 代码 —— 测**隐式声明**（没 ``#include`` 也能用）与
  ``printf`` 的真实输出。
"""

import pytest

from super_execute.application.ports.builtin_port import ProgramExit
from super_execute.domain.entities.c_types import ArrayType
from super_execute.domain.services.builtin_types import CHAR, INT
from super_execute.frameworks.builtins import BuiltinTable
from super_execute.frameworks.memory import SlotMemory
from super_execute.interface_adapters.ast.interpreter import Interpreter
from pycparser.c_parser import CParser


def run(source: str):
    interpreter = Interpreter()
    interpreter.load(CParser().parse(source, "<test>"))
    return interpreter.run()


@pytest.fixture
def table():
    return BuiltinTable(SlotMemory())


@pytest.fixture
def string_pool():
    """把 C 字符串放进堆区，返回地址（模拟字符串字面量）。"""
    memory = SlotMemory()
    table = BuiltinTable(memory)

    def make(text: str):
        payload = [ord(char) for char in text] + [0]
        return memory.allocate_heap(ArrayType(CHAR, len(payload)), payload)

    table.pool = make
    return table


class TestOutput:
    """``printf`` 的第一个参数在 C 里是 ``char *``，所以表层面要传地址。"""

    def test_printf_formats_int(self, string_pool, capsys):
        assert string_pool.call("printf", [string_pool.pool("%d"), 42]) == 2
        assert capsys.readouterr().out == "42"

    def test_printf_percent_is_literal(self, string_pool, capsys):
        string_pool.call("printf", [string_pool.pool("100%%")])
        assert capsys.readouterr().out == "100%"

    def test_printf_multiple_arguments(self, string_pool, capsys):
        string_pool.call("printf", [string_pool.pool("%d-%d"), 1, 2])
        assert capsys.readouterr().out == "1-2"

    def test_printf_strips_length_modifier(self, string_pool, capsys):
        """`%ld` 在 Python 里没有对应写法，去掉长度修饰符即可。"""
        string_pool.call("printf", [string_pool.pool("%ld"), 7])
        assert capsys.readouterr().out == "7"

    def test_printf_hex(self, string_pool, capsys):
        string_pool.call("printf", [string_pool.pool("%x"), 255])
        assert capsys.readouterr().out == "ff"

    def test_puts_adds_newline(self, string_pool, capsys):
        address = string_pool.pool("hi")
        string_pool.call("puts", [address])
        assert capsys.readouterr().out == "hi\n"

    def test_putchar(self, table, capsys):
        table.call("putchar", [ord("A")])
        assert capsys.readouterr().out == "A"


class TestStrings:
    def test_strlen(self, string_pool):
        assert string_pool.call("strlen", [string_pool.pool("hello")]) == 5

    def test_strlen_empty(self, string_pool):
        assert string_pool.call("strlen", [string_pool.pool("")]) == 0

    def test_strcmp_equal(self, string_pool):
        assert (
            string_pool.call(
                "strcmp", [string_pool.pool("abc"), string_pool.pool("abc")]
            )
            == 0
        )

    def test_strcmp_less_and_greater(self, string_pool):
        assert (
            string_pool.call(
                "strcmp", [string_pool.pool("abc"), string_pool.pool("abd")]
            )
            < 0
        )
        assert (
            string_pool.call(
                "strcmp", [string_pool.pool("abd"), string_pool.pool("abc")]
            )
            > 0
        )

    def test_strncmp_stops_early(self, string_pool):
        assert (
            string_pool.call(
                "strncmp", [string_pool.pool("abcX"), string_pool.pool("abcY"), 3]
            )
            == 0
        )

    def test_strcpy_returns_destination(self, string_pool):
        memory = SlotMemory()
        table = BuiltinTable(memory)

        def make(text):
            payload = [ord(char) for char in text] + [0]
            return memory.allocate_heap(ArrayType(CHAR, len(payload)), payload)

        destination = make("xxxxx")
        source = make("hi")
        result = table.call("strcpy", [destination, source])
        assert result == destination
        assert table._read_cstr(destination) == "hi"

    def test_strcat_appends(self, string_pool):
        memory = SlotMemory()
        table = BuiltinTable(memory)

        def make(text):
            payload = [ord(char) for char in text] + [0]
            return memory.allocate_heap(ArrayType(CHAR, len(payload)), payload)

        destination = make("ab")
        table.call("strcat", [destination, make("cd")])
        assert table._read_cstr(destination) == "abcd"


class TestMemory:
    def test_malloc_gives_addressable_storage(self, table):
        address = table.call("malloc", [8])
        assert not address.is_null

    def test_malloc_then_write_and_read(self, table):
        """`int *p = malloc(4); *p = 7;` —— 裸内存要能按 int 访问。"""
        memory = table._memory
        address = table.call("malloc", [4])
        memory.write(address, 7, INT)
        assert memory.read(address, INT) == 7

    def test_calloc_is_zeroed(self, table):
        memory = table._memory
        address = table.call("calloc", [4, 1])
        assert memory.read(address, INT) == 0

    def test_free_is_noop(self, table):
        address = table.call("malloc", [4])
        assert table.call("free", [address]) is None

    def test_memset_fills_bytes(self, table):
        memory = table._memory
        address = table.call("malloc", [4])
        table.call("memset", [address, 65, 4])
        assert [memory.read(address.advanced(i), CHAR) for i in range(4)] == [65] * 4

    def test_memcpy_copies(self, table):
        memory = table._memory
        source = table.call("malloc", [4])
        destination = table.call("malloc", [4])
        for index in range(4):
            memory.write(source.advanced(index), index + 1, CHAR)
        table.call("memcpy", [destination, source, 4])
        assert [memory.read(destination.advanced(i), CHAR) for i in range(4)] == [
            1,
            2,
            3,
            4,
        ]

    def test_out_of_bounds_write_rejected(self, table):
        memory = table._memory
        address = table.call("malloc", [2])
        with pytest.raises(Exception, match="放不下|越界"):
            memory.write(address, 7, INT)


class TestScalarHelpers:
    def test_abs(self, table):
        assert table.call("abs", [-3]) == 3

    def test_atoi(self, string_pool):
        assert string_pool.call("atoi", [string_pool.pool("-42xyz")]) == -42

    def test_sqrt(self, table):
        assert table.call("sqrt", [9.0]) == 3.0

    def test_isdigit(self, table):
        assert table.call("isdigit", [ord("7")]) == 1
        assert table.call("isdigit", [ord("x")]) == 0

    def test_toupper(self, table):
        assert table.call("toupper", [ord("a")]) == ord("A")

    def test_exit_raises(self, table):
        with pytest.raises(ProgramExit) as info:
            table.call("exit", [3])
        assert info.value.code == 3


class TestImplicitDeclaration:
    """没 `#include <stdio.h>` 也能用——像 C89 那样替它补上声明。"""

    def test_printf_without_header(self, capsys):
        source = 'int main(void) { printf("%d", 7); return 0; }'
        assert run(source) == 0
        assert capsys.readouterr().out == "7"

    def test_strlen_without_header(self):
        assert run('int main(void) { return strlen("hello"); }') == 5

    def test_malloc_without_header(self):
        source = """
            struct Point { int x; int y; };
            int main(void) {
                struct Point *p = malloc(sizeof(struct Point));
                p->x = 3;
                p->y = 4;
                return p->x * 10 + p->y;
            }
        """
        assert run(source) == 34

    def test_user_definition_wins(self, capsys):
        """自己写了同名函数，就该用自己的。"""
        source = """
            int puts(char *s) { return 99; }
            int main(void) { return puts("x"); }
        """
        assert run(source) == 99
        assert capsys.readouterr().out == ""

    def test_exit_sets_program_result(self):
        source = "int main(void) { exit(5); return 0; }"
        assert run(source) == 5

    def test_exit_inside_function(self):
        source = "int f(void) { exit(8); return 1; } int main(void) { return f(); }"
        assert run(source) == 8
