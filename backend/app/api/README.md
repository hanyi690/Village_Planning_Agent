# API 层（FastAPI HTTP 入口）

> 前端 HTTP 入口层：参数校验（Pydantic schema）→ 调用 `services/` 业务服务 → 组装响应。**SSE 单通道**架构：全部执行进度/结果通过 SSE 流推送，Checkpoint 为唯一状态源。

---

## 一、层定位

```
前端 ──> api/ (FastAPI) ──> services/ ──> agent/ (LangGraph)
                 │
                 └──> database/ (SQLModel) + modules/
```

路由不做业务逻辑，只做：参数解析 → 调用服务 → 错误转 HTTP 语义 → 响应序列化。

---

## 二、文件清单

| 模块 | 职责 | 挂载 |
|------|------|------|
| `routes.py` | 统一聚合路由 + 健康检查 + 天地图瓦片代理 | ✅ `main.py` |
| `session_routes.py` | 会话核心 API（创建/流/反馈/检查点/报告/规划文本/导出/GIS 上传） | ✅ 经 `routes.py` |
| `gis_test_routes.py` | GIS 开发测试 API（8 端点，仅供前端测试页） | ✅ 经 `routes.py` |
| `admin_code_routes.py` | 2024 行政区划代码查询（china_area-2024） | ⚠️ **未挂载**（无 include_router） |
| `schemas.py` | 请求/响应 Pydantic 模型 + `TaskStatus` 枚举 | — |

---

## 三、会话核心 API（`session_routes.py`）

### 3.1 会话生命周期

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/sessions` | 创建会话（multipart/form-data：文本 + 图片 + GIS/文档上传；`_process_uploaded_file_db` 解析入库） |
| GET | `/api/sessions/{id}/stream` | SSE 事件流（`event_generator` 心跳 + 事件队列消费） |
| GET | `/api/sessions/{id}/sync?from_seq=N` | 断线重连同步（从 seq 增量拉取 + checkpoint 重建事件） |
| POST | `/api/sessions/{id}/feedback` | 用户反馈（触发修订，走 ReviewService） |
| GET | `/api/sessions/{id}/status` | 状态快照（`state_to_ui_status` + 消息提取） |
| DELETE | `/api/sessions/{id}` | 删除会话（级联清理，`SessionService.delete_session`） |

### 3.2 检查点与恢复

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/checkpoints` | 检查点列表（从 `aget_state_history` 提取） |
| POST | `/api/sessions/{id}/resume/{checkpoint_id}` | 从检查点恢复（`PlanningRuntimeService.resume_execution`） |
| PATCH | `/api/sessions/{id}/step-mode` | 切换分步执行模式 |
| GET/PATCH | `/api/sessions/{id}/rag-config` | RAG 开关查询/更新（层级配置） |

### 3.3 报告查询

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/reports/{dim_key}` | 维度报告全文（最新版，`ReportStore.get_latest_report`） |
| GET | `/api/sessions/{id}/reports/{dim_key}/versions` | 版本列表（时间旅行） |
| GET | `/api/sessions/{id}/layer/{layer}/reports` | 整层报告（含 knowledge_sources + instruction） |
| GET | `/api/projects` / `/api/projects/{name}/sessions` / `/api/projects/{name}/reports/{dim_key}` | 项目维度查询 |

### 3.4 规划文本与导出（P9）

| 方法 | 端点 | 说明 |
|------|------|------|
| POST | `/api/sessions/{id}/planning-text` | 生成规划文本（`PlanningTextGenerator` 组装 L3 报告 → docx/JSON 版本化入库） |
| GET | `/api/sessions/{id}/planning-text` (+ `/versions` + `/versions/{v}`) | 规划文本查询（最新版/版本列表/指定版） |
| POST | `/api/sessions/{id}/export` | 导出会话文档（`_export_planning_text` → docx） |

### 3.5 GIS 数据

| 方法 | 端点 | 说明 |
|------|------|------|
| GET | `/api/sessions/{id}/geocode` | 村庄地理编码（行政区划解析） |
| POST | `/api/sessions/{id}/gis-data` | 用户上传 GIS 数据（GeoJSON 类型推断 `_infer_geojson_data_type` / `_infer_data_type_from_filename`，入库供 GIS 流水线使用） |

---

## 四、GIS 开发测试 API（`gis_test_routes.py`）

8 端点（dev 专用，生产应关闭），前缀 `/api/gis-test`：

| 端点 | 说明 |
|------|------|
| `/status` | GIS 服务可用性检查 |
| `/data` | 拉取 GIS 数据（center/bbox/coverage） |
| `/analysis` | 空间分析（isochrone/accessibility/poi） |
| `/validate` | 布局/设施/生态/约束/灾害校验 |
| `/layout` | 全流水线布局生成 |
| `/intent` | 规划文本 → 空间意图解析 |
| `/zones` | 功能分区生成（V/N/E 或三区管控） |
| `/files` (+ `/files/{path}`) | GIS 数据文件浏览/获取 |

---

## 五、Schema 模型（`schemas.py`）

- **枚举**：`TaskStatus`（pending/running/paused/reviewing/revising/completed/failed）
- **多模态**：`ImageData`（base64 + 格式 + 来源 upload/embedded）
- **请求**：`StartPlanningRequest` / `ReviewActionRequest`（approve/reject/rollback）/ `ResumeRequest` / `ChatMessageRequest` / `RunDimensionsRequest` / `RagConfigRequest` / `StepModeRequest`
- **响应**：`SessionStatusResponse` / `ConversationState` / `FileUploadResponse` / `VillageInfo` / `VillageDetail` / `HealthResponse` / `UploadedFileMeta`

---

## 六、中间件与聚合（`main.py` 相关）

- **session_id 注入中间件**：从 URL 正则 `/api/sessions/([^/]+)` 提取 session_id 注入日志上下文（`app/utils/logger.set_session_id`）
- **统一路由**：`routes.py` 聚合 session + gis_test 两个子路由；另含 `/api/health` 健康检查与 `/api/tiles/tianditu/{layer}_{proj}/{z}/{y}/{x}` 天地图瓦片代理（随机 8 服务器 + 15s 超时 + 86400s 缓存，避免前端跨域与 Key 暴露）

---

## 七、相关文档

- `app/services/README.md` — 业务服务层（本层所有路由的服务端实现）
- `app/database/README.md` — 数据表（`dimension_reports` / `planning_sessions` / `planning_bundles` 等）
- `app/modules/planning_text/README.md` — 规划文本生成（P9 端点消费方）
- `app/core/events.py` — SSE 事件类型定义
