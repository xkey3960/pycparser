# super_execute · 位域（B 类第 4 项）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, bitfield, layout

父任务：Task(20261012-144135)；前置：Task(20261030-145131) switch
**在分支 `feat/bitfield` 上完成，验收后合并回 `refactor/super-execute`。**

## 先查旧实现怎么算的

测试期望 `sizeof(struct Bits) == 8`（`struct Bits { int a : 4 + 4; int b : 3; }`），
而 gcc 对同样结构给的是 4。差在哪？

翻了旧 `typesys.py`：**它根本没有位域逻辑**——没有 `bitsize` 的读取，没有打包。
也就是说旧实现把位域当**普通成员**处理，`int a : 8` 占 4 字节、`int b : 3` 再占
4 字节，加起来正好 8。

这解释了期望值，也给出了这次的正确做法。

## 实现：记宽度，不打包

- `Member` 不再拒绝 `bit_width`，改为**校验**：必须是非负整数、且不超过成员类型的位数
  （`int` 33 位 → 报错）
- `_bit_width(decl, scope, resolver)` 用 `fold()` 求宽度——
  `int a : 4 + 4` 折成 8，`int x : W * 2` 用枚举常量也算得出来，**非恒定值报错**
- 布局**完全不变**：位域仍是"占满声明类型的一个成员"

这是有意的取舍，写在 `Member` 的 docstring 里：真正的位打包要改槽位存储
（一个 4 字节槽里塞多个字段），属于 Phase B。

## 度量：52 → 53

```
总计: 53 passed / 61

test_program.py   33 / 40   +1（test_type3_constant_folding）
```

这个用例从"还没支持的表达式: Switch"一路走到通过，跨了三个改动：
switch 分派 → GNU case 范围 → 位域宽度折叠。

新实现测试 **752 → 759**（`TestBitFields` 4 个 + 布局/类型层 5 个改写）。

## 剩下 8 个

| 类 | 用例 | 性质 |
|---|---|---|
| B | `ctrl2_setjmp_longjmp` | setjmp/longjmp 跨帧 unwind |
| C | `l1_lazy_global_init_on_activation`、`l4_global_init_at_startup` | 装载即声明 vs 按文件激活 |
| C | `l4_tag_redef_conflict_on_use` | tag 未使用不补全 |
| C | `plan_c_reachable_prelink` | strict 可达性预链接 |
| D | `qol1_error_traceback`、`err_undefined_variable` | 英文文案（有意不兼容） |
| E | `proto_decl_and_link_error` | 旧单节点 `execute()` |

**B 类只剩 setjmp 一个了。**

## 验收

- `pytest super_execute/tests` → **759 passed**
- 仓库根 `pytest` → 1023 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 53/61
