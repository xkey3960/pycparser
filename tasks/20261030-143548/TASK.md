# super_execute · 修掉 A 类 4 个（兼容层不一致 + main 返回值）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, compat, c99

父任务：Task(20261012-144135)；前置：Task(20261030-142131) GnuCParser
**在分支 `fix/compat-a-class` 上完成，验收后合并回 `refactor/super-execute`。**

按上一轮对 15 个剩余失败的解释，A 类 4 个是"我自己的小 bug / 不一致"，先修：

| # | 用例 | 根因 |
|---|---|---|
| ① | `l2_cross_file_enum` | 兼容层 `g_scope.get()` 返回符号而不是**值** |
| ② | `mem2_recursion` | 同上 |
| ③ | `print_pointer_chain` | `main` 没有 `return` 时返回了 `None` |
| ④ | `err_uninit_ptr_write` | 报错消息缺"地址"字样 |

## ① ② 兼容层的 `get()` 该返回值

旧符号表里 `g_scope.get(name)` 拿到的就是**值**：

```python
assert exe_mod.g_scope.get('EGREEN') == 1     # 常量
assert exe_mod.g_scope.get('count') == 10     # 变量
```

我写的 facade 直接返回了符号对象，于是 `ConstantSymbol(...) == 1` 恒为假。

修法：按符号种类取值——常量给 `.value`，变量从内存读，函数/类型这类没有值的
给符号本身。地址还没就绪时（装载阶段）退回符号，不抛。

## ③ `main` 落到结尾要返回 0

```c
int main() { ... pa = pa->pstNext; }   /* test/printf_pointer.c 结尾没有 return */
```

**C99 5.1.2.2.3**：`main` 执行到结尾的 `}` 等价于 `return 0;`。

这条**只对入口函数**成立——别的非 void 函数落到结尾仍是未定义行为，不给默认值。
测试里专门钉了这个边界（`test_only_main_gets_the_default`）。

## ④ 消息要说清是"地址"的问题

```python
assert '地址' in str(e) or 'Address' in str(e)
# 旧: "解引用 NULL 指针"
# 新: "解引用 NULL 地址（指针为空或未初始化）"
```

未初始化的指针在本实现里就是 NULL 地址（这是项目里**有意记录**的偏差：
C 里未初始化是未定义值，我们给 0）。消息点明"地址"更准，也对上了旧测试的措辞。

## 度量：46 → 50

```
总计: 50 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_print_pointer 1 / 1   +1
test_program.py    31 / 40  +2
test_qol2.py       16 / 18  +1
```

新实现测试 **699 → 705**（新增 `TestMainReturnValue` 4 个、`TestNullDereference` 2 个）。

## 剩下 11 个（都在预期内）

| 类 | 用例 | 性质 |
|---|---|---|
| B | `type3_constant_folding` | `switch` + case 范围 + 位域 |
| B | `err_type_mismatch` | 字符串字面量 |
| B | `ctrl2_setjmp_longjmp` | setjmp/longjmp 跨帧 unwind |
| B | `bug3_static_assert` | `_Static_assert`（**最便宜**，`fold` 已有） |
| C | `l1_lazy_global_init_on_activation`、`l4_global_init_at_startup` | 装载即声明 vs 按文件激活 |
| C | `l4_tag_redef_conflict_on_use` | tag 未使用不补全 |
| C | `plan_c_reachable_prelink` | strict 可达性预链接 |
| D | `qol1_error_traceback`、`err_undefined_variable` | 英文消息文案（有意不兼容） |
| E | `proto_decl_and_link_error` | 旧单节点 `execute()` + `typesys` |

## 验收

- `pytest super_execute/tests` → **705 passed**
- 仓库根 `pytest` → 969 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 50/61
