"""应用层用例：拿 Scope + TypeResolver + MemoryPort 拼出一个能跑的最小运行时。

这一层是三轮成果的汇合点：

    Scope        管名字（变量名、typedef 名、标签）
    TypeResolver 管类型（sizeof / offsetof / 成员类型）
    MemoryPort   管存储（地址、越界、悬空）

用例只依赖端口，所以下面全部用真实的 ``SlotMemory``，不 mock。
"""

import pytest

from super_execute.application.ports import (
    FunctionTablePort,
    MemoryPort,
    TypeResolverPort,
)
from super_execute.application.use_cases import (
    DeclareVariable,
    DeclareVariableOfName,
    LoadValue,
    ReadVariable,
    ScopeSession,
    StoreValue,
    TakeAddress,
    WriteVariable,
)
from super_execute.domain.entities.c_types import (
    ArrayType,
    Member,
    PointerType,
    StructType,
)
from super_execute.domain.entities.symbol import (
    FunctionSymbol,
    TagSymbol,
    TypedefSymbol,
)
from super_execute.domain.exceptions import (
    DuplicateSymbolError,
    MemoryAccessError,
    NotAValueError,
    NullPointerError,
    UndefinedSymbolError,
    UndefinedTypeError,
    UnresolvedTypeError,
)
from super_execute.domain.services.addressing import element_address, member_address
from super_execute.domain.services.builtin_types import INT, SHORT
from super_execute.domain.services.scope_id_allocator import ScopeIdAllocator
from super_execute.domain.services.type_resolver import TypeResolver
from super_execute.domain.value_objects import (
    Address,
    AddressRegion,
    ScopeKind,
    TagKind,
)
from super_execute.frameworks.memory import FunctionTable, SlotMemory


@pytest.fixture
def runtime():
    """一套最小运行时：作用域会话 + 内存 + 类型解析器 + 用例。"""
    allocator = ScopeIdAllocator()
    memory = SlotMemory()
    session = ScopeSession(allocator, memory)
    file_scope = session.open(ScopeKind.FILE)

    return {
        "session": session,
        "memory": memory,
        "scope": file_scope,
        "declare": DeclareVariableOfName(memory, TypeResolver()),
        "declare_typed": DeclareVariable(memory),
        "read": ReadVariable(memory),
        "write": WriteVariable(memory),
        "take_address": TakeAddress(),
        "load": LoadValue(memory),
        "store": StoreValue(memory),
    }


class TestPorts:
    def test_components_satisfy_the_ports(self, runtime):
        assert isinstance(runtime["memory"], MemoryPort)
        assert isinstance(FunctionTable(), FunctionTablePort)
        assert isinstance(TypeResolver(), TypeResolverPort)


