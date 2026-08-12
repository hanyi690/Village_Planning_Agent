# 当前后端 API

> 本文是当前 HTTP/SSE 参考，不是目标 API 设计。路由事实来自
> `backend/app/api/routes.py`、`backend/app/api/v1/routes/` 和
> `backend/app/api/v1/contracts.py`；运行时可在 `/docs`、`/redoc` 查看 OpenAPI。

## 1. 入口与分层

```text
app.main:app
  → app.api.routes.router
      → app.api.v1.router
          → routes/{sessions,state,events,human_review,delivery,map_layers,artifacts}.py
  → application commands / queries / projections
```

路由只做请求解析、错误映射和公开 projection；它不扫描 artifact 目录、不读取 `latest`、
不直接调用图节点、不自行渲染地图。Pydantic request/response models 是边界契约，业务对象
和内部 artifact 不直接暴露给前端。

## 2. 稳定 v1 资源

| 方法 | 路径 | 当前用途 |
|---|---|---|
| `POST` | `/api/v1/sessions` | 创建会话、接收 multipart 文件并启动规划运行 |
| `GET` | `/api/v1/sessions/{session_id}/state` | 读取当前 checkpoint 的公开状态 projection |
| `GET` | `/api/v1/sessions/{session_id}/events` | 订阅当前会话 SSE 事件 |
| `GET` | `/api/v1/sessions/{session_id}/events/sync?after=N` | 从持久事件序号补偿断线 |
| `GET` | `/api/v1/sessions/{session_id}/human-review` | 读取当前 HUMAN interrupt 的 review projection |
| `POST` | `/api/v1/sessions/{session_id}/human-review` | 提交带 event identity 的人工决定 |
| `POST` | `/api/v1/sessions/{session_id}/resume` | 以 interrupt 或显式 checkpoint 模式恢复 |
| `GET` | `/api/v1/sessions/{session_id}/delivery` | 读取 `DeliveryManifest` projection |
| `GET` | `/api/v1/sessions/{session_id}/map-layers` | 读取由交付快照生成的地图图层 |
| `GET` | `/api/v1/sessions/{session_id}/artifacts/{artifact_key}` | 按允许的 key 读取 artifact descriptor 和 payload |

`artifact_key` 的允许集合由 `infrastructure/artifacts/runtime.py` 维护。前端不得根据文件名、
目录或隐式 `latest` 推断产物；身份字段使用 descriptor digest 和 payload digest。

## 3. SSE 与断线同步

事件历史由 `infrastructure/events/repository.py` 保存，在线连接由
`connection_hub.py` 管理，replay/sync 由 `application/queries/run_events.py` 统一处理。

前端处理规则：

1. 连接事件流并保存 `Last-Event-ID`；
2. 断线后调用 `events/sync?after=N`；
3. 如果响应报告序号缺口，重新读取 `/state` 和 `/delivery`；
4. 断线恢复不等于 graph resume，不得因为 SSE 断开而重新执行工作流。

## 4. Resume 与 HUMAN

`POST /resume` 的输入由 `ResumeRequest` 定义，至少区分：

- 当前真实 interrupt 的恢复：携带对应 event identity 和 action；
- 历史 checkpoint 的恢复：携带显式 checkpoint cursor，并创建新 branch；
- 受影响阶段重算：由 application resume service 生成 `ResumePlan`。

路由把参数交给 `application/commands/resume_workflow.py`；真实 checkpoint、interrupt、
artifact parent digest 和 branch 规则由 application/runtime 层验证。API 不通过拼接一个
新的 state 来伪造恢复。

## 5. 健康与开发辅助接口

| 方法 | 路径 | 用途 |
|---|---|---|
| `GET` | `/` | API 基本信息 |
| `GET` | `/health` | 进程存活信息 |
| `GET` | `/api/health` | 数据库、checkpointer、LangGraph readiness |
| `GET` | `/api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}` | 服务端代理天地图瓦片；需要配置 key |

`/api/health` 在 lifespan 完成数据库、组合根和 runtime 初始化前返回非 ready。

## 6. 验证

```powershell
python -m pytest backend/tests/contracts backend/tests/core -q
python -m pytest backend/tests/e2e -q
```

接口文档以 OpenAPI 和 route contract 为准；如果本文与运行中的 `/openapi.json` 不一致，
先修正本文或标注状态，不要在文档里保留第二套 API。
