# super_execute · strangler 收尾（兼容层 + 等价性度量）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, strangler, equivalence

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261030-123612) 表达式与语句

## 做法

旧测试只依赖两个 API 面：

```python
exe_mod.setup_global_scope()
prog = CProgram(files, entry='main'); prog.load(); prog.link(); prog.run()
```

所以做一层 **drop-in 兼容壳**（`super_execute/compat/` 里的顶层 `execute.py` /
`program.py`），把这两个模块在 `sys.modules` 里换成"跑在新实现上"的版本，
旧测试文件**一行都不改**。能过就是等价，过不了就是还缺功能。

```
compat/execute.py             setup_global_scope + 旧异常体系 + 错误翻译
compat/program.py             CProgram（parse_file → Interpreter → run）
compat/compat_state.py        当前解释器实例
compat/run_legacy_tests.py    跑旧套件并出分类报告
```

## 一个方法论上的坑（记录在案）

第一版用 `PYTHONPATH` 把 compat 目录放到最前面来"影子替换"，结果 **61/61 全过**。
这是假的：pytest 在 prepend 导入模式下会把自己算出的 rootdir 插到 `sys.path`
最前面，压过 `PYTHONPATH`，于是 `import program` 又拿回了仓库根那个旧模块——
测的是旧实现。

改成用 importlib 按文件路径把壳装进 `sys.modules`（优先于任何路径搜索），
并在装载后立刻断言 `__file__` 指向 compat 目录。数字随后从 61 掉到 1——
那才是真实起点。

## 顺带修掉的真问题

| 问题 | 说明 |
|---|---|
| 除零用 Python 异常 | `DivisionByZeroError` 进领域错误树；`ZeroDivisionError` 不该漏给调用方 |
| 枚举参与算术被判非法 | `integer_promote` 不认 `EnumType`，`e + 1` 报"算术转换只支持基础类型" |
| 跨文件重复定义 | `lib.c` 与 `main.c` 都原样写着同一份 `typedef struct Pt {...}`；新增 `equivalence.py` 做结构等价，相同则静默去重、不同则报冲突 |
| `cpp_args=None` | 被 `preprocess_file` 当参数塞进命令行，subprocess 里炸成 TypeError |
| 入口检查位置 | 从 `link()` 挪到 `run()`，否则"故意没有 main 只想验冲突"的用例先撞入口错误 |

## 度量（旧套件 61 个用例 × 新实现）

```
总计: 17 passed / 61

test_program.py    9 / 40
test_qol2.py       7 / 18
test_exe.py        0 / 1
test_print_pointer 0 / 1
test_ext.py        1 / 1
```

失败分类：

| 类别 | 数量 | 说明 |
|---|---|---|
| 缺功能（未实现） | 21 | 见下表 |
| 语义 / 消息差异 | 11 | 入口消息文案、冲突是告警还是报错、coord 格式等 |
| LinkError（冲突语义） | 5 | 旧的 strict/warn 两档行为未实现 |
| 断言旧内部结构 | 3 | 断言 `g_source_index` / `g_types`，兼容层下无意义 |
| 类型双关 | 2 | `(AAA*)pc`，Phase A 槽位存储的固有限制 |
| 其他 | 2 | — |

## 剩余缺口（按性价比排序，供下一轮）

1. **常量折叠**：`int a[2+1]` / `enum { A = 1+1 }` —— 阵长和枚举值都要。影响面最大（5+）。
2. **全局初值调用函数**：`int g = helper_gv();` —— 需要"装载完先跑一段初始化"的机制（4）。
3. **函数指针调用**：地址已经能存能传，差一次 `FunctionTable.resolve` 后转发（1）。
4. **GNU 扩展解析**：`typeof` / 语句表达式 / `case 1...5` —— 需要把 `TypeBuilder`
   扩到 `pycparserext` 的 Ext 节点（3）。
5. **`goto`**（1）。
6. **单节点 `execute(node)`**：旧测试直接调它（1）。
7. **冲突语义**：`strict` 报错 / 非 strict 告警 + 消息文案（11+5）。

## 验收

- `pytest super_execute/tests` → **610 passed**
- 仓库根 `pytest` → 874 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` 可复现上述度量

## 结论

**还不能下线旧 `execute.py`**：17/61 说明新实现在多文件、惰性、GNU 扩展、冲突
诊断上仍有实质差距。但这次拿到了可复现的度量工具和逐项缺口，strangler 的
"能过就切、不能过就补"有了客观依据。
