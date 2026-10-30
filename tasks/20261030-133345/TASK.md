# super_execute · 按文件划分作用域（static 隔离，D6）（strangler 第四轮）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, scope, static, d6

父任务：Task(20261012-144135)；前置：Task(20261030-131507) TYPE-2 与 QOL-1

## 要解决的问题

C 的 `static` 是**文件级**的：两个 .c 各写 `static int g;`，是两个互不相干的变量。
重构前的实现把它们声明进同一个作用域，直接撞车报"作用域里已经有 'g' 了"——这是
**正确性问题**，不是测试通过率问题。D6 裁决里答应过要做，一直没做。

## 做法：多一层作用域，而不是加一堆特判

```
FILE   全程序作用域（根）：外部符号（非 static 的全局 / 函数）
 └ UNIT 翻译单元作用域：该文件的 static 符号
    └ FUNCTION / BLOCK / PROTOTYPE
```

关键是**结构解决了问题**：把 static 声明进 UNIT 层之后，名字天然只在那条链上
可见，`Scope.find` 不需要知道"调用者在哪个文件"。函数作用域挂在自己那个 UNIT
下，于是函数体能看见本文件的 static，也能沿链看到外部符号——正是 C 的规则。

要点：

- `ScopeKind.UNIT` 新增；`FUNCTION` 的父作用域放宽为 FILE **或** UNIT
- 链接属性检查从"只能在 FILE"放宽到"FILE 或 UNIT"
- 函数体按单元归档：外部函数用名字做键，static 函数用 `(单元, 名字)` 区分
- `extern int g;`（不带初值）只是引用已有全局，不再当重复定义
- 全局初值在**它所属的那一层**求值（static 全局的初值可能调用本文件的 static 函数）

## 兼容层：投影，不是伪造

旧测试读 `exe_mod.g_static_funcs` / `g_static_globals`——新模型里没有"按文件名分的表"，
因为隔离靠作用域层级实现。兼容层用模块级 `__getattr__` 在**访问那一刻**投影：

    g_static_funcs[文件]   ← 该单元里带 internal 链接的函数符号
    g_static_globals[文件] ← 同样那些变量的**当前值**（真从内存读）

形状是旧的，数据是真的。这不是把断言设成恒真——如果把 static 隔离做错，
投影出来的值就是错的，测试照样会挂。

## 一个隐蔽的 bug

接上投影后 `st_a.c` 的 static 消失了，只有 `st_b.c` 有。原因在兼容层的装载循环：

```python
for path in self.files:            # 第一个循环，path 用完
    ast = parse_file(path); self.asts.append(ast)

for ast in self.asts:              # 第二个循环，path 还停在上一个循环的最后一个值
    self.interpreter.load(ast, path)
```

三个单元全登记成最后一个文件名。改成 `zip(self.files, self.asts)` 后正常。
**循环变量跨循环复用**是这类 bug 的典型来源，值得记一笔。

## 度量：22 → 23

```
总计: 23 passed / 61

test_exe.py        1 / 1
test_ext.py        1 / 1
test_program.py   13 / 40   ← test_s4_static_isolation 通过
test_qol2.py       8 / 18
test_print_pointer 0 / 1
```

只涨了 1，但这一轮的价值主要在**正确性**：之前"两个文件各自 static 同名全局"
这种完全合法的 C 代码是跑不了的。

## 现在剩下的（17 个"缺功能"）

| 缺口 | 数量 | 备注 |
|---|---|---|
| 惰性装载语义 | 4 | `lazy_bad.c` 故意写坏的类型不该在装载时报错；需要"按需构建类型" |
| 冲突诊断 strict/warn 两档 | 8（语义类） | 旧实现非 strict 告警、strict 报错 |
| 函数指针调用 | 1 | 地址已能存能传，差查表转发 |
| `goto` | 1 | |
| GNU 扩展解析 | 2 | `typeof` / 语句表达式 / `case 1...5` |
| 类型双关 | 2 | Phase A 槽位存储的固有限制 |
| 单节点 `execute()` | 1 | 旧 API，兼容层可以补 |

## 验收

- `pytest super_execute/tests` → **659 passed**
- 仓库根 `pytest` → 923 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 23/61
- 新增 `TestStaticIsolation` 6 个用例（含"重构前的 bug"那条回归）
