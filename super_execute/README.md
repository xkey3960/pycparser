# super_execute —— C 语言解释器

用 Python 写的 C 解释器：把 `.c` 文件解析成 AST，逐条解释执行，返回 `main` 的结果。
它按 **clean architecture** 分层，是本仓库现在的唯一现役实现
（旧的 `execute.py` 已下线并归档到 `../archive/`）。

## 快速开始

```bash
cd pycparser/super_execute
py examples/run_hello.py
# → 1hello.c 的 main() 返回 25
#   ↑ printf 的输出（example 里 malloc 了一个 struct 并打印它的 x）
```

`examples/` 里是一对最小样例：

| 文件 | 内容 |
|---|---|
| `examples/hello.c` | 结构体数组、按值传参、循环、`switch`、三目、`malloc`、`printf` |
| `examples/run_hello.py` | 读文件 → 解析 → 装载 → 运行 → 打印返回值 |

## 三步跑一个 C 程序

```python
from pycparser.c_parser import CParser
from super_execute.interface_adapters.ast.interpreter import Interpreter

source = open("hello.c", encoding="utf-8").read()

# 1) 解析：第二个参数是文件名，只用于报错定位
ast = CParser().parse(source, "hello.c")

# 2) 装载：可以多次调用，每次一个翻译单元（多文件程序就这么装载）
interpreter = Interpreter()
interpreter.load(ast, "hello.c")

# 3) 运行：返回 main 的返回值
print(interpreter.run())
```

### 关于注释和 `#include`

**pycparser 的 `CParser` 不接受注释，也不处理 `#include`**——这些是预处理器的活。
示例刻意写成了无注释、无 include 的形式，好让上面那段代码零依赖直接跑。

真实项目请走 `gcc -E`：

```python
import pycparser

ast = pycparser.parse_file(
    "hello.c",
    use_cpp=True,
    cpp_path="gcc",
    cpp_args=["-E", "-Iutils/fake_libc_include"],  # 注意要自己加 -E
)
```

GNU 扩展（`typeof`、语句表达式、`__attribute__`、`case 1 ... 5`）需要
`pycparserext`：

```python
from pycparserext.ext_c_parser import GnuCParser

ast = GnuCParser().parse(source, "hello.c")
```

没装 `pycparserext` 也能用——只是这类扩展会解析失败。适配器把它当**可选依赖**。

### 调用其他函数 / 传参

```python
interpreter.run("main")            # 指定入口
interpreter.call("add", [2, 3])    # 直接调某个函数
```

## 分层

依赖只向内：

```
domain               纯 C 语义：类型、作用域、符号、地址、值转换规则
  ↑
application          用例与端口：DeclareVariable / LoadValue / MemoryPort ...
  ↑
interface_adapters   AST → 用例：TypeBuilder / Evaluator / 语句执行器 / Interpreter
  ↑
frameworks           可替换的基础设施：SlotMemory、FunctionTable
```

```
super_execute/
├── domain/
│   ├── value_objects.py          地址、枚举（ScopeKind / Linkage / ...）
│   ├── entities/                 c_types / scope / symbol
│   └── services/                 类型解析、转换、布局、常量折叠、等价判断
├── application/
│   ├── ports/                    MemoryPort / TypeResolverPort / FunctionTablePort
│   └── use_cases/                声明变量、读写值、取地址、函数表
├── interface_adapters/ast/       TypeBuilder / Evaluator / inference / statements /
│                                 const_eval / string_literal / Interpreter
├── frameworks/memory/            SlotMemory（槽位存储）、FunctionTable
├── tests/                        759 个测试
├── examples/                     本文档用到的样例
└── compat/                       兼容层：让归档的旧测试跑在新实现上
```

`Interpreter` 是唯一的门面；测试里大量直接注入 `SlotMemory` / 分配器来构造场景。

## 地址模型

指针真的只是一个 4 字节整数（`ADDRESS_SIZE = 4`）：

```
31        24 23        16 15                          0
┌───────────┬────────────┬─────────────────────────────┐
│  region   │ scope_id   │          offset             │
└───────────┴────────────┴─────────────────────────────┘
```

| region | 含义 | 次高字节 |
|---|---|---|
| 0 | `SCOPE`（栈/全局） | `scope_id` 1..255，每作用域 64 KiB |
| 1 | `HEAP` | 并入偏移，共 16 MiB |
| 2 | `FUNCTION` | 并入偏移，函数表下标 |

`NULL` 就是 `0`。悬空地址（作用域已销毁）会被检测并报错，而不是读到垃圾。

## 支持的 C 特性

| 类别 | 内容 |
|---|---|
| 类型 | 基础类型（见下表）、指针、数组（含多维、零长）、结构体/联合体/枚举、typedef、函数类型、函数指针 |
| 声明 | 全局/局部变量、`static`（**按文件隔离**）、`extern`、初始化列表与指定初始化器 `{.b=5}` `{[1]=7}` |
| 表达式 | 全部算术/位/比较/逻辑运算、赋值与复合赋值、三目、`sizeof`、强转、`&`/`*`、成员/下标、函数调用、逗号、**字符串字面量** |
| 语句 | `if` / `while` / `do-while` / `for` / **`switch`（含 fall-through）** / `break` / `continue` / `return` / **`goto` 与标签** / 块 |
| 编译期 | **常量折叠**（数组维度、枚举值、case 标签、`_Static_assert`） |
| GNU | 零长数组、语句表达式 `({...})`、`typeof`、`__attribute__`（解析后忽略）、`case 1 ... 5`、`offsetof` 惯用法 |

