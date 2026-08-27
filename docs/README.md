# Documentation center

本文档中心把“目标设计”和“当前实现”严格分开，避免旧状态页、模块蓝图和实现说明相互覆盖。

## Canonical entry points

| 问题 | 权威入口 |
|---|---|
| 先看哪份文档才不会混淆权威 | [design/DOCUMENTATION_AUTHORITY.md](design/DOCUMENTATION_AUTHORITY.md) |
| 旧设计/旧 superpowers 计划以后怎么保留或清理 | [design/DOCUMENT_CLEANUP_MANIFEST.md](design/DOCUMENT_CLEANUP_MANIFEST.md) |
| 系统最终应该怎样工作 | [design/00_SYSTEM_DESIGN.md](design/00_SYSTEM_DESIGN.md) |
| 契约和阶段不变量是什么 | [design/01_CONTRACTS_AND_INVARIANTS.md](design/01_CONTRACTS_AND_INVARIANTS.md) |
| 检索、语义地点和 GROUND 怎样设计 | [design/02_EVIDENCE_AND_GROUNDING.md](design/02_EVIDENCE_AND_GROUNDING.md) |
| ScenarioSet、审批、执行和验证怎样设计 | [design/03_PLANNING_EXECUTION.md](design/03_PLANNING_EXECUTION.md) |
| 用什么指标判断完成 | [design/04_EVALUATION_AND_ACCEPTANCE.md](design/04_EVALUATION_AND_ACCEPTANCE.md) |
| 当前到目标还差什么 | [design/05_MIGRATION.md](design/05_MIGRATION.md) |
| 当前代码实际上怎样运行 | [architecture/CURRENT_RUNTIME.md](architecture/CURRENT_RUNTIME.md) |
| 当前 API、SSE 和 state owner | [architecture/API_AND_STATE.md](architecture/API_AND_STATE.md) |
| 当前怎样启动、退化和测试 | [architecture/OPERATIONS.md](architecture/OPERATIONS.md) |
| 外部字段级契约 | [contracts/openapi-v1.json](contracts/openapi-v1.json) |
| 稳定术语 | [reference/terminology.md](reference/terminology.md) |

推荐阅读顺序：先看 authority map，再看 `design/00` 至 `design/05`，然后按需进入 `architecture/`、`adr/`、`contracts/` 和 `reference/`。

## Authority rules

1. 文档权威边界与保留规则：`design/DOCUMENTATION_AUTHORITY.md`。
2. 当前实现事实：`backend/app/**`、`frontend/**`、Pydantic、生成契约和可重复测试。
3. 目标行为与不变量：`design/00` 至 `design/04`。
4. 当前到目标的唯一状态/迁移清单：`design/05_MIGRATION.md`。
5. 当前运行映射：`architecture/`，每项 CURRENT 结论必须带代码或命令。
6. 旧设计、旧 superpowers 计划和历史报告的逐项清理台账：`design/DOCUMENT_CLEANUP_MANIFEST.md`。
7. ADR、guides、reference、contracts 和 source docs 只补充决定、操作、字段或原始资料，不重定义主链。
8. `_archive/`、`superpowers/` 和历史报告用于追溯，不具有活动设计权威。

## Directory responsibilities

```text
docs/
├── design/          两份文档治理文件 + 六份规范目标文档和导航
├── architecture/    三份当前实现文档和导航
├── contracts/       生成的 OpenAPI/SSE 契约
├── adr/             架构决策记录
├── guides/          面向任务的操作指南
├── reference/       术语、字段和外部资料索引
├── frontend/        前端接入指南
├── superpowers/     实施计划和过程报告；当前可保留执行中计划，其余应逐步归档
├── reports-weekly/  历史运行证据和周报，不是活动设计
└── _archive/        已退役设计、审计、台账和历史快照
```

活动设计文件必须声明 `Status:` 和 `Authority:`。不得在 `design/` 或 `architecture/` 根目录新增日期状态页、第二套总体蓝图或复制的 API schema。重大新设计写 ADR 或修改已有规范；实现完成度只更新迁移表和当前运行时映射。
