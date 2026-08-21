---
tags: [pycparser, program.py, sources.py, 设计文档, 多文件]
created: 2026-08-20
---

# 设计文档：static 文件级作用域 + CLI（S4）

> 问题：`static` 函数/全局变量目前只做"重名降级为警告 + 后者覆盖"（`_func_names`），
> **没有真正的文件级隔离**——两个文件各自的 `static int helper()` 会互相覆盖。
> 真实项目大量 static（内部辅助函数/模块私有状态），隔离是正确链接的关键。
> 现状基线：lab/learning `887197c`（container_of 支持已完成）

---

## 一、现状与问题

| 场景 | 现状 | 问题 |
|---|---|---|
| 两个文件都有 `static int helper()` | 警告 + 后者覆盖 g_functions | 文件 A 调 helper 会拿到 B 的实现（错） |
| 两个文件都有 `static int g` | 全局变量重名，后者覆盖 | A 的 g 和 B 的 g 应互不影响 |
| `static` 前向引用 | 同文件内应可见 | 与普通函数同表，无隔离 |

**C 语义**：`static` 使符号具有**内部链接（internal linkage）**——只在定义它的
编译单元（文件）内可见。跨文件同名 static 互不干扰。

## 二、设计：按文件隔离 static 符号

### 2.1 符号命名空间分层

```
g_functions      — 外部函数（外部链接，跨文件可见，重名冲突）
g_static_funcs   — static 函数（内部链接，按文件隔离）
g_scope(全局)    — 外部全局变量
g_static_globals — static 全局变量（按文件隔离）
```

static 符号存**独立表**，键 = 文件名：
```python
g_static_funcs = {}    # 文件路径 -> {函数名: Function}
g_static_globals = {}  # 文件路径 -> {变量名: value}
```

### 2.2 调用/引用的解析顺序（同文件内优先）

`ExeFuncCall` 查函数时：
1. 当前帧所在文件（StackFrame 增 `file` 字段）的 `g_static_funcs[file]` → 命中则调用
2. 否则 `g_functions`（外部函数）

`ExeID` 读全局变量同理：先查当前文件的 `g_static_globals[file]`，再查全局 g_scope。

### 2.3 注册时的文件归属

- `ExeFuncDef`：若 `decl.storage` 含 `static` → 注册到 `g_static_funcs[当前文件]`，
  **不进入 g_functions**（无跨文件冲突，删除 `_func_names` 的 static 分支）
- `ExeDecl` 顶层全局：`storage` 含 `static` → `g_static_globals[文件]`
- 当前文件 = 激活/装载该文件的路径（文件激活时已切全局作用域，需携带 file 上下文）

### 2.4 与惰性激活的配合

- 索引（`SourceIndex._funcs`）已存 `函数名 -> (路径, FuncDef)`——static 函数
  的惰性激活照常（同文件内调用未命中 → activate_for 定位定义文件）
- `activate_for(name)` 定位后，若定义是 static → 注册到该文件的 static 表

### 2.5 CLI（命令行入口）

`python program.py a.c b.c [--entry main]`：

```python
# program.py 底部
if __name__ == '__main__':
    import sys
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    entry = 'main'
    if '--entry' in sys.argv:
        entry = sys.argv[sys.argv.index('--entry') + 1]
    prog = CProgram(args, entry=entry)
    prog.load()
    print(prog.run())
```

## 三、对现有功能的影响

| 现有能力 | 变化 |
|---|---|
| 外部函数/全局（绝大多数测试） | 不变（static 表为空时行为一致） |
| static 重名（当前 warn+覆盖） | **行为修正**：真正隔离，不再互相覆盖（无警告） |
| 函数指针/惰性/va_list/指针 | 不变（static 函数经表查询，其余走原路径） |
| `_func_names` 冲突检测 | static 分支移除（static 不再参与跨文件冲突） |

## 四、实施步骤

1. `execute.py`：新增 `g_static_funcs`/`g_static_globals` 表 + StackFrame 增 `file` 字段
2. `ExeFuncDef`/`ExeDecl`：static 注册到文件表（需知道当前文件——从激活/装载上下文传入）
3. `ExeFuncCall`/`ExeID`：查表顺序（文件 static 表 → 外部表）
4. `sources.py`：`check_func_conflict` 去 static 分支；索引/激活传当前文件
5. `program.py`：`__main__` CLI 入口
6. 测试：
   - 两文件各 `static int helper()` 返回不同值 → 各自调用正确（隔离）
   - 两文件各 `static int g` → 互不影响
   - static 同文件前向引用可用
   - 外部函数跨文件调用不受影响（回归）
   - CLI：`py program.py a.c b.c` 运行
7. 全量回归 + 文档更新

## 五、验收

- ✅ 两个文件同 `static int helper()`，A 调 A 的、B 调 B 的（不再覆盖）
- ✅ 两个文件同 `static int g`，各自读写独立
- ✅ 外部函数跨文件调用零回归
- ✅ `python program.py a.c b.c` CLI 可用

---

*基线：lab/learning `887197c`* ｜ *关联：设计文档-多文件支持.md（S1-S3）、sources.py（惰性/冲突）、TODO.txt S4*
