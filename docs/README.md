# 文档中心

本目录只解决两件事：说明系统应该怎样设计，以及说明当前代码实际上怎样运行。
如果同一事实在多个文件出现，优先级按下面顺序处理：

1. `backend/app/**`、`frontend/**` 和可重复的测试/运行结果；
2. `design/10_IMPLEMENTATION_STATUS.md` 的状态台账；
3. `architecture/` 的实现映射；
4. `design/` 的目标设计；
5. `audits/`、`superpowers/plans/` 和周报中的历史记录。

历史审计和计划可以解释“为什么会这样”，但不能把旧路径或计划中的能力变成当前事实。

## 先按问题找文档

| 你想知道什么 | 入口 | 文档类型 |
|---|---|---|
| 系统的目标、边界和不变量 | [design/00_SYSTEM_DESIGN.md](design/00_SYSTEM_DESIGN.md) | 设计 / Explanation |
| 后端目标模块如何划分 | [design/14_BACKEND_MODULE_BLUEPRINT.md](design/14_BACKEND_MODULE_BLUEPRINT.md) | 设计 / Explanation |
| 某项能力现在到底完成没有 | [design/10_IMPLEMENTATION_STATUS.md](design/10_IMPLEMENTATION_STATUS.md) | 状态 / Reference |
| 当前代码从哪里启动、怎样流转 | [architecture/structure.md](architecture/structure.md) 与 [architecture/agent-graph.md](architecture/agent-graph.md) | 实现 / Explanation |
| 当前 API、SSE、恢复和交付接口 | [architecture/backend-api.md](architecture/backend-api.md) | 实现 / Reference |
| 状态、artifact 和交付由谁拥有 | [architecture/backend-state-contract.md](architecture/backend-state-contract.md) | 实现 / Reference |
| LLM 工具绑定现在到哪一步 | [design/17_LLM_TOOL_BINDING.md](design/17_LLM_TOOL_BINDING.md) | 设计 + 当前事实 |
| 前端接入、断线同步和恢复 | [frontend/API_SSE_DEVELOPER_GUIDE.md](frontend/API_SSE_DEVELOPER_GUIDE.md) | 指南 / How-to |
| RAG、KG、地点解析等专题 | [architecture/rag-system.md](architecture/rag-system.md)、[design/12_PLACE_NAME_RESOLUTION.md](design/12_PLACE_NAME_RESOLUTION.md) | 专题 |
| 某次审计、真实运行或迁移决定 | [audits/](audits/) | 历史证据 |

## 目录职责

```text
docs/
├── design/          目标设计、领域边界和未来约束；未实现内容必须标 TARGET/GAP
├── architecture/    当前实现映射；只写真实入口、调用链、状态和验证方式
├── guides/           面向任务的操作步骤，例如接入图层或查看 KG
├── reference/        术语、字段、外部规范和稳定查表信息
├── data/             数据源和采集说明；与实现变更同步检查
├── audits/           带日期的审计、真实运行、差距和迁移证据
├── proposals/        提案；除非已明确迁移，否则不代表当前能力
├── superpowers/      一次性执行计划；不作为架构事实源
├── reports/          周报、专利和汇报材料
├── references/       外部规划资料和样例数据，不是本项目实现文档
└── _archive/         已退役文档
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
  → workflow/root_graph.py
  → workflow/stages/* + domain/* + contracts/*
  → infrastructure/artifacts + infrastructure/events + data/spatial
  → application projections → API/SSE/Delivery
```

LangGraph 的 `WorkflowState` 只承担控制字段和 artifact 引用；阶段业务结果由类型化契约和
artifact store 持有。目标设计中仍然保留 L1/L2/L3 认知视图，但不能把它们与当前代码的
目录名、阶段完成度或交付完整度混为一谈。

## 维护规则

新增文档前先回答“读者要做什么或查什么”。解释、参考、指南和教程不要混写在同一篇里；
这是 Diátaxis 对文档内容和导航的基本分离原则。当前实现文档应优先描述 OpenAPI/Pydantic
可观察契约、真实入口和验证命令；设计文档只描述目标边界、决策和不变量。

每次架构迁移至少同步三处：

- 当前代码入口和 `architecture/` 映射；
- `design/10_IMPLEMENTATION_STATUS.md` 的状态与证据；
- 本页或专题索引中的链接。

不要在根 README、设计蓝图、审计报告和模块 README 中复制另一套目录树或迁移清单。
