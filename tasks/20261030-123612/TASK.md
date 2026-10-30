# super_execute · 表达式求值与语句执行（能跑 C 程序了）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, evaluator, interpreter

父任务：Task(20261012-144135) 重构execute.py；前置：Task(20261030-121908) interface adapter

## 目标

最后一块：让新架构真的**跑**起来。分两个提交。

### 提交一：表达式（546 passed）

```
domain/services/conversions.py        整型提升 + 寻常算术转换
interface_adapters/ast/inference.py   表达式 → CType
interface_adapters/ast/evaluator.py   求值：eval() 出值，lvalue() 出地址
```

C 的表达式只有两种命运：算出一个值，或者算出一个地址。所以求值器有两个入口，
`StructRef`/`ArrayRef`/`*p` 在 `lvalue()` 里被翻译成"基地址 + 偏移"——
`&s.m`、`*p = 1`、`a[i] += 1` 于是全是同一套机制。

**C 与 Python 语义不同的地方**（旧实现踩过的坑，现在有专门测试钉住）：

| 语义 | 例 |
|---|---|
| 整型除法向零截断 | `7/2=3`、`-7/2=-3`（Python `//` 是向下取整） |
| 取模与被除数同号 | `-7%3=-1` |
| 指针算术按元素缩放 | `p+1` 跳过 `sizeof(*p)` |
| 指针相减得元素个数 | `&a[2]-&a[0]=2` |
| `&&`/`\|\|` 短路 | `0 && (i/0)` 不炸 |

### 提交二：语句与函数调用（587 passed）

```
interface_adapters/ast/statements.py   Compound/Decl/Typedef/If/While/DoWhile/For/
                                       Return/Break/Continue + 表达式语句兜底
interface_adapters/ast/interpreter.py  门面：装载 → 调 main；函数作用域与形参绑定
```

控制流用异常实现（`ReturnSignal`/`BreakSignal`/`ContinueSignal`），不必给执行器
维护显式的"当前循环/函数"栈。函数体存在解释器里（`dict[str, FuncDef]`），
不塞进 `FunctionSymbol`——符号只该知道名字、类型、地址。

## 测试抓到的四个真实缺口

1. **数组名没有退化成指针**：`int *p = a;` 原来把整个 list 当值传给指针变量。
   补 `array_to_pointer`（C99 6.3.2.1），形参与取值两处都要退。
2. **函数体内的 typedef 没处理**：执行器只认 `Decl`，`typedef` 节点被静默跳过。
   这恰是旧的扁平类型表的漏点。
3. **函数指针调用的报错不对**：报成"未定义的函数"，因为 `call()` 只在文件作用域找。
   改为在当前作用域找，并明确提示"函数指针调用还没接"。
4. **`while` 里的 break/continue 没测**：变异测试把 `while` 的 break 捕获删掉，
   测试仍全绿——因为只有 `for` 测了 break。已补。

## 验收

- `pytest super_execute/tests` → **587 passed**
- 仓库根 `pytest` → 851 passed / 6 skipped
- `ruff check` / `ruff format --check` 全绿
- **变异测试 37/37 全部杀死**
  - 表达式层 11 个（含"指针退化成目标类型""数组长度恒 None"等）
  - 语句/解释器 10 个（if 恒真、break/continue 不捕获、块不进作用域、
    return 丢值、初值被忽略、函数内 typedef 不登记、形参不绑定、形参顺序反转、
    数组不退化成指针）
  - 另有前面几轮的 16 个

## 实测

**仓库里真实存在的文件** `test/multi/lib.c`：

```
装载成功
  helper()        = 42
  sum_pt({10,20}) = 30
```

**13 个内联程序**全部跑出正确结果，包括 `fib(10)=55`、`fac(5)=120`、
结构体按值传参、指针交换、数组+指针、`for`+`break`/`continue`、
以及仓库 `test/multi/ptr_main.c` 里的同款指针程序（99+37=136）。

## 已知边界

- **不支持**：`switch` / `goto` / 字符串字面量 / 函数指针调用 / 可变参数调用 /
  初始化列表（`{1,2,3}`）/ heap（`malloc`）/ 内建函数（`printf` 等）
- **递归深度上限约 127**：每次调用占 2 个作用域 id（函数作用域 + 函数体块），
  8 位 id 空间；超过会报 id 用尽，而不是静默出错。
- **值不做宽度截断**：Phase A 用 Python 整数，`char` 溢出不会回绕。

## 下一步

把旧 `execute.py` 的能力补齐到新实现（switch/goto/内建函数/初始化列表/heap），
然后按 strangler 收尾：让新实现通过旧的 264 个测试，最后下线旧代码。
