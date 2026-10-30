# super_execute · 冲突诊断 strict/warn（strangler 第七轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, diagnostics, strict

父任务：Task(20261012-144135)；前置：Task(20261030-135514) 惰性装载

## 要分清的是三类"冲突"

以前它们全被当成一种错误，所以要么都报错、要么都不报。实际上语义不同：

| 冲突 | 性质 | 旧实现行为 |
|---|---|---|
| 同名 typedef 类型不同 | **非致命**：保留先定义的，继续跑 | 非 strict 告警；strict 报错 |
| 多个文件定义 `main` | 非致命：取第一个 | 告警 |
| 同名外部函数定义两次 | **致命**：无法决定用哪个 | 报错（与 lazy 无关） |

## 实现：两个桶，各自什么时候抛

- `Interpreter.conflicts: list[str]` —— 非致命冲突的说明文案。
  `raise_conflicts()` 根据 `strict` 决定：报错，还是 `[warn]` 打印一次然后清空。
- `Interpreter.pending_conflicts: list[DomainError]` —— 重复函数定义。
  `raise_definition_conflicts()` 无条件抛出（与 lazy 无关）。
- `Interpreter.pending_errors` —— 惰性装载攒下的类型错误，只在 `lazy=False` 的
  `link()` 里抛（上一轮的机制）。

compat 的时序：

```
link():  raise_conflicts()            # 告警/报错
         raise_definition_conflicts() # 永远报错
         if not lazy: raise_pending() # 全量类型检查
run():   raise_conflicts()            # 惰性模式可能没调过 link()
         raise_definition_conflicts()
```

`link()` 和 `run()` 都调一次是有意的：旧测试有的只调 `link()`，有的直接 `run()`。

## 为什么告警要"攒着再打印"

旧测试对 stdout 的捕获范围不一样：

- `test_t6_typedef_conflict` 包住 `load+link+run`
- `test_l3_eager_link_still_works` 只包住 `link+run`（`load()` 在外面！）

如果告警在 `load()` 时就打印，第二个用例抓不到。所以统一**攒起来，在
`link()`/`run()` 第一次调用时打印**，并用 `clear()` 保证只打一次。

## 度量：31 → 37

```
总计: 37 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   26 / 40   +6
test_qol2.py       9 / 18
test_print_pointer 0 / 1
```

这一轮是六轮里涨幅最大的一次（+6），因为冲突诊断牵动的是**跨文件**的一组用例：
typedef 冲突（warn/strict 两档）、函数重名、多个 main、eager link 全量检查、
惰性激活时的冲突检测。

## 剩下 24 个失败

| 性质 | 数量 | 用例 |
|---|---|---|
| GNU 扩展 | 6 | `typeof` / 语句表达式 / `__attribute__` / 指定初始化器 / `case 1...5` / 零长数组 |
| 类型双关 | 3 | `(AAA*)pc`、`struct tagAAA *` 覆盖读——Phase A 槽位存储的固有限制 |
| 旧消息文案 | 3 | `Undefined variable: 'zz'` 等，**有意不兼容** |
| 旧内部断言 | 3 | 断言 `g` 尚未声明（新实现装载即声明）、`g_call_stack` |
| setjmp/longjmp | 1 | 需跨帧 unwind |
| 单节点 `execute()` | 1 | **不做**——服务于被替代的旧类型表 |
| `_Static_assert` | 1 | 编译期断言 |
| 多条目初始化列表 | 2 | `int a[3] = {1,2,3}` |
| 其他 | 4 | |

## 判断：strangler 该收尾了

剩下的主力是 **GNU 扩展（6）** 和 **类型双关（3）**——这两类都不是"重构没做完"，
而是**新实现还没实现的功能**。旧实现在这两块能过，是因为它当年专门做过。

继续追这两个会变成"给新解释器加功能"，那已经超出"等价替换"的范围。
建议把这个事实写进迁移结论，然后讨论下线旧 `execute.py` 的时机。

## 验收

- `pytest super_execute/tests` → **668 passed**
- 仓库根 `pytest` → 932 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 37/61
