---
tags: [pycparser, execute.py, program.py, 设计文档, 编译期]
created: 2026-08-20
---

# 设计文档：_Static_assert 编译期检查（BUG-3）

> 问题：`_Static_assert` 是 C11 编译期检查，当前在 execute() 时**运行时求值**
> （activate/link 的 2 阶段）。语义偏差：① 惰性模式下未激活文件的断言永不检查；
> ② 求值时机混乱（应装载期）。
> 现状基线：lab/learning `fbf6f01`（S4 static 隔离已完成）

---

## 一、现状与问题

```c
_Static_assert(sizeof(int) == 4, "int 必须是 4 字节");
```

当前路径（`ExeStaticAssert.execute`）：`cond = execute(node.cond)` 运行时求值，
activate 2 阶段 / link 2 阶段执行。

**问题**：
1. **惰性模式下未激活文件的断言永不检查**（文件没装载）
2. 语义上 `_Static_assert` 是**编译期**——无论程序跑不跑都应检查
3. cond 应走**常量折叠**（`_eval_constant`）而非通用 execute（可含 sizeof 等编译期表达式）

## 二、设计：装载阶段一次性检查（编译期）

### 2.1 检查时机

移到**文件装载（activate / link 1a 类型阶段后）**，与类型注册同时——所有断言在
"程序装载"时检查，不依赖运行路径：

- `sources.activate`：1a 类型阶段后遍历 StaticAssert（cond 折叠求值）
- `program.link`：1a 后同理
- `ExeStaticAssert`：保留（运行路径也可能遇到函数体内的 `_Static_assert`，
  C23 允许块内静态断言）——但改为**折叠求值**

### 2.2 求值方式

```python
def _check_static_assert(node):
    """编译期检查：cond 用常量折叠求值；失败抛错。"""
    cond = _eval_constant(node.cond)          # 编译期常量折叠（sizeof/算术）
    if cond is None:
        cond = execute(node.cond)             # 回退（宽松）
    if not cond:
        msg = node.message.value if node.message else ""
        raise AssertionError(f"static_assert failed: {msg}")
```

### 2.3 错误信息

失败时带源码位置（QOL-1）：`static_assert failed: <msg>`（coord 由 execute 包装附上）。

## 三、对现有功能的影响

| 现有能力 | 变化 |
|---|---|
| 顶层 `_Static_assert`（activate/link） | **时机提前**：装载阶段检查（不再等运行时） |
| 惰性未激活文件 | L4 起 activate_all **装载全部文件** → 顶层断言总是检查（符合 C 编译期语义：断言与运行路径无关） |
| 函数体内 `_Static_assert`（C23） | 保留运行时检查（折叠求值） |
| cond 含 sizeof/算术 | 折叠求值（`_eval_constant`） |
| 现有测试（test_static_assert） | 不变（值路径兼容） |

## 四、实施步骤

1. `execute.py`：`ExeStaticAssert` 改用折叠求值（`_eval_constant` 优先）
2. `sources.py` `activate`：1a 后遍历 StaticAssert 检查（编译期）
3. `program.py` `link`：1a 后同样检查
4. 测试：
   - 顶层 `_Static_assert(sizeof(int)==4, ...)` 通过
   - 顶层 `_Static_assert(1==2, "fail")` → 装载时报错
   - 惰性模式坏断言文件不激活 → 不报（与惰性一致）
   - 函数体内 `_Static_assert` 运行时检查（回归）
5. 全量回归 + 文档更新

## 五、验收

- ✅ 顶层 `_Static_assert` 在装载（load+run / link）时检查，cond 折叠求值
- ✅ 失败的断言报错含消息（static_assert failed: <msg>）
- ✅ 惰性 activate_all 装载全部文件 → 顶层断言总是检查（C 编译期语义）
- ✅ 既有测试零回归

---

*基线：lab/learning `fbf6f01`* ｜ *关联：TODO.txt BUG-3、typesys._eval_constant（TYPE-3）、execute.py ExeStaticAssert*
