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
`backend/app/main.py`。当前实现、总体设计和验收证据分开维护：

- 当前代码入口、四段主图和边界：[docs/architecture/CURRENT_RUNTIME.md](docs/architecture/CURRENT_RUNTIME.md)
- API/SSE/resume/state：[docs/architecture/API_AND_STATE.md](docs/architecture/API_AND_STATE.md)
- 启动、RAG/embedding 退化和测试：[docs/architecture/OPERATIONS.md](docs/architecture/OPERATIONS.md)
- 总体设计基线：[docs/design/00_SYSTEM_DESIGN.md](docs/design/00_SYSTEM_DESIGN.md)
- 当前到目标的唯一迁移清单：[docs/design/05_MIGRATION.md](docs/design/05_MIGRATION.md)
- 生成的 API 契约：[docs/contracts/openapi-v1.json](docs/contracts/openapi-v1.json)
- 稳定术语：[docs/reference/terminology.md](docs/reference/terminology.md)
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

详细字段以 Pydantic contracts、[生成的 OpenAPI](docs/contracts/openapi-v1.json) 和运行中的 OpenAPI 为准。

## 项目结构

```text
backend/app/
├── api/              HTTP、SSE 和 v1 路由
├── application/      commands、queries、projections、resume
├── bootstrap/        lifespan 和组合根
├── contracts/        跨边界类型契约
├── data/             上传、摄取、快照和数据适配
├── modules/          L1/L2/L3、Evidence、目标投影、接地、选择和执行业务模块
├── core/             共享确定性原语和运行配置
├── infrastructure/   artifact、事件、Context/Evidence/Structured runtime、LLM、KG、RAG、provider
├── spatial/          几何、接地、查询、变化、交付和空间校验
└── workflow/         根图、阶段节点、层编排、对话和工具
```

`WorkflowState` 只保存控制字段和 artifact refs；完整业务结果由 typed contracts 和 CAS
artifact 持有。已退役目录只保存在历史归档中，不是新代码入口。

## 验证

```powershell
$env:PYTHONPATH = 'backend'
python -m compileall -q backend/app
python -c "from app.modules.l1.application import L1Application; from app.modules.l2.application import L2Application; from app.modules.l3.application import L3Application; print('stage facades import ok')"
python scripts/acceptance/l1_facade_probe.py --help
git diff --check
```

真实验收还必须有真实 provider、checkpoint reopen/resume、实际 HTML/GeoJSON/PNG、
`ParcelChangeSet` 和 `DeliverySpatialSnapshot` 的一致性证据。单元测试、固定 fixture、
空变化集或现状复制图不能替代这些证据。

## 文档状态规则

文档分为：设计（为什么）、实现（在哪里/怎么跑）、指南（怎么做）、参考（查什么）和
审计/计划（历史证据或一次性任务）。实现状态统一使用 `CURRENT / PARTIAL / GAP / TARGET /
HISTORICAL`；详见 [docs/README.md](docs/README.md)。
