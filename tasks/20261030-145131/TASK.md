# super_execute · `switch` + GNU case 范围（B 类第 3 项）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, switch, control-flow

父任务：Task(20261012-144135)；前置：Task(20261030-144350) 字符串字面量
**在分支 `feat/switch` 上完成，验收后合并回 `refactor/super-execute`。**

## 语义：switch 不是分支表，是"goto 到某个标签"

C 的 `switch` 本质是跳转到匹配的 `case`，然后**顺序往下执行**（fall-through）。
所以实现只有两步：

1. 算出该从哪一项开始（先找匹配的 `case`，再退回 `default`）；
2. 从那里开始一路执行，直到 `break` 或走完。

中间那些 `case` 标签没有额外作用——它们只是标记位置。

AST 形状（确认过）：`Switch(cond, stmt=Compound)`，`Compound.block_items` 里是
`Case(expr, stmts)` / `Default(stmts)` / 普通语句平铺。每个 `Case` 自带它标签下
的那几条语句，所以 `case 2:`（空）自然就是 fall-through 到下一项。

## 控制流归属

- `break` 由最近的 `switch` 或循环捕获 → `switch` 里捕获，跳出整段
- `continue` **不属于** switch，继续往外传给外层循环
- `goto` 同理往外传（标签是函数作用域的）

这几条都写了测试钉住——尤其是"`switch` 里的 `for` 中 `break` 打的是循环不是 switch"。

## 顺带：GNU case 范围

`case 1 ... 5:` 解析成 `Case(expr=RangeExpression(first, last))`。闭区间判断，
成本很低就一起做了。认法是按类名判断，不引入 pycparserext 依赖。

## 度量：52 → 52（但 `type3` 的失败点前移了）

```
总计: 52 passed / 61
```

`test_type3_constant_folding` 的报错从"还没支持的表达式: Switch"变成了：

```
struct Bits 是不完整类型（只有前置声明），不能求大小
```

也就是说：**switch ✓、case 范围 ✓，只剩位域**。位域是实现定义的打包规则
（`int a : 4 + 4; int b : 3;` 的 sizeof 取决于编译器），要单独定一套并写测试，
所以本轮按计划只做 switch。

新实现测试 **739 → 752**（`TestSwitch` 10 个、`TestCaseRange` 4 个）。

## 剩下 9 个

| 类 | 用例 | 阻塞点 |
|---|---|---|
| B | `type3_constant_folding` | **只剩位域** |
| B | `ctrl2_setjmp_longjmp` | setjmp/longjmp |
| C | 惰性激活时机 ×2、tag 不补全 ×1、strict 可达性 ×1 | 要回到按文件激活 |
| D | 英文文案 ×2 | 不做 |
| E | 旧单节点 `execute()` ×1 | 不做 |

## 验收

- `pytest super_execute/tests` → **752 passed**
- 仓库根 `pytest` → 1016 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 52/61
