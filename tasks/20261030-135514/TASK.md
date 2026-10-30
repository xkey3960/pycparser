# super_execute · 惰性装载语义（strangler 第六轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, lazy-loading

父任务：Task(20261012-144135)；前置：Task(20261030-134143) 函数指针与 goto

## 目标语义（旧实现的 L4 条款）

> 启动装载全部文件（全局 eager），struct/union **只注册不布局**；
> 类型错误延迟到首次真正使用（ensure_complete）。

关键观察：**旧实现的 tag 是先登记、后填成员的**。我们的 `_tag_type` 本来就是这个
顺序——`typedef struct Bad { int arr[no_such_thing + 1]; } Bad;` 在填成员时炸了，
但 `struct Bad` 这个标签**已经登记成不完整类型**了。于是"注册不布局"是白送的，
缺的只是"出错别中断，记下来"。

## 实现

1. `Interpreter(lazy=True)`：`load()` 逐个顶层声明处理，出错就记进
   `pending_errors` 并继续；标签留在"已登记、未布局"的状态。
2. `raise_pending()`：把攒下的错误抛出去。`CProgram.link()` 在 `lazy=False`
   时调用它——这正是旧的"全量检查发生在 link()"。
3. 用到才报：标签不完整，`sizeof` 时报"不完整类型"；这类延迟错误自然发生，
   不需要额外机制。
4. 数组维度的报错补上**是谁的问题**：
   `数组长度必须是整型常量表达式：BinaryOp 折不成常量（no_such_thing 未定义或不是常量）`
   ——表达式里查不到的标识符会被挑出来点名。

**装载阶段总是惰性**（即使 `lazy=False`）：旧 `load()` 也只登记，全量检查在
`link()`。这样 `CProgram(..., lazy=False).load()` 不会提前炸，测试能按旧顺序
`load(); link()` 观察错误。

## 兼容层新增的三块投影

| 旧 API | 投影来源 |
|---|---|
| `sources.g_source_index.state` | 装载过的单元名 → `'loaded'`（新模块 `compat/sources.py`） |
| `g_types.lookup_tag(kind, name)` | `DeclarationLoader.tag_registry` |
| `ctype.is_complete()`（方法） | 包一层 `_LegacyType`——新模型里它是**属性** |

第三块值得一提：`is_complete` 在新领域模型里是属性（`if ctype.is_complete:`），
旧 API 里是方法（`ctype.is_complete()`）。这是纯粹的 API 形状差异，
**在兼容层解决，不改领域模型**。

`sources` 必须注入：仓库根真有一个旧的 `sources.py`，不加进 `install_compat()`
的替换名单就会 `import` 到它。

## 度量：26 → 31

```
总计: 31 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   20 / 40   +5
test_qol2.py       9 / 18
test_print_pointer 0 / 1
```

+5 里既有真语义（惰性装载：坏文件不报、用时才报、link 全量检查），
也有 API 形状适配（`is_complete()`、`g_types`、`sources`）。

## 途中踩的坑

1. `c_ast.AST` 不存在——这个 pycparser 分支的基类叫 `c_ast.Node`。我写
   `_unknown_names` 时按印象用了 `AST`，5 个用例当场报 `AttributeError`。
   教训：**先查再用**，别凭印象写库内部名字。
2. PowerShell 的 `.Replace()` 里用单引号写 `` `r`n `` 不会被转义，把字面量插进了
   源码（两次）。这类改动应该用编辑工具。

## 剩下 30 个失败

| 性质 | 数量 | 判断 |
|---|---|---|
| 冲突诊断 strict/warn | 4 | **下一轮做**：非 strict 告警、strict 报错 |
| 旧消息文案 | 5 | 有意不兼容（中文 vs 英文） |
| GNU 扩展（typeof / 语句表达式 / 零长数组 / `case 1...5`） | 4 | 新增功能，不是等价性 |
| 类型双关 | 3 | Phase A 固有限制 |
| setjmp/longjmp | 1 | 需跨帧 unwind |
| 单节点 `execute()` | 1 | 服务于被替代的旧类型表，**不做** |
| 惰性激活时机断言 | 3 | 断言 `g` 尚未声明——新实现装载即声明，语义不同 |
| 其他 | 9 | |

## 验收

- `pytest super_execute/tests` → **668 passed**
- 仓库根 `pytest` → 932 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 31/61
