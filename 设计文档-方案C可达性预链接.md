---
tags: [pycparser, program.py, sources.py, 设计文档, 惰性解析]
created: 2026-08-20
---

# 设计文档：方案 C — strict 可达性预链接

> 问题：惰性模式（L4）是"装载全部文件 + 类型 lazy"——**可达路径的类型错误在
> 运行时才暴露**。方案 C 给 `strict=True` 加"运行前对**可达部分**完整检查"：
> 保留"不可达坏代码不报"，同时把可达错误的暴露时机提前到运行前。
> 现状基线：lab/learning `44dd015`（BUG-3 StaticAssert 已完成）

---

## 一、动机与对比

| 对比 | L4 惰性（现状） | 方案 C（strict 预链接） |
|---|---|---|
| 检查时机 | 用时才检（运行时） | **运行前**（只查可达） |
| 不可达坏代码 | 永不报错 | 永不报错 ✅ 同样满足 |
| 可达错误暴露 | 运行时（晚） | 运行前（早，更 C 风格） |
| 冲突检测 | 启动时全量 | 只查可达部分 |

**核心承诺**："运行 main 时，不碰 helper 所在文件就不检查它"——方案 C 把这个
承诺**严格化**：不只不检查，连装载/检查都按可达性圈定。

## 二、设计：可达性依赖图 + 预链接

### 2.1 可达性收集（依赖图遍历）

从入口函数出发，迭代收集可达符号，直到不动点：

```
可达集合 R = {入口函数}
循环：
  对 R 中每个函数 f：
    scan(f.body) 收集：
      - 函数调用目标 g → R ∪= {g}（g 的定义文件加入）
      - 类型引用（参数/返回/成员/变量声明）→ 类型定义文件加入
  对 R 中每个类型 t：其定义文件加入
直到 R 不再增长
```

**scan 的 AST 遍历**（`_collect_deps(node)`）：
- `FuncCall` → 目标函数名（ID 直接调用）
- `Decl.type` / `Typedef` / `Cast.to_type` → `type_of_decl` 引出的类型名（struct/enum/union/typedef）
- 递归遍历子节点

**实现**：`SourceIndex.reachable(entry)` → 返回可达**文件集合**（利用现有索引
`_funcs`/`_tags`/`_typedefs`：符号名 → 定义文件）。

### 2.2 预链接（strict 模式）

`CProgram(strict=True, lazy=True)` 时，`run()` 改为：

```python
if self.strict and self.lazy:
    # 方案 C：只对可达文件做完整检查（link 语义的 1a 全量 + 冲突 + 布局）
    reachable = g_source_index.reachable(self.entry)   # 文件集合
    for path in reachable:
        activate(path)                                  # 装载（类型注册不布局）
    # 对可达类型全量补全（布局/重定义冲突/类型错误在此暴露）
    _complete_reachable_types()
```

关键点：
- **装载范围**：只 `activate` 可达文件（不可达文件不装载——比 L4 的 activate_all 更窄）
- **检查范围**：可达类型全量 `ensure_complete`（布局错误运行前暴露）
- **全局变量**：可达文件的全局 init 照常在装载时执行（C 语义）；不可达文件不执行
- **入口/冲突**：可达文件内的函数重名/typedef 冲突照常检测（strict 报错）

### 2.3 与 L4 惰性的关系

| 模式 | 行为 |
|---|---|
| `lazy=True, strict=False`（默认） | L4 现状：activate_all + 类型 lazy（不变） |
| `lazy=True, strict=True` | **方案 C**：只装载+检查可达文件 |
| `lazy=False` | 显式 link 全量检查（不变） |

## 三、对现有功能的影响

| 现有能力 | 变化 |
|---|---|
| 默认惰性（strict=False） | 不变（L4 行为） |
| strict=True 惰性 | **新增**：运行前检查可达部分 |
| 不可达坏文件 | strict 下同样不报（可达性圈定） |
| 全局变量 init | 可达文件照常（启动时）；不可达文件不执行 |
| lazy_bad.c 场景 | strict 下若不可达仍不报 ✅ |
| 惰性基础设施（索引/激活/钩子） | 复用，不变 |

## 四、实施步骤

1. `sources.py`：新增 `reachable(entry)` —— 从入口 BFS 收集可达文件
   （函数体 scan 函数调用 + 类型引用，迭代至不动点）
2. `sources.py`：`_collect_deps` AST 遍历器（FuncCall 目标 / 类型引用）
3. `program.py`：`CProgram` 增 `strict` 与 lazy 组合时 run() 走预链接路径
4. `program.py`：`_complete_reachable_types()` —— 可达类型全量补全
5. 测试：
   - strict 下：main → helper_a（可达），helper_b 不可达且坏 → 不报
   - strict 下：可达路径的类型错误 → 运行前报错
   - 默认惰性（strict=False）行为不变（回归）
   - 不可达坏文件（lazy_bad 场景）strict 下不报
6. 全量回归 + 文档更新

## 五、验收

- ✅ `strict=True` 惰性：**运行前**检查可达路径类型错误（比默认惰性早）
- ✅ 不可达坏文件 strict 下不报（可达性圈定生效）
- ✅ 默认惰性（strict=False）零回归
- ✅ 可达文件的全局 init 照常；不可达文件不装载

---

*基线：lab/learning `44dd015`* ｜ *关联：设计文档-惰性解析.md（方案 B/C 对比）、sources.py（索引/激活）、TODO.txt 方案 C*
