# super_execute · 类型系统 review 修复（A → B → C → D）

- STATUS: CLOSED
- PRIORITY: 100
- TAGS: super_execute, review, fix

父任务：Task(20261029-150452) 类型系统；前置：Task(20261017-122900) Scope 领域层（已 CLOSED）

## 来源

两轮独立评审 + 逐条复现。裁决：**非法 C 结构一律按 C99 报错**，不做静默容错。

## A · fix：C99 语义边界 ✅

- [x] A0 **P0** 布局冻结 vs 类型可变：`ArrayType.count` / `PointerType.target` 改只读，
      `ArrayType.complete(count)` 返回新实例
- [x] A1 union 成员不能是弹性数组（C99 6.7.2.1p1）
- [x] A2 含 FAM 的结构体不能作成员/数组元素
- [x] A3 空结构体/空联合体报错；零长数组报错
- [x] A4 `align_up` 拒绝负数
- [x] A5 `signed unsigned` / 重复说明符返回 None
- [x] A6 移除 `bool` 说明符关键字
- [x] A7 `Address` 拒绝 bool；`from_packed` 定义域写明（`{0} ∪ [0x10000, 0xFFFFFFFF]`）
- [x] A8 标签类型名后多余词报错

## B · refactor：Scope 补强 ✅

- [x] B1 `Scope.declare` 校验变量地址的 `scope_id` 归属
- [x] B2 补 `Scope.redeclare`，与 declare 共用 `_validate_binding`
- [x] B3 `ScopeIdAllocator.open/close`，构造失败退回 id
- [x] B4 符号构造校验 ctype（None 允许，非 CType 拒绝）

## C · test：补齐变异盲点 ✅

- [x] FAM 三条限制 / 空结构体 / 零长数组 / align_up 负数
- [x] `EnumType.constants` 副本、`active()/retired()` 不可变快照
- [x] `BasicType.__eq__` 忽略 size
- [x] `Address` bool 守卫、非 str 守卫、`from_packed` 定义域
- [x] `ScopeKind.PROTOTYPE` 父链
- [x] `tests/unit/domain/conftest.py` 共享夹具

**变异测试复跑：13/13 全部杀死**（上一轮这 13 个里 12 个存活）。

## D · chore：工程门禁 ✅

- [x] `ruff check super_execute` → All checks passed
- [x] `ruff format super_execute` → 19 files reformatted
- [x] 根 `pytest.ini` 接入 `super_execute/tests`
- [x] 解决 `tests` 包重名：删掉测试目录的 `__init__.py` 链，改由
      `super_execute/conftest.py` 引导 `sys.path`（否则报 `No module named 'tests.unit'`）

## 过程记录

| 提交 | 内容 | 测试 |
|---|---|---|
| `5314161` | A · C99 语义边界 + 不可变快照 | 252 passed |
| `212cfd6` | B · Scope 补强 | 253 passed |
| `848ad13` | C · 变异盲点补齐 | 295 passed |
| 本提交 | D · 工程门禁 | 559 passed（264 旧 + 295 新） |

## 已知遗留（本轮不做）

- 包从仓库根不可 import：外层 `super_execute/` 无 `__init__.py`，成了 namespace
  package，`import super_execute.domain` 在仓库根会失败。根治需要
  `super_execute/pyproject.toml` + editable 安装。
- CI（`.github/workflows/ci.yml`）只在 `main` 触发，且 `make test` 是
  `python3 -m unittest discover`，pytest 套件仍未进 CI。
- `ScopeIdAllocator` 复用 id 的悬空风险（D3），兜底依赖 MemoryPort 的
  "已销毁作用域"检查。
- 位域、`const`/`volatile` 限定符、`long double` 仍未支持（既定范围）。
