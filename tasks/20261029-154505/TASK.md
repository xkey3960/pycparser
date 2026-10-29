# super_execute · 内存端口与作用域内存（MemoryPort + SlotMemory）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, memory, frameworks

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261029-150452) 类型系统

## 目标

让 `Address` 真的可解引用——把前两轮的 `Address`（编址）与 `CType`（大小/对齐）
接上，并收掉 D3 留下的那半句："作用域销毁后解引用必须报错"。

## 关键设计决定（实现中修正的一条）

**`read`/`write` 必须带访问类型 `CType`。** 原计划签名是 `read(address)`，
实现到一半发现它无解：C 里首成员的地址与对象本身相同（`&s.a == &s` 当 a 在偏移 0），
只凭地址分不清"读整个结构体"还是"读那个 int"；联合体更极端——所有成员都在偏移 0。
**只有类型能消歧**，所以端口签名改成 `read(address, ctype)` / `write(address, value, ctype)`。
这不是实现偷懒，是 C 语义要求；Phase B 换成字节后同样需要它。

其余决定：

- **Phase A 槽位式**（D2）：值仍是 Python 对象，但按地址索引。复合值用
  `dict[str, Any]`，数组用 `list`。Phase B 再换成字节数组，端口不变。
- **只实现 scope 区**。heap 留给下一轮（需要 first-fit + free），
  function 区不是字节内存而是表（见下），访问 heap 会显式抛
  `RegionNotImplementedError`。
- **函数区**：`FunctionTable` 把"函数名"变成"函数地址"（表下标，不是字节）。
  TASK.md 要的"函数指针和普通指针同构"由此成立——旧实现用函数名字符串当指针，
  既存不进内存也不能比较。
- **类型双关显式拒绝**：Phase A 是槽位存储，做不到按字节重解释，遇到
  `*(char*)&int_var` 这类访问直接报 `MemoryAccessError`，而不是返回错值。

## 交付

```
application/ports/memory_port.py      MemoryPort 协议（依赖倒置的接缝）
frameworks/memory/slot_memory.py      作用域内存：分配 / 读写 / 成员投影 / 悬空检测
frameworks/memory/function_table.py   函数区：函数名 ↔ 函数地址
tests/unit/frameworks/test_slot_memory.py
tests/unit/frameworks/test_function_table.py
```

能力（都有测试）：

- 按 `sizeof`/`alignof` 顺序落位，char 之后放 int 会跳过 3 字节 padding；
- 标量、数组元素（`base + i*sizeof(elem)`）、结构体成员（`base + offsetof`）、
  嵌套结构体成员、结构体数组、联合体成员（靠类型消歧）全部可读写；
- 越界（落在对象之间的洞 / 越过标量自身 / 元素下标超界）、
  作用域未创建、作用域已销毁、地址区未实现、类型不符，各有明确异常。

## 验收

- `pytest super_execute/tests` → **355 passed**（原 295，+60）
- 仓库根 `pytest` → 619 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- **变异测试 11/11 全部杀死**（分配不对齐、去掉容量检查、去掉悬空检查、
  数组下标算错、成员不按类型消歧、去掉类型相容检查、越界放行、标量别名不拦、
  函数地址不递增、函数重复登记覆盖）

## 已知边界（记录在案）

- **D3 的代价**：8 位 id 空间装不下"代"，id 复用后旧地址会静默命中新作用域。
  已用 `test_stale_address_aliases_reused_scope` 刻意钉住这个行为，
  兜底手段是"不要让 id 在活跃期被复用"。
- heap 区未实现；`malloc` 那一轮补。
- Phase A 的复合值（dict/list）是临时表示，Phase B 会被字节取代。

## 下一步

application 用例层：`declare_variable` / `read_variable` / `write_variable` /
`take_address` / `load` / `store`，把 Scope（名字）+ TypeResolver（类型）+
MemoryPort（存储）串起来，替换旧 `execute.py` 里那 48 处 `g_scope.get`。
