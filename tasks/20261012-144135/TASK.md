# 重构execute.py

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: refactor, clean-architecture, strangler

## 结论

新实现在 `super_execute/`，按 clean architecture 分层：

```
domain ← application ← interface_adapters ← frameworks
（依赖只向内）
```

旧实现（`execute.py` / `typesys.py` / `program.py` / `sources.py` / `cbuiltins.py`）
已**下线并归档**到 `archive/legacy-implementation/`，连同它的 7 个测试文件与 18 篇
设计文档。

## 过程：分 12 轮增量推进

每一轮都是「tatr 任务 → 实现 → 测试 → ruff → 提交」，并且**每轮都跑同一个度量**：
用兼容层把归档的旧测试跑在新实现上，看通过数怎么变。

| 轮 | 内容 | 旧套件 |
|---|---|---|
| 1 | 兼容层 + 等价性度量（先发现"假通过"） | 17/61 |
| 2 | 常量折叠、全局初值调函数；修 struct 赋值别名 | 20/61 |
| 3 | TYPE-2 隐式转换、QOL-1 错误定位与调用链 | 22/61 |
| 4 | 按文件划分作用域（D6：static 隔离） | 23/61 |
| 5 | 函数指针调用、goto、除零分类 | 26/61 |
| 6 | 惰性装载语义（只注册不布局） | 31/61 |
| 7 | 冲突诊断 strict/warn | 37/61 |
| 8 | GNU 第一批：零长数组/初始化列表/指定初始化/语句表达式 | 43/61 |
| 9 | GnuCParser 切换 + typeof + offsetof | 46/61 |
| 10 | A 类 4 个（兼容层 get 返回值、main 返回 0、消息措辞） | 50/61 |
| 11 | `_Static_assert`、字符串字面量与堆区、`switch` + case 范围、位域 | 53/61 |
| 12 | 下线旧实现、归档旧测试与文档 | 52/60 |

（最后一轮 61→60 是因为 `test_ext.py` 只依赖 pycparser 本体，留在现役测试里了。）

## 三个值得记住的判断

1. **第一版兼容层测出了假通过**：用 `PYTHONPATH` 影子替换时 61/61 全过，因为
   pytest 会把自己算出的 rootdir 插到 `sys.path` 最前面。改成 `sys.modules` 注入
   并断言 `__file__` 之后，数字掉到 1——那才是真实起点。**度量工具本身也要被验证。**

2. **优先级被数据证伪过**：我先按"影响面"排了常量折叠和全局初值，做完只涨 1；
   而顺手发现的 struct 赋值别名（最早那次 review 的 P0）一次拿下 2 个，其中包括
   最重的端到端用例。

3. **明确不追的东西**：旧实现的英文消息文案（`Undefined variable: 'zz'`）不做兼容。
   新实现用中文是有意的选择；让兼容层伪造英文，通过率会涨，但证明的是"翻译对了"
   而不是"行为等价"。

## 剩余差异（8 个，都有归因）

| 类 | 用例 | 性质 |
|---|---|---|
| B | `ctrl2_setjmp_longjmp` | setjmp/longjmp 跨帧 unwind，新功能 |
| C | 惰性激活时机 ×2、tag 未使用不补全 ×1 | 旧实现按文件激活，新实现装载即声明（L4 语义） |
| C | `plan_c_reachable_prelink` | strict 可达性预链接，独立特性 |
| D | `qol1_error_traceback`、`err_undefined_variable` | 英文文案，有意不兼容 |
| E | `proto_decl_and_link_error` | 旧单节点 `execute()` API + 旧类型系统 |

详细的逐条解释见 `tasks/` 下各轮记录与 `archive/README.md`。

## 原始设想（保留）

> 用 python 的 dict 做 scope 不够：C 的地址操作太灵活，必须模拟内存。
> 指针真的只是一个地址。

地址模型最终落地为 **4 字节 packed**：`region(8) | scope_id 或高位偏移(8) | offset(16)`，
scope 区每作用域 64 KiB，heap / function 区各 16 MiB。这条设计贯穿始终，没改过。
