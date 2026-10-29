# super_execute · 类型系统（CType + 结构体布局 + 类型名解析）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, types, layout

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261017-122900) Scope 领域层

> **review 后续**：本任务交付后经两轮独立评审，发现的 1 个 P0（布局冻结 vs 类型
> 可变）与 7 个 P1（非法 C 结构静默通过等）已在 Task(20261029-153619) 修完，
> 测试从 249 增至 295，变异测试 13/13 全杀。

## 本步范围

`super_execute/super_execute/domain/` 下的最小类型系统。**不做**：位域、类型限定符
（const/volatile）、long double、常量折叠、类型转换（promote/usual_convert）、内存。

## 为什么类型必须在内存之前

`ScopeMemory.allocate()` 要发一个偏移，就必须先知道 `sizeof`/`alignof`。
没有类型系统，连"这个变量占几字节"都算不出来。所以顺序是
Scope → 类型 → 内存 → 用例。

## 关键裁决

- **指针 4 字节**（`POINTER_SIZE = ADDRESS_SIZE`）。宿主 gcc 是 8，这是刻意的
  偏离：只有指针宽度等于 `Address` 宽度，"指针就是一个地址"才闭合。因此凡是
  结构体里含指针的布局都与宿主 ABI 不同，**黄金值测试只用标量成员**。
- **标量尺寸取 LLP64**：`long` 是 4 字节（与宿主 mingw 一致），`long long` 8。
- **位域不做**：`Member.bit_width` 保留字段但传非 None 直接抛
  `UnsupportedTypeError`，等单独一轮（要把成员模型扩成"偏移+位偏移+位宽"）。
- **布局逻辑放在 `StructType.define()` 内部**，没单开 `services/layout.py`：
  布局是结构体自己的不变量，放服务层会造成 entities → services 的反向依赖。
  需要单独计算布局的调用方，用 `StructType.offsetof()` 即可。

## 黄金值来源

布局期望值全部由宿主 gcc 现算，不是手抄。源码与重算命令记在
`tests/unit/domain/test_layout.py` 的 `GCC_SOURCE` 常量里：

    struct A { char a; int b; short c; };                    → size=12 align=4
    struct B { char a; double b; char c; };                  → size=24 align=8
    struct C { short a; char b; };                           → size=4  align=2
    struct D { char a[3]; int b; char c; };                  → size=12 align=4
    struct E { char a; struct C c; int d; };                 → size=12 align=4
    struct F { double a; char b; };                          → size=16 align=8
    union  U { char a; double b; int c; };                   → size=8  align=8

## 验收

- `pytest super_execute/tests` → **249 passed**（scope 119 + 类型 130）
- 仓库既有 264 个测试不回归（6 skipped）
- 上一轮四条实证在类型解析层面闭环：
  `test_sibling_functions_resolve_their_own_struct_p`（4 + 12 = 16）
  `test_block_typedef_does_not_leak_into_resolution`（40 → 出块恢复 int）

## 下一步

`MemoryPort` + `SlotMemory`：让 `Address` 真的可解引用，并收掉 D3 留下的
"作用域销毁后解引用必须报错"这一半。
