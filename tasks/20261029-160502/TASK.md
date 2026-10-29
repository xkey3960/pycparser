# super_execute · application 用例层（声明 / 读写 / 取地址 / 指针访问）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, application, use-cases

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261029-154505) 内存端口

## 目标

把前三轮的三块拼起来，形成"能跑一个最小 C 运行时"的用例层：

    Scope        管名字（变量名、typedef 名、标签）
    TypeResolver 管类型（sizeof / offsetof / 成员类型）
    MemoryPort   管存储（地址、越界、悬空）

## 交付

```
application/ports/type_resolver_port.py   TypeResolverPort
application/ports/function_table_port.py  FunctionTablePort
application/use_cases/scope_session.py    ScopeSession（进/出作用域）
application/use_cases/variables.py        DeclareVariable / DeclareVariableOfName
                                          ReadVariable / WriteVariable
application/use_cases/address.py          TakeAddress（&x / &func）
application/use_cases/memory_access.py    LoadValue / StoreValue（*p / *p = v）
domain/services/addressing.py             member_address / element_address（D5）
```

## 实现中修正的一处划分

原计划 `DeclareVariable` 同时接受"类型名列表"，做到一半发现撑不住：
C 的**声明符**比类型名丰富——`int x` 的类型来自名字（`IdentifierType`），而
`struct P *p` / `int a[3]` 的类型来自声明符上的 `PtrDecl` / `ArrayDecl`。
硬塞进一个类型名参数，迟早要在里面拼 `"*"` 这种伪语法。

于是拆成两个用例：
- `DeclareVariable(memory)` 收**已解析的 CType**（派生类型由适配器从声明符构造）
- `DeclareVariableOfName(memory, resolver)` 收**类型名**，内部解析后委托前者

## 几个刻意的行为

- **先查重再分配**：内存是单调向前的，重复声明不能白吃一段存储
  （测试用"失败后下一个变量的偏移"钉住了这点）。
- **解引用 NULL 在用例层拦**，不在内存层：内存只看到"0 号作用域 0 偏移"，
  它不知道那代表空指针；这是语言语义。
- **`&T`（typedef）报错**：符号分"有存储/无存储"两类的意义就在这里。

## 验收

- `pytest super_execute/tests` → **399 passed**（原 355，+44）
- 仓库根 `pytest` → 663 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- **变异测试 12/12 全部杀死**（不查重、先分配后查重、不写初值、不绑作用域、
  读不校验类别/ctype、取址不查函数表、NULL 不拦、存储失败不退回 id、
  关作用域不归还 id、成员地址不取 offset、元素地址不乘下标）

## 下一步

interface adapter：把 pycparser 的 AST 映射到这些用例（`Decl`/`Typedef`/`StructRef`/
`ArrayRef`/`UnaryOp(&,*)`→ 用例调用），再往上才是表达式求值器和语句执行器。
