# super_execute · `va_arg`（三步计划第 3 步）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: va_arg, parser

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261030-161015) 位域真打包
**在分支 `feat/va-arg` 上完成，验收后合并回 `refactor/super-execute`。**

## 用户定的方向：继承重载，不改上游

原本的判断是"`va_arg` 要改 pycparser 本体，成本最高"。用户要求改成
**继承 + 重载**实现自定义解析器——实测下来这个方向是对的，而且比预想的简单。

关键发现：这个仓库的 pycparser 是**手写递归下降**解析器（有 `_TokenBuffer.peek(k)`
多 token 前瞻），不是 PLY 表驱动。所以扩展点是一条清晰的方法，而不是改语法产生式。

## 语法层：一个只有 20 行的子类

```python
class VaArgParser(CParser):
    _VA_ARG_NAMES = ("va_arg", "__builtin_va_arg")

    def _parse_postfix_expression(self):
        if (self._peek_type(1) == "ID"
                and self._peek(1).value in self._VA_ARG_NAMES
                and self._peek_type(2) == "LPAREN"):
            return self._parse_va_arg()
        return super()._parse_postfix_expression()

    def _parse_va_arg(self):
        ...
        ap = self._parse_assignment_expression()   # 第一个实参：表达式
        self._expect("COMMA")
        type_name = self._parse_type_name()        # 第二个实参：**类型**
        ...
        return VaArgExpr(ap, type_name, coord)
```

只重载一个方法，3 个 token 前瞻就能判断，其余全部交回父类。`VaArgExpr` 是我们自己的
`c_ast.Node` 子类（`ap` 是表达式，`type_name` 是 `Typename`）。

两个名字都认，因为：

| 路径 | 预处理后 | 类型还在吗 |
|---|---|---|
| 不走 cpp，自己写 `va_arg(ap, int)` | 原样 | ✓ |
| 真实 gcc `stdarg.h` | `__builtin_va_arg(ap, int)` | ✓ |
| **fake_libc_include** 的假头文件 | `__builtin_va_arg((ap))` | ✗ **类型被宏丢掉了** |

所以假头文件那条路走不通——已在 README 里写明。

## 运行时

* `Interpreter` 每个函数帧记下多余实参（`_vararg_stack`，`call()` 进出帧时压/弹）。
* `va_list` 变量本身是普通变量（fake 头里就是 `int`），游标按**它的地址**登记：
  `_va_lists[地址] = {args, index}`。
* `va_start(ap, last)` 在 `_handle_call` 里特判——它要拿 `ap` 的**地址**，不能只拿值。
  同时认 `__builtin_va_start`。
* `VaArgExpr` 求值走 `Evaluator.set_va_arg_handler` 回填的钩子（和语句表达式同一个套路），
  取下一个实参并按 `type_name` 转换。
* `infer` 对 `VaArgExpr` 直接返回那个类型——所以 `int x = va_arg(ap, int);` 的类型推导正常。

## 度量

```
super_execute  831 → 848 tests（+17）
仓库根         974 → 990+ passed / 6 skipped
旧套件         51 / 60（不变，旧用例里没有 va_arg）
```

端到端验证：

```c
int sum(int n, ...) { va_list ap; int total = 0; va_start(ap, n);
    for (int i = 0; i < n; i++) total += va_arg(ap, int);
    va_end(ap); return total; }
int main(void) { return sum(3, 10, 20, 12); }        /* → 42 */
```

测到的场景：顺序取、类型转换（int 实参按 double 取）、`char *` 实参、
两个函数的游标互不干扰、内层调用不破坏外层帧、没 `va_start` 就 `va_arg` 报错、
取多了报错、标准 `CParser` 仍然解析不了（对照组）。

## 三步计划完成

| 步 | 状态 | 指标 |
|---|---|---|
| ① 位域值语义 | ✅ | 52/60 不变 |
| ② 位域真打包 | ✅ | 52 → 51（有意，`test_type3` 断言旧的不打包） |
| ③ `va_arg` | ✅ | 51/60 不变 |

## 验收

- `pytest super_execute/tests` → 848 passed
- 仓库根全绿
- `ruff check` / `format --check` 全绿
- 上游 `pycparser/` 一行未改（`git status` 可证）
