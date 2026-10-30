# super_execute · interface adapter（AST → 用例）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, adapter, pycparser

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261029-160502) 用例层

## 目标

让新架构能吃**真实的 C 源码**：把 pycparser 的 AST 翻译成领域对象与用例调用。

    AST 声明符   → CType      （type_builder）
    AST 顶层声明 → 用例调用    （declaration_loader）

这一层认识 pycparser，用例不认识——所以所有 `isinstance(node, c_ast.Xxx)` 只出现在
这里，下游一律是领域对象。将来换 Clang AST 或自研 parser，只换这一层。

## 交付

```
interface_adapters/ast/type_builder.py       声明符 → CType
interface_adapters/ast/declaration_loader.py FileAST 顶层 → 用例
application/use_cases/functions.py           DeclareFunction（函数进函数表）
tests/unit/interface_adapters/               conftest + 2 个测试文件（50 个用例）
```

`DeclareVariable` 顺带加了 `linkage` 参数（static 的内部链接）。

## 覆盖的声明符形状

`int x` / `unsigned long x` / `MyTypedef x` / `int *p` / `int **p` / `int a[3]` /
`int a[2][3]` / `int *a[3]` / `int (*p)[4]` / `int f(int,char)` / `int f(void)` /
`int printf(char*,...)` / `struct` / `union` / `enum`（含自增与负值）/
匿名 struct / 自引用 struct / 前向声明后补定义 / 弹性数组成员。

## 测试抓到的真实语义 bug

**块内同名标签应该遮蔽外层，而不是重复定义。**

最初 `_tag_type` 沿作用域链查标签，于是块里写 `struct P { ... }` 时找到外层的
完整 `struct P`，再 `define()` 就报"已经定义过了"。正确规则是 C99 6.2.1/6.7.2.3：

- **带定义**（有成员/枚举值）→ 一定是本层的新类型，外层同名标签被**遮蔽**；
- **不带定义**（`struct S;` / `struct S *p;`）→ 先在链上找可见的同名标签；
- 本层已有（前置声明后补定义）→ 复用本层那个，再定义成员。

自引用 `struct Node { struct Node *next; }` 靠"先登记标签、后定义成员"成立。

## 验收

- `pytest super_execute/tests` → **465 passed**（原 415，+50）
- 仓库根 `pytest` → 729 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- **变异测试 11/11 全部杀死**（指针退化成目标类型、数组长度恒 None、函数忽略形参、
  变参标记丢失、标签不复用、枚举常量不入作用域、枚举自增失效、负号被忽略、
  链接属性恒 NONE、初值被丢弃、typedef 不登记）

## 实测：真实仓库文件

`test/multi/lib.c` 原样装载（无 #include，不必过 cpp）：

```
ordinary Pt       TypedefSymbol   -> struct Pt (size=8)
ordinary helper   FunctionSymbol  int ()          @function#0
ordinary sum_pt   FunctionSymbol  int (struct Pt) @function#1
tag      Pt       struct          size=8 align=4  x@0 y@4
typedef Pt 指向同一类型: True
```

## 下一步

表达式求值与语句执行：`BinaryOp`/`UnaryOp`/`Assignment`/`If`/`While`/`Return` +
lvalue 解析（`s.m`、`p->m`、`a[i]`、`*p`）。做完就能真的"跑"上面那个 lib.c 里的
`helper()` 与 `sum_pt()`。
