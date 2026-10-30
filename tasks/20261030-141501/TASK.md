# super_execute · GNU 扩展第一批：①②③④（strangler 第八轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, gnu, initializer

父任务：Task(20261012-144135)；前置：Task(20261030-140220) 冲突诊断

按上一篇分析，先做**不需要 `GnuCParser`** 的四项：

| # | 项 | 结果 |
|---|---|---|
| ① | 零长数组 `char s[0]` | ✅ |
| ② | 初始化列表 `{1,2,3}` / `{{..},{..}}` | ✅ |
| ③ | 指定初始化器 `{.b=5}` / `{[1]=7}` | ✅ |
| ④ | 语句表达式 `({ ... })` | ✅ |

## ① 零长数组

`ArrayType` 原来拒绝 `count <= 0`。现在只拒绝负数，**0 是允许的**：

```python
assert ArrayType(INT, 0).is_complete   # 长度确定，只是为 0
assert ArrayType(INT).count is None    # 不完整数组才是 None
```

这个区分很重要：0 是"确定的空数组"，`None` 是"长度未定"。混在一起会让
`sizeof` 和弹性数组成员的判断都失准。

## ② 初始化列表

`{...}` 不是表达式——它**按目标类型铺开**，所以不能走普通 `eval`，必须带着类型递归：

```python
Evaluator.eval_init(init, ctype, scope)   # 新入口
```

- 数组：按下标填，缺的补 `default_value`
- 结构体/联合体：按成员顺序填
- 标量：`int x = {5}` 取第一项
- `int a[] = {1,2,3};` 的长度由初始化器决定（`ctype.complete(len(exprs))`，C99 6.7.9p22）

全局初值也走 `eval_init`（`_initialize_globals` 里用符号的 ctype）。

## ③ 指定初始化器

`{.b = 5}` / `{[1] = 7}` 与 ② 共用 `_init_list`，只是多一步"看设计符决定填哪个槽位"。

**一个 pycparser 的坑**：`[1]` 的设计符在 AST 里是 **`Constant`**，不是 `ArrayRef`
（`NamedInitializer.name[0]`）。两种都认了。

## ④ 语句表达式

`({ ... })` 出现在**表达式位置**时是 `Compound`。求值器不持有作用域会话，
所以沿用"回填钩子"的路子：

```
Evaluator.set_compound_handler(StatementExecutor.execute_expression)
```

执行时开一个**新块作用域**（里面声明的变量不泄漏），逐条执行，取最后一条表达式语句的值。
嵌套的 `({ int a = 2; ({ a * 5; }) })` 要递归——内层那个也是 `Compound`，
在"最后一条"的位置它就是值，不是语句。

类型推断同理：`TypeInferencer._compound` 取最后一条非声明语句的类型。

## 途中发现的两个真 bug

### 1. 嵌套聚合在偏移 0 处提前返回

`m[0][1]` 读不出正确值，报"偏移 0 上是 int[3]，不能用 int 访问"。

根因在 `SlotMemory._resolve`：数组/结构体分支在 `rest == 0` 时直接返回元素类型，
但**偏移落在元素起点不等于调用方要的就是这个元素**——`m[0]` 的类型是 `int[3]`，
而 `m[0][1]` 要的是里面的 `int`。

修法：加 `_needs_descent(element, want)`——元素是聚合且类型对不上时，继续往下剥。
二维数组、嵌套结构体成员都踩这个坑。

### 2. `[1]` 的设计符形状

见上。属于"库内部表示和预期不一致"，又一次印证：**先查再用**。

## 度量：37 → 43

```
总计: 43 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   28 / 40   +2
test_qol2.py      13 / 18   +4
test_print_pointer 0 / 1
```

新实现测试 **668 → 687**（新增 19 个：初始化器 10、语句表达式 5、嵌套聚合 4）。

## 剩下 18 个

| 性质 | 用例 |
|---|---|
| 需要 `GnuCParser` 的 GNU 扩展 | `test_gnu_typeof`、`test_gnu_attribute`、`test_container_of`（typeof 声明位） |
| `switch` + case 范围 + 位域 | `test_type3_constant_folding` |
| 类型双关 | `test_chain_ptr_member_addr`、`test_print_pointer_chain` |
| 旧消息文案 | `test_qol1_error_traceback`、`test_err_undefined_variable`、`test_err_type_mismatch`、`test_err_uninit_ptr_write` |
| 旧内部断言 | `test_l1_lazy_global_init_on_activation`、`test_l4_global_init_at_startup`、`test_l2_cross_file_enum`、`test_mem2_recursion` |
| 其他 | `test_bug3_static_assert`、`test_plan_c_reachable_prelink`、`test_ctrl2_setjmp_longjmp`、`test_l4_tag_redef_conflict_on_use`、`test_proto_decl_and_link_error` |

## 验收

- `pytest super_execute/tests` → **687 passed**
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 43/61
