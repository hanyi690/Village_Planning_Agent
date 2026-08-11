# 架构实现文档

> `docs/design/` 说明为什么这样设计；本文档目录说明目标结构映射到哪里，以及当前代码如何迁移。

## 权威链

```text
backend/app/**                 ← 当前实现事实源
  ↑
docs/design/00_SYSTEM_DESIGN  ← 目标架构 North Star
  ↑
docs/design/01-11              ← 契约、管线、迁移和状态
  ↑
docs/architecture/*.md         ← 实现映射
```

如果当前代码和目标设计不一致，以代码和可重复测试为当前事实源；目标文档必须明确标为目标，不能把计划中的能力写成已实现。

## 文档索引

| 文档 | 内容 |
|---|---|
| [structure.md](structure.md) | 目录、上下文和子图总览 |
| [agent-graph.md](agent-graph.md) | 当前主图与目标分层子图 |
| [modules.md](modules.md) | 模块职责和依赖边界 |
| [backend-api.md](backend-api.md) | API、SSE 和服务适配 |
| [backend-state-contract.md](backend-state-contract.md) | 状态所有权、artifact 与 DELIVER SSOT |
| [frontend-api-v1.md](frontend-api-v1.md) | 稳定 `/api/v1` 前端对接契约 |
| [api-sse-cutover.md](api-sse-cutover.md) | API/SSE 切换、旧端点退役矩阵与验收规则 |
| [../frontend/API_SSE_DEVELOPER_GUIDE.md](../frontend/API_SSE_DEVELOPER_GUIDE.md) | 前端开发者完整接入、恢复、测试与后端演进规范 |
| [frontend.md](frontend.md) | 前端状态、地图和 SSE |
| [rag-system.md](rag-system.md) | RAG 数据摄取与检索实现 |
| [deployment.md](deployment.md) | 部署和运行环境 |

## 快速导航

- [后端模块、状态与同步机制深度审查及理想设计](../audits/backend-ideal-architecture-2026-08-11.md)

- 设计总图：[design/00_SYSTEM_DESIGN.md](../design/00_SYSTEM_DESIGN.md)
- 规划管线：[design/04_PLANNING_PIPELINE.md](../design/04_PLANNING_PIPELINE.md)
- EXPLORE：[design/05_EXPLORE_BRIDGE.md](../design/05_EXPLORE_BRIDGE.md)
- PARSE/GROUND/SELECT：[design/06_PARSE_EXECUTE.md](../design/06_PARSE_EXECUTE.md)
- 迁移计划：[design/09_INTEGRATION_BREAKPOINTS.md](../design/09_INTEGRATION_BREAKPOINTS.md)
