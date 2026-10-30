# super_execute · `_Static_assert`（B 类第 1 项）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, static-assert, c11

父任务：Task(20261012-144135)；前置：Task(20261030-143548) A 类修复
**在分支 `fix/static-assert` 上完成，验收后合并回 `refactor/super-execute`。**

## 为什么先做这个

B 类四项里最便宜的：条件是**常量表达式**，而 `fold()` 早就有了（数组维度、枚举值
用的是同一个折叠器）。原先 `load_node` 里对 `c_ast.StaticAssert` 直接 `return None`，
注释写着"留给编译期检查"——就是一直没做。

## 实现

```c
_Static_assert(sizeof(int) == 4, "int 必须 4 字节");
_Static_assert(1 + 1 == 2, "算术折叠");
```

- `DeclarationLoader.load_node` → `check_static_assert(node, scope, resolver)`
- `StatementExecutor._execute` 也走同一函数（函数体里的断言同样是编译期检查）
- 判据：`fold(cond)` 为假 → `StaticAssertError("static_assert failed: <msg>")`
- 折不动（条件引用了变量）→ `UnsupportedTypeError`，**不能默默放过**

## 一个结构上的调整：把"硬错误"独立出来

原先只有两个桶：

- `pending_errors` —— 惰性装载攒下的**类型错误**，只在 `lazy=False` 的 `link()` 里抛
- `pending_conflicts` —— 重复定义的函数，`link()`/`run()` 都抛

`_Static_assert` 失败属于第二类语义（**装载期就能定论**），但叫 "conflicts" 名不副实。
所以把 `pending_conflicts` 改名 `hard_errors`，方法名 `raise_definition_conflicts`
→ `raise_hard_errors`，并在 `load()` 里按异常类型分流：

```python
if isinstance(error, (DuplicateSymbolError, StaticAssertError)):
    self.hard_errors.append(error)
else:
    self.pending_errors.append(error)
```

这样"为什么这个错误 lazy 也要报"在代码里是**有类型依据的**，不是靠注释约定。

## 度量：50 → 51

```
总计: 51 passed / 61

test_program.py   32 / 40   +1（test_bug3_static_assert）
```

新实现测试 **705 → 713**（新增 `TestStaticAssert` 8 个：算术/sizeof/枚举常量条件、
失败消息、非恒定条件、函数体内、体内失败）。

## 剩下 10 个

| 类 | 用例 |
|---|---|
| B | `type3_constant_folding`（switch + case 范围 + 位域） |
| B | `err_type_mismatch`（字符串字面量） |
| B | `ctrl2_setjmp_longjmp`（setjmp/longjmp） |
| C | 惰性激活时机 ×2、tag 未使用不补全 ×1、strict 可达性 ×1 |
| D | 英文文案 ×2 |
| E | 旧单节点 `execute()` ×1 |

## 验收

- `pytest super_execute/tests` → **713 passed**
- 仓库根 `pytest` → 977 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 51/61
