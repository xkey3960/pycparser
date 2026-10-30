# super_execute · TYPE-2 隐式转换 + QOL-1 错误定位（strangler 第三轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, conversions, error-reporting

父任务：Task(20261012-144135)；前置：Task(20261030-130703) 常量折叠与全局初值

## 按数据排的优先级

上一轮的度量指出真正的阻塞是惰性装载、冲突诊断、隐式转换、错误定位。这一轮取
后两项（前两项需要结构性改动，单独一轮）。

### 1. TYPE-2 隐式类型转换

`domain/services/conversions.py` 新增 `convert_value(value, ctype)`，用在
**四类"值流入类型"的地方**：

| 场合 | 例 |
|---|---|
| 初始化 | `int x = 3.7;` → 3 |
| 赋值 / 复合赋值 | `y += 2.7`（先算 7.7 再转回 int）→ 7 |
| 传参 | `half_of(5)` 传给 `double` 形参 → 5.0 |
| 返回值 | `return 3.7;`（`int` 函数）→ 3 |

浮点转整型向零截断（`int(-3.7) == -3`），整数 0 转指针变 NULL，枚举按 int 存。

**故意没做**：窄化截断。Phase A 用 Python 整数，`char c = 300` 不会回绕成 44——
那是 Phase B 换字节存储后自然发生的事。测试把当前行为钉住了，避免误以为是 bug。

### 2. QOL-1 错误定位与调用链

`DomainError` 现在带 `coord` 与 `call_chain`：

- 求值器与语句执行器的**入口**都包一层，出错时把该节点的 coord 附到异常上。
  因为递归调用也走入口，**最内层**先附上；外层看到已有值就不覆盖——报出来的是
  真正的出错点，不是最外层那条语句。
- `Interpreter.call` 在函数边界记录调用链（只在最内层记一次）。
- `Interpreter.run` 出错时打印 `[error] <位置>: <消息>` + `调用链: main → helper → inner`，
  然后再把异常抛出去（调用方既能看报告，也能按类型捕获）。

## 一次操作失误与恢复（记录在案）

用 PowerShell 做多行字符串替换时写错了参数（`-replace` 后跟了三个元素），
命令报错导致 `$new` 为空，`Set-Content` 把 `evaluator.py` 截断成 3 字节。

恢复：`git checkout -- <file>` 回到上一次提交，再用手工编辑重做三处改动
（DomainError 导入、convert_value 调用、eval/_eval 包装）。

**教训**：结构性改动不要用 shell 字符串手术，用编辑工具；并且改大批量前先提交。
这次损失有限（文件刚提交过），但流程上是运气。

## 度量：20 → 22

```
总计: 22 passed / 61
test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   12 / 40     ← test_type2_implicit_conversion 通过
test_qol2.py       8 / 18     ← 一个 coord 相关用例通过
test_print_pointer 0 / 1
```

| 类别 | 数量 |
|---|---|
| 缺功能 | 17 |
| 语义 / 消息差异 | 8 |
| 断言旧内部结构 | 5 |
| 其余 | 9 |

**"语义 / 消息差异"从 10 降到 8**，说明 coord 确实是其中一部分的成因；剩下的
主要是**旧实现的英文消息文案**（`Undefined variable: 'zz'`）。这一类我**不做兼容**：
新实现用中文消息是有意的选择，兼容层去伪造英文文案只会让"等价性"这个指标变虚。

## 下一轮

1. **惰性装载语义**（4 个）——`lazy=True` 时坏文件不报错、用到才报。这是
   `sources.py` 那套激活机制，需要先设计"文件作用域 + 按需构建"。
2. **static 文件级隔离**（正确性问题，度量上被旧内部断言挡住）——两个文件各自的
   `static int g;` 目前会在同一作用域撞车；D6 答应过要做成 per-file scope。
3. **冲突诊断的 strict/warn 两档**（8 个里的大头）。
4. GNU 扩展解析（2）、函数指针调用（1）、`goto`（1）。

## 验收

- `pytest super_execute/tests` → **651 passed**（原 627，+24）
- 仓库根 `pytest` → 915 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 22/61
