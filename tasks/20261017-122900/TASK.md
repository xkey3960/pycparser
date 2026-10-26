# super_execute · Scope 领域层（entities + value objects + services）

- STATUS: OPEN
- PRIORITY: 100
- TAGS: super_execute, scope, domain

父任务：Task(20261012-144135) 重构execute.py

## 本步范围

只做 `super_execute/super_execute/domain/` 下的 Scope 相关领域层与单元测试。
**不做**：MemoryRegion 实现、application 用例、AST 适配器、frameworks、旧 execute.py 的迁移。

## 已确认的设计裁决

- D1 地址分 region 解释：scope 区 `region:8 + scope_id:8 + offset:16`（每作用域 64 KiB）；
  heap / function 区 `region:8 + offset:24`（16 MiB），scope_id 恒 0。
  `NULL` = `(SCOPE, 0, 0)`；scope_id 0 仅用于 NULL，真实 id 取值 1..255。
- D2 分期：本步只落符号表 + 地址值对象，值仍是 Python 对象；MemoryRegion 留到下一步可插拔替换。
- D3 作用域 id **复用**：退役的 id 归还后优先复用；解引用已销毁作用域的检查随内存实现落地。
- D4 只做 2 个命名空间（普通标识符 / 标签）；goto label 维持块内局部，成员名归 StructType。
- D5 成员名**不进** Scope：`&s.m` = 结构体基地址 + 成员偏移。
- D6 static 收敛为 `ScopeKind.FILE` + `Linkage.INTERNAL`（本步只落 Linkage 值对象）。
- D7 旧 execute.py 并行保留（strangler），待新实现跑通全部用例再切换。

## 实证依据（重构前必须为红）

| # | 程序 | 真实 C | 旧实现 |
|---|---|---|---|
| 1 | 块内 `typedef double T;` 出块后 `sizeof(T)` | 40 | 80 |
| 2 | 两个函数各自定义 `struct P`（4 / 12 字节） | 16 | 8 |
| 3 | 函数内 `struct Inner` 标签泄漏全局 | 8 | 8（但已泄漏） |
| 4 | 块内变量遮蔽 / 出块不可见 | 正确 | 正确 |

结论：变量的作用域是对的，**类型名与函数名完全没有作用域**，故本步以命名空间 + 作用域链重建。

## 验收

- `pytest super_execute/tests` 全绿。
- 仓库既有 264 个测试不回归。
