# super_execute · 类型系统 review 修复（A → B → C → D）

- STATUS: OPEN
- PRIORITY: 100
- TAGS: super_execute, review, fix

父任务：Task(20261029-150452) 类型系统；前置：Task(20261017-122900) Scope 领域层（已 CLOSED）

## 来源

两轮独立评审 + 逐条复现，结论见 4 个批次。裁决：**非法 C 结构一律按 C99 报错**，
不做静默容错（union 内弹性数组、FAM 结构体作成员、空结构体、零长数组）。

## A · fix：C99 语义边界（纯加校验）

- [ ] A0 **P0** 布局冻结 vs 类型可变：`ArrayType.count` / `PointerType.target`
      改为只读 + `ArrayType.complete(count)` 返回新实例。否则
      `define()` 后再改 `count`，`arr.sizeof()==40` 而 `s.sizeof()==4` 静默算错。
- [ ] A1 union 成员不能是弹性数组（C99 6.7.2.1p1）
- [ ] A2 含 FAM 的结构体不能作成员/数组元素（否则静默欠分配）
- [ ] A3 空结构体/空联合体报错（C99 要求至少一个具名成员）；零长数组报错
- [ ] A4 `align_up` 拒绝负数
- [ ] A5 说明符非法组合：`signed unsigned` / 重复 `unsigned|short|signed`
- [ ] A6 移除 `bool` 说明符关键字（C 里它来自 `<stdbool.h>` 的宏，不是关键字）
- [ ] A7 `Address` 拒绝 bool 作 region/delta；`from_packed` 保留区写明并测试

## B · refactor：Scope 补强

- [ ] B1 `Scope.declare` 校验变量地址的 `scope_id` 必须等于本作用域
- [ ] B2 补 `Scope.redeclare`（原型/extern/tentative），保留链接属性校验
- [ ] B3 `ScopeIdAllocator.open(kind, parent)` / `close(scope)`，让"建作用域"
      走受控入口，降低 id 重复
- [ ] B4 符号构造校验 ctype：允许 None（未解析），非 None 必须是 CType

## C · test：补齐变异测试暴露的盲点

- [ ] FAM 必须在最后 / union FAM / 空结构体 / 零长数组
- [ ] `EnumType.constants` 防御副本、`active()` 不可变视图
- [ ] `BasicType.__eq__` 忽略 size（判等语义钉住）
- [ ] `Address` 的 bool 守卫、`__contains__` 非 str 守卫
- [ ] `ScopeKind.PROTOTYPE` 父链校验
- [ ] 新增 `tests/unit/domain/conftest.py`，去掉 4 处重复的 `_var`/`file_scope`

## D · chore：工程门禁

- [ ] `ruff check` 清零（含 `super_execute.py` 草稿的 F401）
- [ ] `ruff format super_execute`（会重排行号，因此放最后）
- [ ] 根 `pytest.ini` 的 `testpaths` 接入 `super_execute/tests`，恢复"一条命令跑完"

## 已知遗留（本轮不做，记录在案）

- 包从仓库根不可 import：外层 `super_execute/` 无 `__init__.py`，成了 namespace
  package。需要 `super_execute/pyproject.toml` + editable 安装才能根治。
- CI（`.github/workflows/ci.yml`）只在 `main` 触发，且 `make test` 是
  `python3 -m unittest discover`，pytest 套件从未进过 CI。
- `ScopeIdAllocator` 复用 id 的悬空风险（D3），兜底依赖 MemoryPort 的
  "已销毁作用域"检查。
