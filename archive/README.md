# archive —— 已下线的旧实现与旧文档

这个目录里的东西**不再是现役代码**，只为追溯与对照保留。

```
archive/
├── legacy-implementation/   旧解释器实现（已下线）
│   ├── execute.py           2958 行：解释执行、作用域、函数调用、错误回溯
│   ├── typesys.py            967 行：扁平类型表、结构体/联合体/枚举
│   ├── program.py            416 行：CProgram（多文件装载、惰性激活、AST 缓存）
│   ├── sources.py            334 行：文件索引与激活状态
│   └── cbuiltins.py          580 行：printf 等内建函数
├── legacy-tests/            旧实现配套的测试（7 个文件）
└── docs/                    旧实现的设计文档（18 篇）
```

## 为什么下线

新实现在 `super_execute/` 里，按 clean architecture 分层重写：

```
domain ← application ← interface_adapters ← frameworks
```

新旧两套并存期间，仓库里有两份解释器、两套类型系统、两套测试——读代码的人
必须先判断"这个函数属于哪一套"。下线的目的是让仓库里**只有一套现役实现**。

## 旧测试没有丢，只是搬了家

`archive/legacy-tests/` 里的测试仍然可以跑，而且跑的是**新实现**：

```bash
py super_execute/compat/run_legacy_tests.py
py super_execute/compat/run_legacy_tests.py archive/legacy-tests/test_program.py
```

做法是 `super_execute/compat/` 那一层兼容壳：用 importlib 把它们需要的
`execute` / `program` / `sources` 换成"跑在新实现上"的版本，再在同一个进程里
跑 pytest。所以这些测试现在衡量的是**新旧等价性**。

最后一次实测：**52 / 60 通过**。剩下 8 个失败都有明确归因，见
`super_execute/tasks/` 下各轮任务记录（惰性激活时机、strict 可达性、
英文消息文案、旧单节点 `execute()` API、setjmp）。

## 想直接运行归档的旧实现？

把它加进 `PYTHONPATH` 即可（它内部靠 `import typesys` / `import sources` 互相引用，
必须在同一个目录里一起导入）：

```bash
set PYTHONPATH=archive/legacy-implementation
```

但请注意：**这是死代码**，不再维护，也不再参与任何测试或构建。

## 文档

`archive/docs/` 里的设计文档描述的是旧实现。它们仍然有参考价值——
很多结论（地址模型、指针语义、C 的类型规则）在新实现里**同样成立**，
而且当初拍板时的取舍理由都写在里面。但看的时候要记住：

* 里面提到的模块名、函数名、`g_scope` / `g_types` 之类的全局，都是旧实现的形状；
* "已实现"的功能清单以 `super_execute/` 下的代码和测试为准。

新实现的记录在 `super_execute/tasks/` 与 `tasks/` 下。