基础类型与尺寸：

| 类型 | 字节 |
|---|---|
| `char` | 1 |
| `short` | 2 |
| `int` | 4 |
| `long` | 4 |
| `long long` | 8 |
| `float` / `double` | 4 / 8 |
| 指针 | **4** |

## 内建函数

解释器不链接 libc，而是用 Python 复刻了一份常用 C 库函数。**不需要 `#include`**——
解释器会像 C89 那样替你补上声明：

```c
int main(void) {
    printf("%d\n", 42);                       /* 直接用，不用 stdio.h */
    char *p = malloc(16);                     /* 不用 stdlib.h */
    struct Point *q = malloc(sizeof(struct Point));
    q->x = 1;                                 /* 裸内存按 struct 访问 */
    return strlen("hello");
}
```

| 分组 | 函数 |
|---|---|
| 输出 | `printf` `puts` `putchar` `exit` `_exit` |
| 字符串 | `strlen` `strcmp` `strncmp` `strcpy` `strcat` `memcmp` `memcpy` `memset` |
| 内存 | `malloc` `calloc` `free` |
| 数值 | `abs` `atoi` `sqrt` `pow` `fabs` `floor` `ceil` `fmod` `sin` `cos` `tan` `exp` `log` |
| 字符 | `isdigit` `isalpha` `isalnum` `isspace` `isupper` `islower` `toupper` `tolower` |

几条语义说明：

* **自己定义的函数优先**：写了 `int puts(char *s) {...}` 就用你的，内建的让位。
* `printf` 支持 `%d %i %u %x %X %o %c %s %p %f %e %g %%` 和宽度/精度/对齐，
  **长度修饰符会被忽略**（`%ld` 当 `%d`）。
* `malloc` / `calloc` 返回的存储**没有声明类型**，随后按什么类型访问都行
  （见下面"原始存储"）；`free` 是空操作——Phase A 的堆不回收。
* `exit(n)` 不是错误：它终止程序，`main` 的结果就是 `n`。
* 内建函数没有 `va_arg`：能调用，但函数体里拿不到多余实参。

## 已知限制与刻意的偏差

这些不是 bug，是**当前实现的选择**，写在这里免得当成 bug 追：

| 限制 | 说明 |
|---|---|
| **位域不打包** | `struct { int a : 8; int b : 3; }` 的 `sizeof` 是 8（每个位域占满声明类型）。gcc 会给 4。宽度本身会折叠并校验 |
| **整数宽度不截断** | Phase A 用 Python 整数存值：`char c = 300` 不会回绕成 44，溢出也不回绕 |
| **未初始化变量按零值** | C 里是未确定值；这里一律零初始化（可复现优先） |
| **数组越界报错** | C 里是未定义行为；这里检测并报 `OutOfBounds` |
| **类型双关受限** | 普通变量按另一种类型读同一块存储会被拒绝。**但 `malloc` 的原始存储不在此列**——它本来就没有声明类型 |
| **没有 `setjmp`/`longjmp`** | 需要跨帧 unwind，未实现 |
| **没有 `va_arg`** | 可变参数函数能声明、能调用，但函数体贴不到多余实参 |
| **switch 不能从外部跳进** | `goto` 跳进 `switch` 内部不支持（跳出去可以） |

另外两条实现细节：字符串字面量放在 HEAP 区，**相同字面量只分配一次**；
`main` 执行到结尾的 `}` 等价于 `return 0;`（C99 5.1.2.2.3）。

## 错误报告

出错时会打印一份报告，再抛出异常，两者都能用：

```
[error] hello.c:12:9: 未定义的标识符 'zz'（查找路径 block#7 -> function#6 -> unit#2 -> file#1）
调用链: main → helper → inner
```

- **位置**精确到出错的那个节点（最内层），不是最外层语句
- **调用链**是函数调用路径
- 异常体系在 `domain/exceptions.py`，基类是 `DomainError`，按语义分类
  （`UndefinedSymbolError` / `InvalidTypeError` / `NullPointerError` / `OutOfBoundsError` ...）

## 测试

```bash
cd super_execute && py -m pytest        # 759 个测试
cd ..           && py -m pytest        # 仓库全部现役测试（含上游 pycparser 测试）
cd ..           && py super_execute/compat/run_legacy_tests.py
                                       # 归档的旧测试跑在新实现上：52 / 60
```

最后那条是**等价性度量**：`compat/` 里有一层壳，把归档测试需要的
`execute` / `program` / `sources` 换成"跑在新实现上"的版本。它衡量的是新旧差异，
不是新实现的单元覆盖——两者都要看。
