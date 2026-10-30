# super_execute · 函数指针调用 + goto + 除零分类（strangler 第五轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, function-pointer, goto

父任务：Task(20261012-144135)；前置：Task(20261030-133345) 按文件划分作用域

## 三个小口子（原计划）

### 1. 函数指针调用

`fp(x)` 里 `fp` 是**变量**不是函数名。原来的 `call()` 一看到"不是 FunctionSymbol"
就报"函数指针调用还没接"。现在的分派：

```
node.name 不是 ID（`(*fp)(x)`）  → 先求值成地址 → call_through(address)
node.name 是 ID 且符号是函数指针 → 读变量里的地址 → call_through(address)
否则                              → 按名字调用（原路径）
```

`call_through` 把地址从函数表解析回符号再按名字调用——因为**函数名当值时就是它的
地址**，"经变量调用"和"直接调用"走的是同一条路。

顺带补了一处：解引用函数指针（`(*fp)(x)`）不该去读函数体存储，
FUNCTION 区没有可读的槽位；解引用函数指针得到"函数本身"，而函数的值就是地址。

### 2. goto

标签是**函数作用域**的，`goto` 可以从循环里跳到外层块。实现用异常逐层传播：

- `_compound` 先给本块建 `标签名 → 下标` 的表
- 捕获 `GotoSignal`：本块有这个标签就从那个下标继续，没有就继续往外抛
- 一路抛到函数边界还没找到 → `UndefinedLabelError`

这样"前跳 / 回跳 / 跳出循环 / 嵌套块跳外层"全部自然成立，不需要给每个块预建表。
`switch` 仍然没做（`case` 是另一套语义）。

### 3. 除零的错误分类

`DivisionByZeroError` 之前没进兼容层的映射表，于是旧测试拿到的是
`InterpreterError` 而不是 `TypeError_`。补上映射，并把消息改成含"除零"字样
（旧测试断言这个词）。

## 度量：23 → 26

```
总计: 26 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   15 / 40   +2（goto / 函数指针）
test_qol2.py       9 / 18   +1（除零分类）
test_print_pointer 0 / 1
```

## 现在剩下的失败（35 个），按性质分

| 性质 | 数量 | 说明 |
|---|---|---|
| **惰性装载语义** | 4 | `lazy_bad.c` 故意写坏的类型不该在装载时报错；load 时是 eager 的 |
| **旧消息文案 / 告警文案** | 5 | `Undefined variable: 'zz'`、`多个文件定义入口`、`dupf`。**有意不做兼容** |
| **冲突诊断 strict/warn** | 4 | 非 strict 告警、strict 报错 |
| **GNU 扩展解析** | 2 | `typeof` / 语句表达式 / `case 1...5` |
| **类型双关** | 3 | `(AAA*)pc` 与 `struct tagAAA *` 覆盖读，Phase A 槽位存储的固有限制 |
| **旧内部断言** | 4 | 断言 `g_source_index` / 惰性激活时机 |
| **setjmp/longjmp** | 1 | 需要跨帧 unwind |
| **单节点 `execute()`** | 1 | 旧 API，且 test_typesys.py 有 48 个用例依赖它 |
| **零长数组** | 1 | GNU 扩展 |
| **其他** | 10 | 见任务末尾 |

## 我的判断：剩下的都不该急着做

- **惰性装载**是唯一还有分量的架构工作（要"按需构建类型"），值得单独一轮设计。
- **消息文案**明确不做：新实现用中文是有意选择。
- **GNU 扩展**和**setjmp**是新增功能，不是"重构等价性"的一部分。
- **单节点 `execute()`** 服务于 `test_typesys.py`——那 48 个用例测的是旧的扁平
  类型表，而新架构用 `TypeBuilder` + `Scope` 替代了它。为它们写兼容层意义不大：
  通过率会涨，但证明的只是"旧 API 还能用"，不是"新实现等价"。

## 验收

- `pytest super_execute/tests` → **668 passed**
- 仓库根 `pytest` → 932 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 26/61
- 新增 `TestGoto` 5 个、`TestFunctionPointers` 6 个用例
