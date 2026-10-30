# super_execute · 内建函数（C 标准库最小实现）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: builtins, libc

父任务：Task(20261012-144135) 重构execute.py
**在分支 `feat/builtins` 上完成，验收后合并回 `refactor/super-execute`。**

## 起点：示例被改过了

动手前发现 `examples/hello.c` 被加了几行：

```c
struct Point *pstPoint = (struct Point *)malloc(sizeof(struct Point));
pstPoint->x = 1;
pstPoint->y = 2;
printf("%u", pstPoint->x);
```

这就是需求：`malloc` + `printf` 要能用。它比"实现 printf"难——因为 `malloc`
返回的存储**没有声明类型**，随后却要当 `struct Point *` 访问。

## 两部分工作

### 1. 内建函数表

```
application/ports/builtin_port.py    契约：has / signature / call / names
frameworks/builtins/table.py         实现 + 签名表
```

共 **44 个函数**：

| 分组 | 函数 |
|---|---|
| 输出 | `printf` `puts` `putchar` `exit` `_exit` |
| 字符串 | `strlen` `strcmp` `strncmp` `strcpy` `strcat` `memcmp` `memcpy` `memset` |
| 内存 | `malloc` `calloc` `free` |
| 数值 | `abs` `atoi` + 10 个 `math.h` |
| 字符 | 6 个 `ctype.h` 判断 + `toupper` `tolower` |

几个实现要点：

* **隐式声明**：`Interpreter` 在装载时把这些名字登记进全局作用域，就像 C89 替编译器
  补上声明——所以 `printf` 不需要 `#include`。用户自己定义同名函数时 `redeclare`
  会覆盖内建的，**自己实现的优先**（有测试钉住）。
* `printf` 的格式串要自己翻译：去长度修饰符（`%ld`→`%d`）、`%p`→`%#x`、
  `%%` 原样。翻译完交给 Python 的 `%`。
  **即使没有实参也要走 `%` 运算**——否则 `printf("100%%")` 会原样输出 `100%%`。
* `exit(n)` 不是错误：抛 `ProgramExit`，`Interpreter.run` 捕获后把 `n` 当程序结果。

### 2. 原始存储（`RawBuffer`）

`malloc` 出来的内存没有声明类型，但普通槽位有——所以原本会报"类型双关"：

```
偏移 0 上是 char，不能用 int 访问（Phase A 的槽位存储不支持类型双关）
```

新增 `RawBuffer`：按**访问时的类型**存值，`(偏移, 类型名) -> 值`；
复合类型**拆开**存（结构体按成员偏移、数组按下标）。这样：

* `p->x = 1` 写 `(0, 'int')`
* `*p = pt` 按成员拆开写，落到同样的键上——两者看到的是同一份数据
* 越界写会报错（按 `ctype.sizeof()` 与缓冲区大小核对）

这不是字节级存储（Phase A 本来也不做宽度截断），但足够支撑 `malloc` 的常见用法。
文档里把"类型双关受限"这条补了例外说明：**`malloc` 的原始存储不在此列**。

## 一次自己造成的事故

用 PowerShell 改文件时写错参数（`Get-Content -Raw utf8`，应为 `-Encoding utf8`），
`$t` 变成 null，`Set-Content` 把两个文件**清空成 3 字节**：
`slot_memory.py` 与 `memory_port.py`。

`git checkout --` 恢复后用手工编辑重做。**这是本次会话第二次栽在同一件事上**
（上次是 `evaluator.py`）。教训重复了，值得写进任务。

## 度量

```
super_execute  759 → 794 tests（+35）
仓库根         904 → 937
旧套件（兼容层）52 / 60（不变——那 8 个失败与内建函数无关）
```

`examples/hello.c`（用户改过的版本）现在输出：

```
1hello.c 的 main() 返回 25
    ↑ printf("%u", pstPoint->x)         ↑ main 的返回值
```

## 顺带修的文档

README 原写着"没有输出"和"没有内建函数"——都改掉了，新增「内建函数」一节
（函数清单 + 四条语义说明），并把"类型双关受限"补上 `malloc` 例外。

## 验收

- `pytest super_execute/tests` → **794 passed**
- 仓库根 `pytest` → 937 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- `py examples/run_hello.py` → 打印 `1`，返回 25
