# super_execute · 位域值语义（三步计划第 1 步）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: bitfield, semantics

父任务：Task(20261012-144135) 重构execute.py
**在分支 `fix/bitfield-values` 上完成，验收后合并回 `refactor/super-execute`。**

按上一轮定的顺序执行：① 位域值语义 → ② 位域真打包 → ③ `va_arg`。这是第 1 步。

## 先取 gcc 的黄金值，不靠推理

```
struct S { unsigned a : 3; int b : 3; unsigned c : 5; int d : 4; };
s.a = 9;   → 1        s.b = 5;  → -3
s.c = 33;  → 1        s.d = 7;  → 7      s.b = -4; → -4
sizeof = 4
```

两条规则：**无符号**取低 w 位；**有符号**再符号扩展。

## 修的是真 bug

之前完全没有截断：`unsigned a : 3; s.a = 9;` 读回 9。C 里应该是 1。

现在与 gcc 逐条一致：

```
s.a = 9  (unsigned:3)  →   1   (gcc: 1)
s.b = 5  (int:3)       →  -3   (gcc: -3)
s.c = 33 (unsigned:5)  →   1   (gcc: 1)
s.d = 7  (int:4)       →   7   (gcc: 7)
s.b = -4 (int:3)       →  -4   (gcc: -4)
```

## 改动点（四处在"值流入/流出位域"的地方）

| 位置 | 做什么 |
|---|---|
| `Evaluator._eval_assignment` | 赋值目标是位域成员 → 按宽度截断（`=` 与 `+=` 都走这条） |
| `Evaluator._load_lvalue` | 读位域时按宽度掩码（防止存储里的越界值被原样读出） |
| `Evaluator._init_list` | 初始化列表 `{9, 7}` 也要截断 |
| `Evaluator._offsetof_null_base` | `offsetof` 用到位域 → 报错（C99 6.7.2.1 明令禁止） |

新增三个小工具：`_member_of`（从结构体类型按名找成员）、`_bitfield_member`（判断左值是不是位域）、
`_fit_to_bitfield`（掩码 + 符号扩展）。

## 没动布局

`sizeof` 仍是"每个位域占满声明类型"（`struct { unsigned a:3; int b:3; }` = 8，gcc 是 4）。
这是第 2 步的事——真打包要改成员寻址、存储表示和 `_resolve` 的歧义处理，
而且**会让归档的 `test_type3_constant_folding` 失败**（它断言 `sizeof == 8`）。
先做值语义的好处正是：修了真 bug，却不掉指标。

旧套件实测 **52 / 60，未变** ✓。

## 一个老测试被改对了

`test_read_write_like_ordinary_members` 原来用 `int a : 1; int b : 2;` 断言 `1*10+3 == 13`。
按 C 语义 `int a:1` 只能是 0 或 -1（gcc 实测），所以那个断言编码的是"不截断"的旧行为。
改成 `unsigned` 后断言仍然成立，另外新增 10 个用例专门测截断。

## 度量

```
super_execute  799 → 809 tests（+10）
旧套件         52 / 60（不变）
ruff           全绿
```

## 验收

- 五条 golden 值与 gcc 逐条一致
- `offsetof` 用到位域会报错
- `pytest super_execute/tests` → 809 passed
- 仓库根 `pytest` → 绿色
