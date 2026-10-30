# super_execute · 字符串字面量（B 类第 2 项）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, string, heap

父任务：Task(20261012-144135)；前置：Task(20261030-143854) `_Static_assert`
**在分支 `feat/string-literal` 上完成，验收后合并回 `refactor/super-execute`。**

## 为什么先做堆区

字符串字面量的内容必须存在某处，而 `Address` 早就留了 HEAP 区
（`region:8 | offset:24`，16 MiB），只是一直报"heap 留给下一轮"。
这次把它打开：

- `MemoryPort.allocate_heap(ctype, value)` —— 分配并写入初值
- `SlotMemory` 增加堆区游标与块表；`_locate` 分流到 `_locate_heap`
- `HEAP_REGION_SIZE = 16 MiB`（常量之前只在注释里）

堆区没有 `scope_id`（地址里那 8 位并进了偏移），所以整个程序共用一条单调向前的
游标；Phase A 不回收。

## 三处改动

1. **解码**：`interface_adapters/ast/string_literal.py`
   pycparser 把字面量**原样**放在 `Constant.value` 里（带引号也带转义），
   所以要自己解：`\n \t \0 \\ \" \x41 \101`。不认识的转义原样保留那个字符。

2. **类型**：`"abc"` → `char[4]`（含结尾 NUL）。
   在多数表达式里退化成 `char *`（C99 6.3.2.1）——这一步由既有的数组退化逻辑承担。

3. **求值**：内容写进堆区，值是地址。**相同字面量只分配一次**
   （C99 6.4.5p6 说重复字面量是否合并是实现定义的），这样循环里反复求值
   不会把堆撑爆。

## 顺带：让算术错误说清是哪一步

`int + "abc"` 以前只说"算术转换只支持基础类型，收到 int 与 char[4]"，看不出是
哪个运算。现在带上运算本身：

```
二元运算 BinaryOp('+') 的操作数类型不匹配：算术转换只支持基础类型，收到 int 与 char[4]
```

## 度量：51 → 52

```
总计: 52 passed / 61

test_qol2.py      17 / 18   +1（test_err_type_mismatch）
```

新实现测试 **713 → 739**（`test_string_literal.py` 解码 15 个、
`TestStringLiterals` 7 个、堆区 4 个）。

## 剩下 9 个

| 类 | 用例 |
|---|---|
| B | `type3_constant_folding`（switch + case 范围 + 位域） |
| B | `ctrl2_setjmp_longjmp`（setjmp/longjmp） |
| C | 惰性激活时机 ×2、tag 未使用不补全 ×1、strict 可达性 ×1 |
| D | 英文文案 ×2 |
| E | 旧单节点 `execute()` ×1 |

## 验收

- `pytest super_execute/tests` → **739 passed**
- 仓库根 `pytest` → 1003 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py super_execute/compat/run_legacy_tests.py` → 52/61
