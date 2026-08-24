# Documentation center

本文档中心把“目标设计”和“当前实现”严格分开，避免旧状态页、模块蓝图和实现说明相互覆盖。

## Canonical entry points

| 问题 | 权威入口 |
|---|---|
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

## Authority rules

1. 当前实现事实：`backend/app/**`、`frontend/**`、Pydantic、生成契约和可重复测试。
2. 目标行为与不变量：`design/00` 至 `design/04`。
3. 当前到目标的唯一状态/迁移清单：`design/05_MIGRATION.md`。
4. 当前运行映射：`architecture/`，每项 CURRENT 结论必须带代码或命令。
5. ADR、guides 和 reference 只补充决定、操作或稳定查表信息，不重定义主链。
6. `_archive/`、`superpowers/` 和历史报告用于追溯，不具有活动设计权威。

## Directory responsibilities

```text
docs/
├── design/          六份规范目标文档和导航
├── architecture/    三份当前实现文档和导航
├── contracts/       生成的 OpenAPI/SSE 契约
├── adr/             架构决策记录
├── guides/          面向任务的操作指南
├── reference/       术语、字段和外部资料索引
├── frontend/        前端接入指南
├── superpowers/     实施计划和过程报告，不是设计权威
└── _archive/        已退役设计、审计、台账和历史快照
```

活动设计文件必须声明 `Status:` 和 `Authority:`。不得在 `design/` 或 `architecture/` 根目录新增日期状态页、第二套总体蓝图或复制的 API schema。重大新设计写 ADR 或修改已有规范；实现完成度只更新迁移表和当前运行时映射。
