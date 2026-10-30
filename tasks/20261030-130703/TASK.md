# super_execute · 常量折叠 + 全局初值（strangler 第二轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, const-fold, init

父任务：Task(20261012-144135)；前置：Task(20261030-125604) strangler 兼容层

## 按计划做的两件事

### 1. 常量折叠（`interface_adapters/ast/const_eval.py`）

`fold(node, scope, resolver)` 在编译期把表达式算成整数。两种非它不可的场合：

```c
int arr[10 + 5];                  /* 数组维度 */
enum E { A = 1 + 1, B = A * 3 };  /* 枚举值，且能引用前面的枚举常量 */
```

支持：整型/字符字面量、枚举常量、算术/位运算、比较与逻辑、`sizeof`、整型强转、三目。
折不动返回 `None`，由调用方决定报错还是推迟。

顺带把 `c_div` / `c_mod` 抽到 `domain/services/arithmetic.py`——求值器和折叠器
必须共用同一份"向零截断"语义，各写一份迟早漂开。

### 2. 全局初值可以调用函数

```c
int g = helper_gv();   /* 函数定义可能在另一个文件里 */
```

`DeclarationLoader` 现在把折不动的初值记进 `deferred_initializers`，
`Interpreter` 在**所有翻译单元装载完之后**统一求值（那时函数表和函数体才齐），
且只做一次（初始化过程中调用的函数会再进 `call()`，不能递归触发）。

## 结果：17 → 20，但**增量主要不来自这两件事**

| 修复 | 影响 |
|---|---|
| **struct 赋值拷贝**（`_detach`） | `test_exe` 过了（397 字节的 `test/main.c` 跑出 **165**）、三文件端到端过了 |
| **枚举常量跨文件去重** | 三个文件重复定义同一份 `enum Color` 不再报重复 |
| **同名函数定义取第一份** | 多个 `main` 时旧实现取第一个，现在一致 |
| 常量折叠 / 全局初值 | 各解锁少量用例 |

`test_exe.py` 从 0/1 变 1/1 是这一轮最有分量的：它跑的是仓库里真实存在的
`test/main.c`，覆盖跨文件、struct、指针、控制流的组合，期望值 165。

### 最有价值的发现：`q = p` 的别名

三文件端到端原先给出 **206**（期望 116），不是报错而是**错答案**——更危险。
定位到 `Point q = p;` 之后 `q.x = 100` 改到了 `p`：Phase A 的复合值是 dict，
直接存进槽位就成了引用共享。

这正是**最早那次代码 review 的 P0**（"struct 赋值不拷贝，产生别名"）。
旧实现有这个问题，新实现在没有测试盯着的地方原样复现了它。修复是在
`SlotMemory.write` 里写入前 `deepcopy` 复合值（`_detach`），两条写入路径都覆盖。

## 我的优先级判断错了

上一轮我按"影响面"排了缺口顺序，把常量折叠和全局初值排在前面。
实际做完只拿到 +3，而顺手发现的 struct 拷贝问题一次拿下 2 个用例（含最重的
`test_exe`）。

原因：那 17 个"缺功能"里真正卡住大多数用例的是**惰性装载语义**
（`lazy_bad.c` 故意写坏的类型不该在装载时报错）、**冲突诊断的 strict/warn 两档**、
**GNU 扩展解析**、**类型双关**、**coord 错误定位**——常量折叠只是其中一小块。

度量工具的价值就在这里：它证伪了拍脑袋的排序。

## 当前度量（61 个旧用例 × 新实现）

```
总计: 20 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   11 / 40
test_qol2.py       7 / 18
test_print_pointer 0 / 1
```

| 类别 | 数量 | 典型原因 |
|---|---|---|
| 缺功能 | 17 | 惰性装载（4）、单节点 `execute()`（1）、函数指针调用（1）、`goto`（1）、GNU 解析（2）、类型双关（2）、`_Static_assert`（1）等 |
| 语义 / 消息差异 | 10 | 冲突是告警还是报错、入口取第一个的告警文案、错误消息缺 coord |
| 断言旧内部 | 5 | 断言 `g_scope._symbols` / `g_source_index`，兼容层下无意义 |
| 其余 | 9 | static 文件级隔离、隐式类型转换（38.1 vs 38）、struct tag 重复定义时机等 |

## 下一轮建议（这次基于数据）

1. **惰性装载语义**（4 个）——`lazy=True` 时坏文件不报错，用到才报。
2. **隐式类型转换**（2+）——`int x = 3.1` 要截断成 3；现在存的是 38.1。
3. **static 文件级隔离**（1）——同名的 `static int g;` 在两个文件里应能共存（D6）。
4. **coord 错误定位**（1+）——错误消息要带源码位置，这是 QOL-1 的核心价值。
5. GNU 扩展解析（2）、函数指针调用（1）、`goto`（1）……

## 验收

- `pytest super_execute/tests` → **627 passed**（原 610，+17）
- 仓库根 `pytest` → 891 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 20/61（可复现）
