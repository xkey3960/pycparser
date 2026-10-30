# super_execute · 位域真打包（三步计划第 2 步）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: bitfield, layout

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261030-160027) 位域值语义
**在分支 `feat/bitfield-packing` 上完成，验收后合并回 `refactor/super-execute`。**

## 先量 gcc 的规则，再写代码

C 标准把位域布局定为**实现定义**，所以必须先选一个目标并对齐。用 gcc（mingw 13.2，
`int` 4 字节）实测了 12 组结构体：

| 结构 | gcc sizeof |
|---|---|
| `{unsigned a:3}` | 4 |
| `{unsigned a:3; unsigned b:5}` | 4 |
| `{unsigned a:3; unsigned b:30}` | 8 |
| `{char c; unsigned a:3}` | 8 |
| `{unsigned a:3; char c}` | 8（`c` 在偏移 4） |
| `{unsigned a:3; int n}` | 8（`n` 在偏移 4） |
| `{unsigned a:3; unsigned b:5; int n}` | 8（`n` 在偏移 4） |
| `{unsigned a:20; unsigned b:20}` | 8 |
| `{unsigned a:3; char b:2}` | 8 |
| `{char b:2; unsigned a:3}` | 8 |
| `{unsigned a:31; unsigned b:2}` | 8 |
| `{int n; unsigned a:3; unsigned b:5; char c}` | 12 |

反推出的规则（就是这套实现）：

* 每个位域属于一个"声明类型大小"的存储单元，单元按该类型的对齐要求放置；
* 连续的同类型位域**共用一个单元**，直到放不下；
* 放不下、或类型变了，就另起一个单元；
* 单元之后的普通成员从单元的**末尾**开始。

12 组全部对上。

## 三处结构改动

### 1. 布局（`c_types.py`）

`_layout` 从"按字节依次落位"改成带位域单元的算法，返回四元组
`(大小, 对齐, {成员: 字节偏移}, {成员: (单元偏移, 位偏移, 位宽)})`。

新增 `is_bitfield(name)` / `bit_layout(name)`；`offsetof(name)` 对位域**报错**
（gcc 也不许：`attempt to take address of bit-field`，实测过）。

### 2. 成员寻址：位域没有字节偏移

这是最关键的一点。`struct { unsigned a:3; unsigned b:5; }` 里 a 和 b 落在**同一片
字节**上，`SlotMemory._resolve` 按字节偏移找成员会撞在一起——`(offset, want)` 消不了
歧义（两个都是 unsigned int）。

所以：

* `_resolve` **跳过位域成员**（它们永远不能按字节偏移访问）；
* `MemoryPort` 新增 `read_member` / `write_member`——带着**成员名字**访问，
  只有名字能区分同一个单元里的两个位域；
* 求值器的 `_load_lvalue` / `_eval_assignment` 对位域走这条路，其余成员照旧走地址。

变量定义 `({ int a; })` 那条老路（`_member_container`）仍然用 `_resolve` 找复合对象，
只是不再往下找位域成员。

### 3. 原始存储（`malloc` 出来的结构体）

`RawBuffer` 里位域不能按 `(偏移, 类型名)` 存（会撞），改成按**单元**存一个整数：
`(单元偏移, "bits") -> 打包后的整数`，读时移位+掩码+符号扩展，写时读改写。
`_raw_read` / `_raw_write` 对复合类型改成逐成员调用，于是普通成员与位域共用一套逻辑。

## 一个有意的分歧：旧套件 52 → 51

掉的是 `test_type3_constant_folding`：

```
期望 168，实际 164
```

它算的是 `... + sizeof(struct Bits)`，而 `struct Bits { int a:8; int b:3; }` 在**旧实现**
里是 8 字节（旧实现不打包）。现在按 gcc 是 4，于是总和差 4。

这是**有意的**：新实现比旧实现更接近 C，而不是退化。已在 README 的"已知限制"里
把这条从"位域不打包"改成"位域按 gcc 规则打包（实现定义，12 组实测对齐）"。

## 度量

```
super_execute  809 → 839 tests（+30：布局黄金值 12 + 细节 8 + 其余）
仓库根         952 → 974 passed / 6 skipped
旧套件         52 → 51 / 60（type3 因故意分歧失败）
```

## 验收

- 12 组布局与 gcc 逐条一致
- 5 组 sizeof 现场对照全部 OK
- `offsetof(位域)` 报错
- `pytest super_execute/tests` → 839 passed