class TestDeclareVariable:
    def test_declares_and_allocates(self, runtime):
        symbol = runtime["declare"](runtime["scope"], "x", ["int"])

        assert symbol.name == "x"
        assert symbol.ctype is INT
        assert symbol.address == Address(AddressRegion.SCOPE, 1, 0)
        assert runtime["scope"].find("x") is symbol

    def test_initial_value(self, runtime):
        runtime["declare"](runtime["scope"], "x", ["int"], initial=42)
        assert runtime["read"](runtime["scope"], "x") == 42

    def test_offsets_follow_alignment(self, runtime):
        c = runtime["declare"](runtime["scope"], "c", ["char"])
        i = runtime["declare"](runtime["scope"], "i", ["int"])
        assert (c.address.offset, i.address.offset) == (0, 4)

    def test_duplicate_rejected_without_wasting_storage(self, runtime):
        runtime["declare"](runtime["scope"], "x", ["int"])
        with pytest.raises(DuplicateSymbolError):
            runtime["declare"](runtime["scope"], "x", ["int"])

        # 失败的那次不能白吃 4 字节：y 应该紧接在 x 后面
        y = runtime["declare"](runtime["scope"], "y", ["int"])
        assert y.address.offset == 4

    def test_unknown_type(self, runtime):
        with pytest.raises(UndefinedTypeError):
            runtime["declare"](runtime["scope"], "x", ["NoSuchType"])

    def test_struct_variable(self, runtime):
        point = StructType("Point")
        point.define([Member("a", SHORT), Member("b", INT)])
        runtime["scope"].declare(TagSymbol("Point", TagKind.STRUCT, point))

        symbol = runtime["declare"](runtime["scope"], "p", ["struct", "Point"])
        assert symbol.ctype is point

    def test_uninitialized_aggregate_is_zero_filled(self, runtime):
        """`struct Point s; s.a = 1;` 必须能跑——成员容器要先存在。"""
        point = StructType("Point")
        point.define([Member("a", SHORT), Member("b", INT)])
        runtime["scope"].declare(TagSymbol("Point", TagKind.STRUCT, point))

        symbol = runtime["declare"](runtime["scope"], "s", ["struct", "Point"])
        assert runtime["read"](runtime["scope"], "s") == {"a": 0, "b": 0}

        # 直接写成员（不经整体赋值）
        address = member_address(symbol.address, point, "a")
        runtime["store"](address, 7, SHORT)
        assert runtime["read"](runtime["scope"], "s") == {"a": 7, "b": 0}

    def test_uninitialized_array_is_zero_filled(self, runtime):
        array = ArrayType(INT, 3)
        runtime["declare_typed"](runtime["scope"], "a", array)
        assert runtime["read"](runtime["scope"], "a") == [0, 0, 0]

    def test_uninitialized_pointer_is_null(self, runtime):
        runtime["declare_typed"](runtime["scope"], "p", PointerType(INT))
        assert runtime["read"](runtime["scope"], "p").is_null

    def test_typed_declaration_for_derived_types(self, runtime):
        """指针 / 数组的类型来自声明符，由调用方构造成 CType 后传进来。"""
        pointer = PointerType(INT)
        symbol = runtime["declare_typed"](runtime["scope"], "p", pointer)

        assert symbol.ctype is pointer
        assert symbol.ctype.sizeof() == 4

    def test_typed_declaration_requires_ctype(self, runtime):
        with pytest.raises(Exception):
            runtime["declare_typed"](runtime["scope"], "p", ["int"])


class TestReadWriteVariable:
    def test_roundtrip(self, runtime):
        runtime["declare"](runtime["scope"], "x", ["int"])
        runtime["write"](runtime["scope"], "x", 7)
        assert runtime["read"](runtime["scope"], "x") == 7

    def test_undeclared(self, runtime):
        with pytest.raises(UndefinedSymbolError):
            runtime["read"](runtime["scope"], "nope")

    def test_typedef_is_not_a_value(self, runtime):
        runtime["scope"].declare(TypedefSymbol("T", INT))
        with pytest.raises(NotAValueError, match="不是可以读写的变量"):
            runtime["read"](runtime["scope"], "T")

    def test_unresolved_type_rejected(self, runtime):
        runtime["declare"](runtime["scope"], "x", ["int"])
        runtime["scope"].find("x").ctype = None  # 模拟类型尚未解析
        with pytest.raises(UnresolvedTypeError):
            runtime["read"](runtime["scope"], "x")

    def test_inner_scope_shadows(self, runtime):
        session, scope = runtime["session"], runtime["scope"]
        runtime["declare"](scope, "x", ["int"], initial=1)

        block = session.open(ScopeKind.BLOCK, scope)
        runtime["declare"](block, "x", ["int"], initial=2)
        assert runtime["read"](block, "x") == 2
        assert runtime["read"](scope, "x") == 1


class TestTakeAddress:
    def test_variable_address(self, runtime):
        symbol = runtime["declare"](runtime["scope"], "x", ["int"])
        assert runtime["take_address"](runtime["scope"], "x") == symbol.address

    def test_function_address_from_table(self, runtime):
        table = FunctionTable()
        table.bind(FunctionSymbol("log_tx", Address(AddressRegion.FUNCTION, 0, 0)))
        take = TakeAddress(table)

        address = take(runtime["scope"], "log_tx")
        assert address.region is AddressRegion.FUNCTION
        assert table.resolve(address).name == "log_tx"

    def test_unknown_name(self, runtime):
        with pytest.raises(UndefinedSymbolError):
            runtime["take_address"](runtime["scope"], "nope")

    def test_typedef_has_no_address(self, runtime):
        runtime["scope"].declare(TypedefSymbol("T", INT))
        with pytest.raises(NotAValueError, match="没有地址可取"):
            runtime["take_address"](runtime["scope"], "T")


