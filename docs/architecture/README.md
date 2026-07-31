# 架构文档（Architecture）

> 本目录回答"代码在哪里、怎么跑"（where / how）。
> 设计理由（why）见 [`docs/design/`](../design/)。

## 权威链（Authority Chain）

```
代码 (backend/app/**, frontend/**)          ← 最终事实源
  ↑
design/00_SYSTEM_DESIGN.md                  ← North Star（为什么这么设计）
  ↑
design/01-10_*.md                           ← 设计问题展开
  ↑
architecture/*.md                           ← 技术实现映射（本文档目录）
  ↑
README.md（根）                             ← 对外门面（只链接不重复）
```

- `design/` 回答"为什么"
- `architecture/` 回答"在哪里、怎么跑"
- `audits/` 和 `proposals/` 为诊断参考和未落地提案，**不参与**权威链

## 架构文档索引

| 文档 | 核心内容 |
|------|----------|
| [agent-graph.md](./agent-graph.md) | 5 节点主图（`graph.py` + `routing.py` + `state.py`），节点表、ASCII 图、路由逻辑 |
| [backend-api.md](./backend-api.md) | `/api/sessions/*` 7 端点 + SSE 单通道 + 服务层 + 天地图瓦片代理 |
| [frontend.md](./frontend.md) | Next.js 14 + Zustand 5 + MapLibre GL，目录结构、SSE 连接管理 |
| [modules.md](./modules.md) | 五层模块实现映射（schema / data / spatial_ops / kg / rag） |
| [deployment.md](./deployment.md) | 部署配置（Docker Compose、`.env`、LLM 切换） |
| [rag-system.md](./rag-system.md) | RAG 知识检索（Small-to-Big + 层级感知 + ChromaDB） |

## 快速导航

| 想了解... | 请阅读 |
|----------|--------|
| 主图怎么跑 | [agent-graph.md](./agent-graph.md) |
| API 端点有哪些 | [backend-api.md](./backend-api.md) |
| 前端状态怎么管 | [frontend.md](./frontend.md) |
| 五层模块如何分层 | [modules.md](./modules.md) |
| 怎么部署 | [deployment.md](./deployment.md) |
| RAG 怎么检索 | [rag-system.md](./rag-system.md) |

## 相关资源

- [设计文档](../design/) — North Star 与设计展开
- [术语表](../reference/terminology.md) — 术语定义
- [审计诊断](../audits/) — 架构审计
- [重构提案](../proposals/) — 未落地提案
