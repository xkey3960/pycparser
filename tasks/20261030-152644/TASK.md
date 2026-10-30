# super_execute · 使用者指南与示例

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: docs, examples

父任务：Task(20261012-144135) 重构execute.py
**在分支 `docs/user-guide` 上完成，验收后合并回 `refactor/super-execute`。**

## 交付

| 文件 | 内容 |
|---|---|
| `super_execute/README.md` | 使用者指南 |
| `super_execute/examples/hello.c` | 示例 C：结构体数组、按值传参、循环、`switch`、三目 |
| `super_execute/examples/run_hello.py` | 读文件 → 解析 → 装载 → 运行 → 打印返回值 |
| `super_execute/tests/unit/test_examples.py` | 把"示例跑出 25"钉成测试 |

## 示例为什么这么写

推理器**没有输出语句**（`printf` 属于没做的内建函数），所以约定是
**程序结果 = `main` 的返回值**，由 Python 侧打印。这句话在 README 和示例里都写了。

三个坑是在写示例时撞出来的，都写进了文档：

1. **`CParser` 不接受注释**，注释要靠 `gcc -E` 剥。所以 `hello.c` 刻意不带注释、
   不带 `#include`，好让示例零依赖直接跑；真实项目的做法（`parse_file(use_cpp=True,
   cpp_args=["-E", ...])`）单独给了一段。
2. **`parse_file` 不会自己加 `-E`**（本仓库 pycparser 的行为），必须显式传，
   否则 gcc 会去编译链接。
3. `GnuCParser` 是**可选依赖**：装了才有 `typeof` / 语句表达式 / `case 1 ... 5`。

## 文档里的事实都验过

写文档时不敢凭印象，逐条核对：

| 说法 | 怎么验的 |
|---|---|
| 基础类型尺寸 | 读 `builtin_types.py`：`long` 是 4、`long long` 是 8、指针 4 |
| 指针 4 字节 | `POINTER_SIZE = ADDRESS_SIZE` |
| `goto` 能跳出 `switch` | 跑了一遍，返回 1 ✓ |
| `goto` 不能跳进 `switch` | 跑了一遍，`UndefinedLabelError` ✓ |
| 可变参数能声明能调用、但拿不到多余实参 | `f(7,8,9)` 返回 7 ✓ |
| 测试数 759 | 跑 junit 数的 |

初稿里我把基础类型写成"LLP64"——不准确：`long` 是 4（LLP64 的特征），但指针也是 4，
整体是 ILP32 的形状。改成直接列尺寸表，不贴 ABI 标签。

## 验证

- `py examples/run_hello.py` → `hello.c 的 main() 返回 25`（从仓库根、项目根、
  examples 目录三种 CWD 都能跑）
- 仓库根 `pytest` → **904 passed / 6 skipped**（+2 是新增的示例测试）
- 旧套件（兼容层）→ 52 / 60
- `ruff check super_execute` / `ruff format --check` 全绿

## 验收

- README 里的每个代码片段都能跑（`CParser` 路径已实测；cpp 路径也实测过 `main() = 6`）
- 示例有测试兜底，改坏会先红