class TestPointerAccess:
    def test_load_through_pointer(self, runtime):
        """int *p = &x; *p 读到的就是 x。"""
        symbol = runtime["declare"](runtime["scope"], "x", ["int"], initial=9)
        assert runtime["load"](symbol.address, INT) == 9

    def test_store_through_pointer(self, runtime):
        symbol = runtime["declare"](runtime["scope"], "x", ["int"], initial=9)
        runtime["store"](symbol.address, 10, INT)
        assert runtime["read"](runtime["scope"], "x") == 10

    def test_null_dereference(self, runtime):
        null = Address.null()
        with pytest.raises(NullPointerError):
            runtime["load"](null, INT)
        with pytest.raises(NullPointerError):
            runtime["store"](null, 1, INT)

    def test_pointer_into_struct_member(self, runtime):
        """int *p = &s.b; *p = 5;  -- 成员地址就是普通地址（D5）。"""
        point = StructType("Point")
        point.define([Member("a", SHORT), Member("b", INT)])
        runtime["scope"].declare(TagSymbol("Point", TagKind.STRUCT, point))

        symbol = runtime["declare"](runtime["scope"], "s", ["struct", "Point"])
        runtime["write"](runtime["scope"], "s", {"a": 1, "b": 2})

        address = member_address(symbol.address, point, "b")
        assert runtime["load"](address, INT) == 2

        runtime["store"](address, 5, INT)
        assert runtime["read"](runtime["scope"], "s") == {"a": 1, "b": 5}

    def test_array_element_through_pointer(self, runtime):
        array = ArrayType(INT, 3)
        symbol = runtime["declare_typed"](runtime["scope"], "arr", array)
        runtime["write"](runtime["scope"], "arr", [10, 20, 30])

        address = element_address(symbol.address, array, 2)
        assert runtime["load"](address, INT) == 30


class TestScopeSession:
    def test_open_creates_memory(self, runtime):
        session, memory = runtime["session"], runtime["memory"]
        block = session.open(ScopeKind.BLOCK, runtime["scope"])
        assert memory.is_live(block.scope_id)

    def test_close_destroys_memory_and_releases_id(self, runtime):
        session, memory = runtime["session"], runtime["memory"]
        block = session.open(ScopeKind.BLOCK, runtime["scope"])
        address = runtime["declare"](block, "v", ["int"]).address

        session.close(block)

        assert not memory.is_live(block.scope_id)
        with pytest.raises(MemoryAccessError):
            memory.read(address, INT)

    def test_id_returned_when_memory_setup_fails(self):
        """建存储失败时 id 必须退回，否则 255 个 id 会被慢慢吃光。"""

        class _BrokenMemory(SlotMemory):
            def create_scope(self, scope_id):
                raise MemoryAccessError("模拟存储创建失败")

        allocator = ScopeIdAllocator()
        session = ScopeSession(allocator, _BrokenMemory())
        with pytest.raises(MemoryAccessError):
            session.open(ScopeKind.FILE)
        assert len(allocator) == 0

    def test_open_close_cycles_reuse_ids(self, runtime):
        session = runtime["session"]
        for _ in range(5):
            block = session.open(ScopeKind.BLOCK, runtime["scope"])
            session.close(block)

        block = session.open(ScopeKind.BLOCK, runtime["scope"])
        assert block.scope_id == 2  # 复用了最小的空闲 id


class TestFullScenario:
    def test_struct_pointer_and_member_flow(self, runtime):
        """把三轮的东西连起来跑一遍：定义结构体 → 声明 → 取地址 → 经指针读回。"""
        scope = runtime["scope"]

        point = StructType("Point")
        point.define([Member("a", SHORT), Member("b", INT)])
        scope.declare(TagSymbol("Point", TagKind.STRUCT, point))

        s = runtime["declare"](
            scope, "s", ["struct", "Point"], initial={"a": 1, "b": 2}
        )
        p = runtime["declare_typed"](scope, "p", PointerType(point))

        runtime["write"](scope, "p", s.address)
        stored = runtime["read"](scope, "p")

        assert stored == s.address
        # 经指针地址读回整个结构体
        assert runtime["load"](stored, point) == {"a": 1, "b": 2}
        # 指针变量本身也占了存储
        assert p.ctype.sizeof() == 4
