# 村庄规划智能体

基于 FastAPI、LangGraph、Pydantic 和 Next.js 的村庄规划系统。系统把规划认知、证据探索、
空间决策和成果交付串成可恢复的工作流；当前代码已经完成主要后端目录收敛，但“有节点/有
测试”不等于完成真实、法定、无 HUMAN 阻塞的规划闭环。

## 当前运行链

```text
上传资料 / SessionDataSnapshot / SpatialWorkspace
  → L1/L2/L3 认知层
  → TARGET_PROJECTION → GROUND → SELECT → EXECUTE
  → VALIDATE → RECONCILE → DELIVER
  → DeliverySpatialSnapshot → API / SSE / 地图 / 导出
```

根图入口是 `backend/app/workflow/root_graph.py`，FastAPI 入口是
`backend/app/main.py`。当前实现、目标设计和未实现清单分开维护：

- 当前代码入口和调用链：[docs/architecture/structure.md](docs/architecture/structure.md)
- 当前主图（四段子图）：[docs/architecture/agent-graph.md](docs/architecture/agent-graph.md)
- API/SSE/resume：[docs/architecture/backend-api.md](docs/architecture/backend-api.md)
- 状态、artifact、交付边界：[docs/architecture/backend-state-contract.md](docs/architecture/backend-state-contract.md)
- 目标设计：[docs/design/00_SYSTEM_DESIGN.md](docs/design/00_SYSTEM_DESIGN.md)
- 后端蓝图：[docs/design/14_BACKEND_MODULE_BLUEPRINT.md](docs/design/14_BACKEND_MODULE_BLUEPRINT.md)
- 实现状态：[docs/design/10_IMPLEMENTATION_STATUS.md](docs/design/10_IMPLEMENTATION_STATUS.md)
- 模块级盘点（以代码为准）：[docs/design/24_MODULE_OUTPUT_INVENTORY.md](docs/design/24_MODULE_OUTPUT_INVENTORY.md)、[docs/design/25_VALIDATION_INVENTORY.md](docs/design/25_VALIDATION_INVENTORY.md)
- 设计 vs 实现差异：[docs/design/27_IMPLEMENTATION_VS_DESIGN.md](docs/design/27_IMPLEMENTATION_VS_DESIGN.md)
- 完整文档导航：[docs/README.md](docs/README.md)

## 快速开始

### 环境

- Python 3.11+
- Node.js 18+（推荐 20+）
- 至少一个兼容 provider 的 LLM key；没有 key 时真实 LLM 验收应 skip，而不是写成通过

### 安装

```powershell
pip install -r requirements.txt
Set-Location frontend
npm install
Set-Location ..
```

复制 `.env.example` 为 `.env`，按需配置 provider、数据库、RAG、地图和 CORS。不要把真实
key 提交到仓库。

### 启动

后端：

```powershell
Set-Location backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
Set-Location frontend
npm run dev
```

后端 OpenAPI：<http://127.0.0.1:8000/docs>；健康检查：
<http://127.0.0.1:8000/health> 和 <http://127.0.0.1:8000/api/health>。

Docker 入口仍由 `docker-compose.yml` 提供，但具体端口和环境变量以该文件及 `.env.example`
为准，不在本文复制第二份配置表。

## 当前 API 概览

稳定前端入口是 `/api/v1`：

| 资源 | 路径 |
|---|---|
| 创建会话 | `POST /api/v1/sessions` |
| 状态 | `GET /api/v1/sessions/{id}/state` |
| SSE / 补偿 | `GET /api/v1/sessions/{id}/events`、`events/sync?after=N` |
| HUMAN | `GET/POST /api/v1/sessions/{id}/human-review` |
| 恢复 | `POST /api/v1/sessions/{id}/resume` |
| 交付 / 图层 | `GET /api/v1/sessions/{id}/delivery`、`map-layers` |
| artifact | `GET /api/v1/sessions/{id}/artifacts/{key}` |

详细字段以 `backend/app/api/v1/contracts.py` 和运行中的 OpenAPI 为准。

## 项目结构

```text
backend/app/
├── api/              HTTP、SSE 和 v1 路由
├── application/      commands、queries、projections、resume
├── bootstrap/        lifespan 和组合根
├── contracts/        跨边界类型契约
├── data/             上传、摄取、快照和数据适配
├── domain/           规划、执行、校验和交付业务
├── evidence/         证据索引与检索模型
├── infrastructure/   artifact、事件、runtime、LLM、KG、RAG、provider
├── spatial/          几何、接地、查询、变化、交付和空间校验
└── workflow/         根图、阶段节点、层编排、对话和工具
```

`WorkflowState` 只保存控制字段和 artifact refs；完整业务结果由 typed contracts 和 CAS
artifact 持有。旧的 `app/agent`、`app/modules`、`app/services` 路径只在迁移历史中出现，
不是新代码入口。

## 验证

```powershell
python -m pytest backend/tests/contracts backend/tests/core -q
python -m pytest backend/tests/e2e -q
```

真实验收还必须有真实 provider、checkpoint reopen/resume、实际 HTML/GeoJSON/PNG、
`ParcelChangeSet` 和 `DeliverySpatialSnapshot` 的一致性证据。单元测试、固定 fixture、
空变化集或现状复制图不能替代这些证据。

## 文档状态规则

文档分为：设计（为什么）、实现（在哪里/怎么跑）、指南（怎么做）、参考（查什么）和
审计/计划（历史证据或一次性任务）。实现状态统一使用 `CURRENT / PARTIAL / GAP / TARGET /
HISTORICAL`；详见 [docs/README.md](docs/README.md)。
