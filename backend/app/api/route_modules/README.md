# API route_modules

`route_modules/` 是会话 API 的按职责拆分层。每个文件只负责 FastAPI 路由、请求/响应模型和服务调用，不实现规划算法；领域逻辑由 `app.modules/` 提供，运行编排由 `app.services/` 与 `app.agent/` 提供。

## 模块清单

| 文件 | 端点范围 | 主要职责 |
|---|---|---|
| `session_crud.py` | `/api/sessions`、状态、删除 | 创建会话、上传文件、启动运行、删除会话 |
| `session_sse.py` | `/stream`、`/sync` | SSE 事件流、断线后的 seq 增量同步 |
| `session_hitl.py` | `/feedback`、步骤审核 | 反馈、驳回、继续、人工审核动作 |
| `session_gis.py` | `/geocode`、`/gis-data` | 会话级地理编码和 GIS 数据上传 |
| `session_checkpoints.py` | `/checkpoints`、`/resume` | 稳定检查点列表与恢复 |
| `session_history.py` | reports、projects、planning-text | 报告、版本、阶段追踪和规划文本查询/生成 |

## 运行约束

- 所有路由必须进行输入校验并返回稳定的 HTTP 语义；不要把异常字符串直接作为生产响应。
- SSE 路由不持有数据库会话；订阅、心跳、取消和 `finally` 清理由事件服务负责。
- 长任务通过 `PlanningRuntimeService` 和任务监督器运行，不能把 LangGraph 状态复制到路由局部变量作为第二事实源。
- 任何新的规划能力先进入 `app.modules/` 或已有 `ports/`，路由只做适配。

## 验证

```powershell
pytest -o addopts="" -q backend/tests/core backend/tests/unit
```

主应用健康检查：`GET /health` 是存活检查，`GET /api/health` 是依赖初始化后的就绪检查。
