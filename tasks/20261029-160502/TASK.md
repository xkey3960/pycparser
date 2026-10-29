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
domain/services/defaults.py               default_value（零初始化）
```

## 演示时发现的缺口：默认值

写演示（手写一遍 `struct Point s; s.a = 1;`）时崩了：新分配的槽里是 `None`，
成员写不进去。C 的自动变量是"不确定值"，但解释器不能真留空洞——否则这段
完全合法的 C 代码会失败。

补上 `default_value(ctype)`：标量 0、浮点 0.0（**类型也要对**）、指针 NULL、
数组逐元素、结构体/联合体逐成员；弹性数组成员给空表。
`DeclareVariable` 现在先铺零值再写初值。

这是**发现于演示而不是测试**的一类问题——测试只覆盖了"整体赋值后再读成员"，
没覆盖"声明后直接写成员"。

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

- `pytest super_execute/tests` → **415 passed**（原 355，+60）
- 仓库根 `pytest` → 679 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- **变异测试 17/17 全部杀死**
  - 用例层 12 个：不查重、先分配后查重、不写初值、不绑作用域、读不校验类别/ctype、
    取址不查函数表、NULL 不拦、存储失败不退回 id、关作用域不归还 id、
    成员地址不取 offset、元素地址不乘下标
  - 默认值 5 个：不铺零值、结构体给 None、数组给空表、浮点给 0、
    指针给 0（后两个靠"断言类型/身份"才杀掉——`0 == 0.0` 在 Python 里为真）

## 下一步

interface adapter：把 pycparser 的 AST 映射到这些用例（`Decl`/`Typedef`/`StructRef`/
`ArrayRef`/`UnaryOp(&,*)`→ 用例调用），再往上才是表达式求值器和语句执行器。
