# Documentation center

本目录严格区分目标设计、当前实现、迁移账本和历史证据。

## Canonical entry points

| 问题 | 权威入口 |
|---|---|
| 文档冲突听谁的 | [design/DOCUMENTATION_AUTHORITY.md](design/DOCUMENTATION_AUTHORITY.md) |
| 系统总体目标 | [design/00_SYSTEM_DESIGN.md](design/00_SYSTEM_DESIGN.md) |
| 可执行模块设计标准 | [design/EXECUTABLE_DESIGN_STANDARD.md](design/EXECUTABLE_DESIGN_STANDARD.md) |
| DATA | [design/DATA_EXECUTABLE_DESIGN.md](design/DATA_EXECUTABLE_DESIGN.md) |
| 初期认知闭环 | [design/README.md](design/README.md) |
| Cognition / World Model | [design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md](design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md) |
| Evidence | [design/04_EVIDENCE.md](design/04_EVIDENCE.md) |
| L1 | [design/01_CONTRACTS_AND_INVARIANTS.md](design/01_CONTRACTS_AND_INVARIANTS.md) |
| Target Projection | [design/05_PROJECTION_AND_GROUND.md](design/05_PROJECTION_AND_GROUND.md) |
| L1-GROUND | [design/L1_GROUND_EXECUTABLE_DESIGN.md](design/L1_GROUND_EXECUTABLE_DESIGN.md) |
| Planning Ground | [design/PLANNING_GROUND_EXECUTABLE_DESIGN.md](design/PLANNING_GROUND_EXECUTABLE_DESIGN.md) |
| P0/P1/P2 验收 | [design/acceptance/README.md](design/acceptance/README.md) |
| 跨模块 Gate 和增量协议 | [design/10_MODULE_LEVEL_EXECUTABLE_DESIGN.md](design/10_MODULE_LEVEL_EXECUTABLE_DESIGN.md) |
| 当前到目标还差什么 | [design/05_MIGRATION.md](design/05_MIGRATION.md) |
| 当前代码怎样运行 | [architecture/CURRENT_RUNTIME.md](architecture/CURRENT_RUNTIME.md) |
| API、SSE、state | [architecture/API_AND_STATE.md](architecture/API_AND_STATE.md) |
| 启动与诊断 | [architecture/OPERATIONS.md](architecture/OPERATIONS.md) |
| 外部字段契约 | [contracts/openapi-v1.json](contracts/openapi-v1.json) |

## Authority rules

1. 当前事实来自代码、可重载 artifact 和实际运行；
2. 字段来自 Pydantic/OpenAPI；
3. 目标来自对应 design owner；
4. current-to-target 状态只在 <code>design/05_MIGRATION.md</code>；
5. audit、plan、weekly report、参考报告和历史会话不覆盖上述 owner；
6. TARGET 不能写成 IMPLEMENTED，IMPLEMENTED 不能自动写成 RUNTIME_VERIFIED/CURRENT。

## Directory responsibilities

~~~text
docs/
├── design/          目标设计、跨模块规范和迁移账本
├── architecture/    当前运行实现
├── contracts/       生成的外部契约
├── adr/             架构决定
├── audits/          一次性审计证据
├── guides/          操作指南
├── reference/       稳定参考
├── frontend/        前端接入
└── 其他资料         领域输入/参考，不是系统设计
~~~

<code>docs/superpowers/</code>、<code>docs/reports-weekly/</code> 和临时分析文件若存在，只是
HISTORICAL/WORKING MATERIAL。它们不在 active design 导航中，也不能作为 workflow 输入或
完成度证据。

活动设计的详细导航和阅读顺序见 [design/README.md](design/README.md)。
