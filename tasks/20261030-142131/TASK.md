# super_execute · 切换到 GnuCParser（GNU 扩展第二批）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, gnu, parser

父任务：Task(20261012-144135)；前置：Task(20261030-141501) GNU 第一批
**在分支 `feature/gnu-parser` 上完成，验收后合并回 `refactor/super-execute`。**

## 先摸清节点形状，别凭印象改

动手前先探测了 `GnuCParser` 对**普通代码**产出什么节点。结论和预想的不一样：

| Ext 节点 | 是 `c_ast` 的子类吗 |
|---|---|
| `TypeDeclExt` | ✅ 是 `TypeDecl` 的子类 |
| `ArrayDeclExt` | ✅ 是 `ArrayDecl` 的子类 |
| `StructExt` | ✅ 是 `Struct` 的子类 |
| **`FuncDeclExt`** | ❌ **不是** `FuncDecl` 的子类 |
| `TypeOfExpression` / `TypeOfDeclaration` | ❌ 独立类 |

所以"换解析器会把所有 `isinstance` 都打穿"的担心是多余的——**只有函数声明符**需要
显式认，其余三个靠继承就通了。

## 改动

1. `type_builder.py`：`_FUNC_DECLS` 元组 = `(c_ast.FuncDecl, FuncDeclExt)`，
   用于声明符分派和 `_function`。
2. `typeof`：新增 `_typeof_expression` / `_typeof_declaration`。
   求 `typeof(expr)` 的类型要调推断器，而推断器又依赖 `TypeBuilder`（`from_type`），
   所以这里**延迟导入**，避免导入期循环。
3. `pycparserext` 是**可选依赖**：`_ext_class()` 装不上就返回 `None`，
   `_FUNC_DECLS` 退化成只有 `c_ast.FuncDecl`。适配器不把它变成硬依赖。
4. compat 默认解析器改成 `GnuCParser`（和旧 `CProgram` 一致），没有则降级朴素。

## 顺带修掉的两个真 bug（`offsetof` 链条）

`test_container_of` 一路往下挖，暴露出两处：

### ① `(T *)0` 没变成空指针

`_eval_cast` 对指针目标直接 `return value`，于是 `(struct L *)0` 得到**整数 0**，
后面 `->` 访问报"成员访问的基地址不是指针"。

改成 `convert_value(value, target)`：指针之间仍是换解释，但整数 0 会变成 `NULL_ADDRESS`。

### ② `&((T *)0)->m` 的表示问题

`offsetof` 就是这么定义的，但"空指针 + 偏移"在 `Address` 里没有合法表示
（`scope_id == 0` 是 NULL 专用，构造校验会拒绝）。

三次尝试后定下来：**它本来就不是地址，是整数偏移**。所以在 `_address_of` 里
特判——基址为空指针时直接返回 `offsetof()` 的整数结果。

同时保住了安全检查：普通的 `*(p + 1)`（p 为空）仍然报
"NULL 指针不能参与指针算术"。offsetof 是特例，不是放水。

## 度量：43 → 46

```
总计: 46 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   29 / 40   +1（container_of）
test_qol2.py      15 / 18   +2（typeof / attribute）
test_print_pointer 0 / 1
```

新实现测试 **687 → 699**（新增 `test_gnu_extensions.py` 12 个）。

## 剩下 15 个

| 性质 | 用例 |
|---|---|
| `switch` + case 范围 + 位域 | `test_type3_constant_folding` |
| 类型双关 | `test_chain_ptr_member_addr`、`test_print_pointer_chain` |
| 旧消息文案（有意不兼容） | `test_qol1_error_traceback`、`test_err_undefined_variable`、`test_err_type_mismatch`、`test_err_uninit_ptr_write` |
| 旧内部断言 | `test_l1_lazy_global_init_on_activation`、`test_l4_global_init_at_startup`、`test_l2_cross_file_enum`、`test_mem2_recursion`、`test_l4_tag_redef_conflict_on_use`、`test_plan_c_reachable_prelink` |
| 其他 | `test_bug3_static_assert`、`test_ctrl2_setjmp_longjmp`、`test_proto_decl_and_link_error` |

## 验收

- `pytest super_execute/tests` → **699 passed**
- 仓库根 `pytest` → 963 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 46/61
