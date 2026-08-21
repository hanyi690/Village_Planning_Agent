# 文档中心

本目录只保留三类维护入口：总体设计（`design/00_SYSTEM_DESIGN.md`）、当前实现映射
（`architecture/` + 各模块 README）和可复核状态/审计证据。如果同一事实在多个文件出现，优先级如下：

1. `backend/app/**`、`frontend/**` 和可重复的测试/运行结果；
2. `design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md`、
   `design/27_IMPLEMENTATION_VS_DESIGN.md` 和 `design/RELATION_AWARE_MODIFICATION_LEDGER.md`；
3. 最新专题审计和可重复运行证据；
4. `architecture/` 的实现映射；
5. `design/` 的目标设计；
6. `_archive/` 中的历史审计、计划与周报（只用于解释“为什么会这样”，不能把旧路径或计划中
   的能力变成当前事实）。

## 先按问题找文档

| 你想知道什么 | 入口 | 文档类型 |
|---|---|---|
| 系统的目标、边界、不变量和完成门槛 | [design/00_SYSTEM_DESIGN.md](design/00_SYSTEM_DESIGN.md) | 总体设计 |
| 某项能力现在到底完成没有 | [design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md](design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md) | 状态 / CURRENT |
| 设计文档与实现哪里不一致 | [design/27_IMPLEMENTATION_VS_DESIGN.md](design/27_IMPLEMENTATION_VS_DESIGN.md) | 差异 / CURRENT |
| 关系感知空间规划推进到哪一步 | [design/RELATION_AWARE_MODIFICATION_LEDGER.md](design/RELATION_AWARE_MODIFICATION_LEDGER.md) | 台账 / CURRENT |
| 按模块组织的专题设计 | [design/README.md](design/README.md) → `design/modules/<模块>/` | 设计 / TARGET |
| 当前代码从哪里启动、怎样流转 | [architecture/structure.md](architecture/structure.md) 与 [architecture/agent-graph.md](architecture/agent-graph.md) | 实现 / Explanation |
| 后端每个模块的详细说明 | [backend/app/README.md](../backend/app/README.md) → 各模块 `README.md`（[索引](architecture/README.md)） | 实现 / 模块级 |
| 当前 API、SSE、恢复和交付接口 | [architecture/backend-api.md](architecture/backend-api.md) | 实现 / Reference |
| 状态、artifact 和交付由谁拥有 | [architecture/backend-state-contract.md](architecture/backend-state-contract.md) | 实现 / Reference |
| 前端接入、断线同步和恢复 | [frontend/API_SSE_DEVELOPER_GUIDE.md](frontend/API_SSE_DEVELOPER_GUIDE.md) | 指南 / How-to |
| 前端每个 feature 的详细说明 | [frontend/src/features/README.md](../frontend/src/features/README.md) | 实现 / 模块级 |
| RAG、KG、地点解析等专题 | [architecture/rag-system.md](architecture/rag-system.md)、[design/12_PLACE_NAME_RESOLUTION.md](design/modules/kg-place/12_PLACE_NAME_RESOLUTION.md) | 专题 |
| 历史审计、真实运行或迁移决定 | [_archive/](_archive/) | 历史证据 |

## 目录职责

```text
docs/
├── design/          唯一总体设计（00）+ 当前状态/差异/实施台账 + 按模块组织的 `modules/<模块>/` 专题设计
├── architecture/    当前实现映射；只写真实入口、调用链、状态和验证方式
├── guides/          面向任务的操作步骤（接入图层、查看 KG 等）
├── reference/       术语、字段、外部规范和稳定查表信息
├── data/            数据源和采集说明
├── frontend/        前端接入手册
├── contracts/       openapi-v1.json、sse-events-v1.schema.json（真实 API 契约）
├── adr/             架构决策记录
├── _archive/        已退役文档（审计、提案、计划、周报、PPT、迭代日志）
└── （参考资料）RAG 知识库/、参考报告/、references/、*.pdf/*.mpk/*.docx/*.zip 为领域原始资料，不是维护性文档
```

## 状态标记

- `CURRENT`：当前生产路径存在，并有代码或可重复测试证据。
- `PARTIAL`：有可运行片段，但闭环、边界、真实数据或验收仍不完整。
- `GAP`：设计要求存在，但当前生产路径没有实现，或已知接线断裂。
- `TARGET`：目标设计；不能用于证明功能已完成。
- `HISTORICAL`：带日期的历史事实，只用于解释当时的状态。

“文件存在”“单元测试通过”“能生成空集合或复制现状图”都不足以单独标记 `CURRENT`。
涉及地图、规划结果或恢复的能力，还必须检查实际产物、来源引用、版本一致性和失败路径。

## 当前实现的最短阅读路径

```text
backend/app/main.py
  → bootstrap/lifespan.py + bootstrap/composition.py
  → api/routes.py → api/v1/routes/*
  → application/commands + application/queries
  → infrastructure/runtime/planning_runtime_service.py
  → workflow/root_graph.py（四段子图）
  → workflow/stages/* + domain/* + contracts/*
  → infrastructure/artifacts + infrastructure/events + data/spatial
  → application projections → API/SSE/Delivery
```

LangGraph 的 `WorkflowState` 只承担控制字段和 artifact 引用；阶段业务结果由类型化契约和
artifact store 持有。目标设计中仍然保留 L1/L2/L3 认知视图，但不能把它们与当前代码的
目录名、阶段完成度或交付完整度混为一谈。

## 维护规则

新增文档前先回答“读者要做什么或查什么”。解释、参考、指南和教程不要混写在同一篇里。
模块级细节写进对应模块的 `README.md`，`docs/architecture/` 只做索引和跨模块说明，不复制
模块 README 的内容。当前实现文档应优先描述 OpenAPI/Pydantic 可观察契约、真实入口和验证
命令；设计文档只描述目标边界、决策和不变量。

每次架构迁移至少同步三处：

- 当前代码入口和 `architecture/` 映射；
- `design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md` 的状态与证据；
- 本页或专题索引中的链接；差异登记到 `design/27_IMPLEMENTATION_VS_DESIGN.md`。

不要在根 README、总体设计、审计报告和模块 README 中复制另一套目录树或迁移清单。
