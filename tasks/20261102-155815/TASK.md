# super_execute · 补充示例：GNU 扩展 + `va_arg` 的解析器

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: va_arg, gnu, example

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261030-161716) va_arg
**在分支 `feat/gnu-va-arg-example` 上完成，验收后合并回 `refactor/super-execute`。**

## 需求

上一轮的 `VaArgParser` 只继承标准 `CParser`——用不了 GNU 扩展。
但真实代码里这两样经常同时需要（GNU 的 `typeof` / `case 1 ... 5` + 可变参数）。
所以：

1. 把那条语法抽成 **mixin**，同时派生两个解析器；
2. 补一个把 GNU 扩展和 `va_arg` 混用的示例。

## 实现：mixin 而不是复制

`GnuCParser` 自己也重载了 `_parse_postfix_expression`（处理
`__builtin_types_compatible_p`），所以组合方式是 MRO：

```
GnuVaArgParser → _VaArgMixin → GnuCParser → CParser
```

先看是不是 `va_arg`，不是就交给 GNU 那层，再交给标准层。新增的语法仍然只有一处。

```python
class _VaArgMixin:
    def _parse_postfix_expression(self):
        if (self._peek_type(1) == "ID"
                and self._peek(1).value in self._VA_ARG_NAMES
                and self._peek_type(2) == "LPAREN"):
            return self._parse_va_arg()
        return super()._parse_postfix_expression()

class VaArgParser(_VaArgMixin, CParser): ...
class GnuVaArgParser(_VaArgMixin, GnuCParser): ...
```

`pycparserext` 是可选依赖：没装时 `GnuVaArgParser` 变成"一构造就报清楚
`ImportError`"的占位类，`VaArgParser` 不受影响。

## 示例

`examples/varargs.c` —— 一个程序里同时用五样东西：

| 特性 | 代码 |
|---|---|
| 可变参数 | `va_start` / `va_arg` / `va_end` |
| GNU 区间分支 | `case 90 ... 100: return 4;` |
| GNU 语句表达式 | `({ int t = sum(2, 5, 6); t * 2; })` |
| GNU `typeof` | `typeof(int) bonus` |
| 内建函数 | `printf`（不用 `#include`） |

`examples/run_varargs.py` 与 `run_hello.py` 只差**一行**：解析器换成 `GnuVaArgParser`。

```
$ py examples/run_varargs.py
sum   = 6
bonus = 22
grade = 3
varargs.c 的 main() 返回 25
```

三种 CWD（项目目录 / 仓库根 / 临时目录）都能跑。

## 解析器组合矩阵（实测，也写进了 README）

| 解析器 | `va_arg` | `case 1 ... 5` |
|---|---|---|
| `CParser` | ✗ | ✗ |
| `VaArgParser` | ✓ | ✗ |
| `GnuVaArgParser` | ✓ | ✓ |

## 测试

`tests/unit/test_examples.py` 把这个示例钉住，并且**三条对照**一起测：

* `varargs.c` + `GnuVaArgParser` → 25；
* 同一个文件 + `CParser` → 解析失败（这正是示例要换解析器的原因）；
* 同一个文件 + `VaArgParser` → 也失败（`typeof` / 区间分支需要 GNU 那层）。

`tests/unit/interface_adapters/test_va_arg.py` 新增 `TestGnuParser` 三个用例，
其中两个是反方向对照（`GnuCParser` 不认 `va_arg`、`VaArgParser` 不认区间分支）。

## 度量

```
super_execute  847 → 853 tests（+6）
旧套件         51 / 60（不变）
ruff           全绿
```

## 验收

- 示例从三种 CWD 都能跑出 `sum=6 / bonus=22 / grade=3 / 返回 25`
- 解析器矩阵与 README 写的一致
- `pytest super_execute/tests` → 853 passed
- 上游 `pycparser/`、`pycparserext/` 一行未改
