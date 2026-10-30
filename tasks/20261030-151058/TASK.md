# 下线旧 execute.py + 归档旧文档

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: retirement, archive, migration

父任务：Task(20261012-144135) 重构execute.py
**在分支 `chore/retire-legacy-execute` 上完成，验收后合并回 `refactor/super-execute`。**

## 动了什么

```
archive/
├── legacy-implementation/   execute.py(2958行) typesys.py(967) program.py(416)
│                            sources.py(334) cbuiltins.py(580)
├── legacy-tests/            test_program / test_typesys / test_builtins /
│                            test_qol2 / test_qol4 / test_exe / test_print_pointer
├── docs/                    18 篇设计文档 + 学习总结.md + 测试说明.md
└── README.md                为什么下线、旧测试怎么还能跑、文档怎么看
```

`lockcheck.py` 与 `test_lockcheck.py` **没有归档**：它是独立的持锁调用静态分析工具，
和被替换的解释器毫无关系。

## 配套改动

| 文件 | 改了什么 |
|---|---|
| `pytest.ini` | testpaths 只剩现役测试；`norecursedirs = archive` |
| `conftest.py` | 删掉旧状态重置（`execute.setup_global_scope` / `g_types.clear`），只剩说明 |
| `pyproject.toml` | ruff 与 ty 都 `exclude = ["archive"]` |
| `super_execute/compat/run_legacy_tests.py` | 目标路径改到 `archive/legacy-tests/` |

最后一条是关键：**归档的旧测试仍然能跑，而且跑的是新实现**。

```bash
py super_execute/compat/run_legacy_tests.py     # 52 / 60
```

## 验证

- `import execute` → `ModuleNotFoundError`（旧实现真的不在导入路径上了）
- 仓库根 `pytest` → **902 passed / 0 failed / 6 skipped**（原 1023，差额是归档的旧测试）
- 旧套件（兼容层）→ **52 / 60**
- `super_execute` 自身 → 759 passed
- `ruff check super_execute` 绿

## 一个诚实的观察：`make check` 本来就是红的

对比前后（用 git stash 量的）：

| | ruff check . | ruff format 待整理 |
|---|---|---|
| 归档前 | 57 errors | 20 个文件 |
| 归档后 | **4 errors** | **8 个文件** |

也就是说归档**顺带清掉了旧实现的一大块 lint 债**。剩下的 4 个都在我没碰的文件里
（`lockcheck.py` 的未用 import、`test_ext.py` 的 E402 与 `_DeclSpec` 未定义名、
上游 `pycparser/` 与 `pycparserext/` 的格式）。它们在本轮之前就存在，不属于
"下线旧实现"的范围，所以没动。

## 仍然存在的东西

`archive/` 里的旧代码是**死代码**：不再维护、不参与构建、不参与任何测试。
想直接跑它需要显式 `PYTHONPATH=archive/legacy-implementation`，`archive/README.md`
写了这一点，也写明了"看旧文档时哪些结论在新实现里仍然成立"。

## 验收

- `pytest`（仓库根）→ 902 passed / 6 skipped
- `py super_execute/compat/run_legacy_tests.py` → 52/60
- `ruff check super_execute` / `ruff format --check super_execute` 全绿
