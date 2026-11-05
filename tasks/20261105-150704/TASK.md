# super_execute · 初始化器缺口（用户报错 `还没支持的表达式: InitList`）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: initializer, compound-literal, designator

父任务：Task(20261012-144135) 重构execute.py
**在分支 `fix/initializers` 上完成，验收后合并回 `refactor/super-execute`。**

## 触发点

用户在 `examples/varargs.c` 里加了一段真实代码：

```c
typedef enum tagTestEnum { Test1, Test2, TestMax } TestEnum;

char *g_apcTestString[TestMax] = {
    [Test1] = "Test1",
    [Test2] = "Test2",
};
```

报 `还没支持的表达式: InitList`。

## 根因：全局初始化走错了函数

`Interpreter._initialize_globals` 用 `evaluator.eval(expression)` 求全局初值。
但花括号列表**不是表达式**——局部声明早就走 `eval_init`（按目标类型铺开），
全局却漏了这一条。一行改掉：

```python
value = self._evaluator.eval_init(expression, symbol.ctype, target)
```

## 顺着同一条链挖出来的其它缺口

修完主因再跑一批用例，发现一整条链都缺：

| 缺口 | 现象 | 处理 |
|---|---|---|
| 全局聚合初始化 | `int g[3] = {1,2,3};` 报 InitList | 改用 `eval_init` |
| 全局数组长度不由初值决定 | `char g[] = "abc";` 报"不完整数组" | 抽 `complete_array_type`，局部/全局/复合字面量三处共用 |
| **设计符当成员名** | `[Test1]` 被当成成员名 → `0 <= "Test1"` 崩 | 见下 |
| 复合字面量 | `(struct S){1,2}` 完全不支持 | 加了 infer/eval/lvalue 三条路 |
| 数组退化 | `strlen(g[1])`（`char[][4]`）报"需要字符串地址" | 求值语境里数组退化成地址 |
| 嵌套设计符 | `.p.v = 6` / `[1][0] = 5` 只认第一层 | 拆成一层套一层的 InitList |
| `sizeof *p` 自引用 | `struct S *p = malloc(sizeof *p);` 报未定义 `p` | 先声明、后求初值（C 的顺序） |
| `__builtin_types_compatible_p` | `AttributeError: TypeList has no attribute exprs` | 实参是类型不是表达式，求值前拦截 |
| 弹性数组成员下标 | `p->a[0]` 报"缺长度" | 长度未知也算地址，边界交给存储层兜底 |
| `realloc` | 没实现 | 新增；按**值**搬而不是逐字节（Phase A 存储是按值的） |
| `sprintf` / `snprintf` | 没实现 | 新增，复用 printf 的格式翻译 |

### 设计符那条值得单独说

pycparser 把 `.y` 和 `[Test1]` **都**记成 `ID` 节点，形状一模一样。
旧的实现把它们统统当成员名，于是 `[Test1]` 变成字符串 `"Test1"`，再和整数比大小 → TypeError。

正确的判据是**目标类型**（这正是 C 的规则）：

* 初始化数组 ⇒ 设计符是**下标表达式**，`[Test1]` 求值成枚举常量 0；
* 初始化结构体 ⇒ 设计符是**成员名**。

所以 `_designator` 只拆结构，解释权交给调用方的 ctype。

## 顺带统一了一处重复

"数组长度由初值决定"原来写在三个地方（局部声明、全局声明、现在还有复合字面量），
抽成 `complete_array_type(ctype, init)`，三种写法共用——否则同一个写法在函数内外
行为会不一样。

## 「还有什么没支持」写成了可执行清单

新增 `tests/unit/test_unsupported.py`：

* `PARSER_GAPS` —— 语法层不认（复合字面量接后缀、`_Generic`、计算 goto、GNU 嵌套函数、预处理指令）；
* `TYPE_GAPS` —— `long double`、`_Complex`；
* `TestRuntimeGaps` —— 结构体三元运算、`qsort`；
* `TestWhatDoesWork` —— **反向清单**：容易以为没做但其实已通的 11 条。

每条"不支持"都对应一个断言，清单不会腐烂；新增能力时删掉对应行，测试会提醒。

## 度量

```
super_execute  854 → 905 tests（+51）
仓库根         全绿
旧套件         51 / 60（不变）
ruff           全绿
```

用户那份 `varargs.c` 现在跑出：

```
sum   = 6
bonus = 22
grade = 3
varargs.c 的 main() 返回 25
```

## 验收

- 用户报的 `还没支持的表达式: InitList` 不再出现
- 新增 28 个初始化器用例 + 23 个"支持/不支持"清单用例
- 全量 905 passed；旧套件不变
