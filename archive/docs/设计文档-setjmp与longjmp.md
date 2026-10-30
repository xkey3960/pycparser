---
tags: [pycparser, execute.py, 设计文档, 控制流]
created: 2026-08-20
---

# 设计文档：setjmp / longjmp（CTRL-2）

> 问题：`setjmp`/`longjmp` 是非局部跳转——longjmp 从**深处**跨多个函数栈帧
> 跳回 setjmp 处，setjmp "返回两次"（第一次 0，longjmp 后返回传入值）。
> 依赖 MEM-2 的 g_call_stack 做 unwinding。
> 现状基线：lab/learning `a9401d2`（CTRL-1 Goto 已完成）

---

## 一、语义

```c
jmp_buf buf;
if (setjmp(buf) == 0) {
    /* 第一次进入（正常路径） */
    deep_function();        /* 内部可能 longjmp(buf, 5) */
} else {
    /* longjmp 跳回后的路径（setjmp 第二次返回 5） */
    handle_error();
}
```

关键语义：
1. `setjmp(buf)` 第一次调用返回 **0**
2. `deep_function` 里 `longjmp(buf, 5)` → **跨所有中间函数帧**跳回 setjmp 调用点
3. setjmp **第二次返回 5**（非 0）→ `if` 走 else 分支
4. 中间函数的栈帧全部丢弃（局部变量失效）

## 二、设计：LongJmpException + setjmp 调用点重放

### 2.1 核心机制

```
setjmp(buf)（ExeFuncCall 拦截）：
  _JMP_BUFS[buf名] = {depth: len(g_call_stack), compound: 当前Compound, idx: 当前语句索引}
  返回 0

longjmp(buf, val)：
  抛 LongJmpException(buf, val)

LongJmpException 传播：
  - 穿过各 ExeFuncCall 的 finally（弹栈，丢弃中间帧）
  - 各 Compound 捕获时检查：记录中的 compound 是否是自己
      * 是 → 跳回 setjmp 语句索引重放（setjmp 这次返回 val）
      * 否 → 继续传播
```

**调用点重放**（关键）：setjmp 所在 Compound 捕获 LongJmpException 后，跳回
`idx`（setjmp 所在语句）重新执行——此时 setjmp 拦截发现 `_JMP_BUFS[buf].retval`
已设置 → 返回 val（非 0）→ `if (setjmp(buf))` 走 else 分支 → 之后继续执行。
setjmp 之前的语句不重放（idx 是 setjmp 语句本身）。

### 2.2 模块状态

```python
_JMP_BUFS = {}          # buf 变量名 -> {depth, compound, idx, retval}
_ACTIVE_COMPOUND = None # ExeCompound 执行时记录（setjmp 定位调用点）
_ACTIVE_STMT_IDX = 0

class LongJmpException(Exception):
    def __init__(self, buf, val):
        self.buf = buf
        self.val = val
```

### 2.3 Compound 改造

`ExeCompound` 的 while 循环：
```python
i = 0
while i < len(items):
    _ACTIVE_COMPOUND = self
    _ACTIVE_STMT_IDX = i
    item = items[i]
    try:
        result = execute(item)
    except GotoException as g:
        ...（现有）
    except LongJmpException as e:
        rec = _JMP_BUFS.get(e.buf)
        if rec and rec['compound'] is self:
            rec['retval'] = e.val      # 标记：setjmp 第二次返回 val
            i = rec['idx']             # 跳回 setjmp 语句重放
            continue
        raise                            # 非本层 → 传播
    i += 1
```

### 2.4 setjmp/longjmp 拦截（ExeFuncCall，类似 va_list）

```python
if func_name == 'setjmp':
    buf = _arg_id(0)
    _JMP_BUFS[buf] = {'depth': len(g_call_stack),
                      'compound': _ACTIVE_COMPOUND,
                      'idx': _ACTIVE_STMT_IDX,
                      'retval': 0}
    return 0
if func_name == 'longjmp':
    buf, val = _arg_id(0), 求值第2实参
    raise LongJmpException(buf, val)
```

setjmp 第二次执行（重放）：若 `_JMP_BUFS[buf]['retval']` 非 0 → 取走并返回。

### 2.5 jmp_buf 类型

`jmp_buf` 内建注册（typesys）：`typedef int jmp_buf[1]`（数组）或直接 int。
`setjmp(buf)` 的 buf 是变量名（宏展开后 `setjmp(buf)` → 实参是 ID）。

## 三、对现有功能的影响

| 现有能力 | 变化 |
|---|---|
| 函数调用/栈帧（MEM-2） | 不变（LongJmpException 只额外穿过，finally 弹栈照旧） |
| goto（CTRL-1） | 不变（GotoException 与 LongJmpException 独立捕获） |
| return/break/continue | 不变 |
| 普通程序（无 setjmp） | 零影响（_JMP_BUFS 空） |
| 嵌套 setjmp（多 buf） | 支持（按 buf 名区分） |

## 四、实施步骤

1. `execute.py`：新增 `LongJmpException` + `_JMP_BUFS` + `_ACTIVE_COMPOUND/_ACTIVE_STMT_IDX`
2. `ExeCompound`：while 循环记录位置 + 捕获 LongJmpException（重放）
3. `ExeFuncCall`：拦截 `setjmp`/`longjmp`（同 va_list 模式，_arg_id 取 buf 名）
4. `typesys.py`：内建注册 `jmp_buf`（int）
5. 测试：
   - `setjmp` 第一次返回 0；longjmp 后 else 分支执行
   - 跨多层函数 longjmp（main → a → b，b 里 longjmp 回 main）
   - longjmp 返回指定值（非 0）
   - 未调用 setjmp 就 longjmp → 报错
   - 普通程序零回归
6. 全量回归 + 文档更新

## 五、验收

- ✅ `if (setjmp(buf))` 模式：第一次 0 / longjmp 后 val（走 else）
- ✅ 跨多层函数 unwinding（中间帧丢弃）
- ✅ 未 setjmp 就 longjmp 明确报错
- ✅ 既有测试零回归

---

*基线：lab/learning `a9401d2`* ｜ *关联：TODO.txt CTRL-2、execute.py g_call_stack（MEM-2）/GotoException（CTRL-1）*
