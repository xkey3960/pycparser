---
tags: [pycparser, execute.py, 设计文档, 控制流]
created: 2026-08-20
---

# 设计文档：Goto 与标签（CTRL-1）

> 问题：`goto label;` 目前抛 `Goto is not supported`。解释器逐语句执行，
> goto 需要知道 label 在**哪里**（两遍扫描：先收集 Label → 语句索引，再跳转）。
> 现状基线：lab/learning `3157133`（方案 C 已完成）

---

## 一、现状与设计思路

C 的 goto 是**函数内**跳转（不能跨函数）。当前 `ExeGoto` 直接抛错。

**TODO 设计**（两遍扫描）：
1. 第一遍：`Compound` 执行时扫描 `block_items` 收集 `Label → 语句索引`
2. 第二遍：`goto` 执行时抛 `GotoException(label)`，外层 `Compound` 捕获后
   跳到对应语句继续

**C 语义**：goto 可以向前或向后跳；不能跳进另一个函数的内部；可跳出循环/switch
（break 的泛化）。

## 二、设计：GotoException + Compound 标签表

### 2.1 异常与标签表

```python
class GotoException(Exception):
    """goto 跳转信号：携带目标标签名。"""
    def __init__(self, label):
        self.label = label

# Compound 执行时构建的标签索引：label 名 -> 语句索引
# （g_scope 之外用模块级或 Compound 内部局部？——用 Compound 执行时的局部 dict）
```

### 2.2 Compound 两遍扫描

```python
class ExeCompound(Execute):
    def execute(self):
        ...
        items = self.node.block_items or []
        # 第一遍：收集 Label -> index（同层，不递归进嵌套块）
        label_index = {}
        for i, item in enumerate(items):
            if isinstance(item, Label):
                label_index[item.name] = i
        # 第二遍：顺序执行，goto 时按索引跳转
        i = 0
        while i < len(items):
            item = items[i]
            try:
                result = execute(item)
            except GotoException as g:
                if g.label in label_index:
                    i = label_index[g.label]
                    continue          # 跳到目标语句（其后继续）
                raise               # 本层无此标签 → 传给外层（嵌套块场景）
            i += 1
        ...
```

**关键**：goto 的目标 label 在同层收集（`Label` 直接是 block_items 成员）；若本层
找不到（嵌套在 if/while 里的 goto 跳外层标签）→ GotoException 向上传播，外层
Compound 捕获。**跨层向前/向后跳都支持**（label 索引可前可后）。

### 2.3 ExeLabel / ExeGoto

```python
class ExeLabel(Execute):
    """Labeled statement：标签本身不做事，执行其语句。"""
    def execute(self):
        if self.node.stmt is not None:
            execute(self.node.stmt)

class ExeGoto(Execute):
    """Goto statement：抛 GotoException（由 Compound 捕获跳转）。"""
    def execute(self):
        raise GotoException(self.node.name)
```

### 2.4 与 break/continue/return 的关系

- break/continue 用各自异常，goto 用 GotoException——互不干扰
- goto 跳出循环：循环体的 Compound 处理 goto（其 Label 在同层？不——goto 跳出
  while 要跳**循环外**的 label，那是外层 Compound 的 label）。循环内 goto 抛
  GotoException，穿过 while（while 不捕获 GotoException，只捕 break/continue），
  被外层 Compound 捕获 → 正确跳转
- goto 跨函数：C 不允许——函数体是独立 Compound（函数调用栈帧），goto 不会穿出
  （外层是调用方函数的不同执行，label 不在其 block_items 同层）→ 自然报错（未捕获）

## 三、对现有功能的影响

| 现有能力 | 变化 |
|---|---|
| `goto`（原抛错） | **支持**：同函数内任意方向跳转 |
| break/continue/return | 不变（各自异常独立） |
| 嵌套块 / 循环内 goto 跳外层 | 支持（GotoException 穿透，外层捕获） |
| 函数内 label 重名 | C 不允许（gcc 报错）；解释器宽松（后者覆盖索引） |
| 跨函数 goto | 不支持（C 语义，自然抛"未捕获 GotoException"） |

## 四、实施步骤

1. `execute.py`：新增 `GotoException`
2. `ExeCompound`：两遍扫描（label 索引 + 索引跳转执行）
3. `ExeGoto`：抛 `GotoException(node.name)`（替换 AssertionError）
4. 测试：
   - `goto` 向前跳（跳过语句）
   - `goto` 向后跳（循环）
   - goto 跳出循环（到循环外 label）
   - goto 嵌套 if 内跳外层 label
   - 跨函数 goto → 报错（回归：不崩溃，明确报错）
5. 全量回归 + 文档更新

## 五、验收

- ✅ `goto` 向前/向后跳转正确（同函数内）
- ✅ goto 跳出循环 / 嵌套块跳外层 label
- ✅ 既有控制流（break/continue/return）零回归
- ✅ 跨函数 goto 明确报错

---

*基线：lab/learning `3157133`* ｜ *关联：TODO.txt CTRL-1、execute.py ExeCompound/ExeGoto/ExeLabel*
