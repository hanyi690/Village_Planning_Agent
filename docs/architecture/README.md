# 当前架构实现

本目录只描述已经存在于 `backend/app/` 或 `frontend/` 的实现：入口、调用链、状态边界、
接口和验证方式。目标架构、未实现能力和未来迁移顺序见
[`../design/00_SYSTEM_DESIGN.md`](../design/00_SYSTEM_DESIGN.md)；
完成度见 [`../design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md`](../design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md)；
设计与实现的差异见 [`../design/27_IMPLEMENTATION_VS_DESIGN.md`](../design/27_IMPLEMENTATION_VS_DESIGN.md)。

## 当前实现入口

```text
backend/app/main.py
  → bootstrap/lifespan.py
  → api/routes.py → api/v1/routes/*
  → application/commands|queries|projections
  → infrastructure/runtime/planning_runtime_service.py
  → workflow/root_graph.py（四段子图：intent_loop / cognitive / spatial_chain / hitl）
```

## 文档索引

| 文档 | 只回答一个问题 |
|---|---|
| [structure.md](structure.md) | 当前目录、入口和依赖边界是什么？ |
| [agent-graph.md](agent-graph.md) | 根图四段子图有哪些节点、阶段和恢复路径？ |
| [backend-api.md](backend-api.md) | 当前 HTTP、SSE、resume 和 delivery 接口是什么？ |
| [backend-state-contract.md](backend-state-contract.md) | state、artifact、事件和交付的 owner 是谁？ |
| [rag-system.md](rag-system.md) | 当前 RAG 摄取和检索如何运行？ |
| [deployment.md](deployment.md) | 当前本地和容器启动方式是什么？ |
| [../frontend/API_SSE_DEVELOPER_GUIDE.md](../frontend/API_SSE_DEVELOPER_GUIDE.md) | 前端接入、同步和恢复如何实现？ |

## 模块级 README（代码内）

每个后端/前端模块有自己的详细 README（以实际代码为准），架构文档只做索引，不复制内容：

```text
backend/app/README.md                 应用根包总览（13 个模块一览）
backend/app/{api,application,bootstrap,config,contracts,core,data,database,
            domain,evidence,infrastructure,spatial,workflow}/README.md    各模块详细说明
frontend/src/features/README.md       feature 索引
frontend/src/features/{planning,compliance,evaluation,suitability}/README.md
frontend/src/{app,types,styles}/README.md
```

## 事实规则

- `backend/app/**` 和可重复测试是实现事实源；本目录不能覆盖代码行为。
- 每一条“当前”描述应带代码路径、契约名称或验证命令。
- 目标行为必须链接到 `design/`，并显式标为 `TARGET`、`GAP` 或 `PARTIAL`。
- `docs/_archive/` 中带日期的内容是证据或历史快照，不作为当前入口。
- 已删除的 `app/agent`、`app/modules`、`app/services` 路径只允许出现在迁移历史中，
  不能出现在当前目录树或当前调用链里。

## 变更后检查

```powershell
rg -n --glob '*.md' 'app/agent|app/modules|app/services|backend/app/modules' docs backend/app README.md
rg -n --glob '*.md' '\[.*\]\([^)]*\)' docs/architecture docs/design
pytest backend/tests/contracts backend/tests/core -q
```
