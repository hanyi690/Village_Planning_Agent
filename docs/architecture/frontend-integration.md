# 前端对接实现映射（CURRENT）

本文只描述当前代码已经挂载的 v1 transport、artifact descriptor、SSE 和空间交付读取方式。
目标行为与不可妥协不变量见 [`docs/design/14_BACKEND_MODULE_BLUEPRINT.md`](../design/14_BACKEND_MODULE_BLUEPRINT.md)；
实现差距以 [`docs/design/10_IMPLEMENTATION_STATUS.md`](../design/10_IMPLEMENTATION_STATUS.md) 为准。

## 1. 前端只消费投影，不成为规划事实 owner

前端可以读取：

- `SessionProjection`：当前阶段、状态、进度、链接和交付状态；
- `PublicEvent`：持久事件的增量通知；
- `HumanReviewProjection`：当前真实 interrupt 的待审项目；
- `ArtifactDescriptor + payload`：显式 checkpoint refs 指向的 typed artifact；
- `MapLayerCollection`：由 `DeliverySpatialSnapshot` 派生的地图投影；
- `DeliveryProjection`：manifest、statutory/diagnostic 状态和下载项。

Markdown、StepReport、SSE data 和 PNG/HTML 都是投影或交付物，不能被前端重新解释为规划输入。
特别是前端不得根据项目名称、地块 `dlbm` 或颜色推导规划分类。

## 2. 当前调用闭环

```text
POST /api/v1/sessions
  -> session_id
GET  /api/v1/sessions/{id}/events
  -> persistent PublicEvent(seq)
  -> GET /state 或显式 /artifacts/{artifact_key}
  -> GET /delivery /map-layers
  -> 读取实际 GeoJSON、HTML、双 panel PNG
```

SSE 只通知“哪个阶段或事件已提交”，完整业务数据始终从 checkpoint 的显式 refs 读取。断线恢复
不会触发图 resume：使用 `Last-Event-ID` 补发事件；发生缺口时读取 `/state`，再按当前 refs 拉取。

## 3. v1 资源

正式入口均带 `/api/v1`：

| 方法 | 路径 | 用途 |
|---|---|---|
| POST | `/api/v1/sessions` | 创建会话并冻结数据快照 |
| GET | `/api/v1/sessions/{id}/state` | 当前公开状态投影 |
| GET | `/api/v1/sessions/{id}/events` | SSE 持久事件流 |
| GET | `/api/v1/sessions/{id}/events/sync` | 按 seq 补发事件 |
| GET | `/api/v1/sessions/{id}/human-review` | 当前真实 interrupt 投影 |
| POST | `/api/v1/sessions/{id}/human-review` | 提交带 event_id 的人工决策 |
| POST | `/api/v1/sessions/{id}/resume` | 从明确 checkpoint 分叉恢复 |
| GET | `/api/v1/sessions/{id}/delivery` | 交付投影 |
| GET | `/api/v1/sessions/{id}/map-layers` | 地图图层集合 |
| GET | `/api/v1/sessions/{id}/artifacts/{artifact_key}` | 读取一个显式 artifact |

旧 `/api/sessions/.../artifacts`、按 artifact type 找 latest、`?version=N`、`/render-layers` 和
旧 `/stream` 不属于当前实现，前端不得调用。

## 4. Artifact descriptor

`artifact_refs` 只存在于当前 LangGraph checkpoint。每个值是 `ArtifactDescriptor`：

```json
{
  "digest": "sha256:<64 hex>",
  "descriptor_digest": "sha256:<64 hex>",
  "media_type": "application/json",
  "size_bytes": 1234,
  "schema_id": "DeliverySpatialSnapshot",
  "schema_version": "3",
  "semantic_digest": "sha256:<64 hex>",
  "parent_digests": {
    "execution_result": "sha256:<64 hex>"
  },
  "producer_stage": "deliver",
  "run_id": "session-id",
  "branch_id": "main",
  "created_at": "2026-08-11T00:00:00Z",
  "provenance": {"artifact_key": "delivery_spatial_snapshot"}
}
```

含义：

- `digest` 是内容 blob 身份；相同内容可跨 branch 复用；
- `descriptor_digest` 是带 schema、父输入、producer、run/branch/provenance 的不可变描述身份；
- `parent_digests` 是 resume/StepReport 的输入血缘；
- `branch_id` 区分历史 checkpoint fork；HUMAN interrupt resume 不创建伪造 branch；
- 不存在 `revision`、`artifact_id`、`latest` 或前端可修改的版本指针。

### 4.1 读取一个 artifact

```http
GET /api/v1/sessions/{session_id}/artifacts/delivery_spatial_snapshot
```

成功响应：

```json
{
  "session_id": "sid",
  "artifact_key": "delivery_spatial_snapshot",
  "artifact_ref": {"digest": "sha256:...", "descriptor_digest": "sha256:..."},
  "payload": {}
}
```

请求不存在或尚未进入当前 checkpoint 的 key 返回 404。前端应将其显示为“阶段尚未产出”，而不是
构造空结果或读取旧文件。

常用 key：`l1_snapshot`、`l2_strategy`、`planning_program`、`grounding_result`、`site_selection`、
`execution_plan`、`execution_result`、`validation_report`、
`reconciliation_report`、`delivery_spatial_snapshot`、`render_layers`、`delivery_manifest`、
`render_artifacts`、`deferral_ledger`。

## 5. 地图与交付

`GET /map-layers` 只从当前 checkpoint 的 `delivery_spatial_snapshot` 和 `render_layers` 读取。它不扫描
CAS 目录，也不从 `PlannedState`、`gis_data` 或历史文件拼装结果。

响应的 `layers[]` 是 GeoJSON 图层投影：

```json
{
  "session_id": "sid",
  "snapshot_checksum": "sha256:...",
  "delivery_status": "complete",
  "layers": [
    {
      "layer_type": "planned",
      "layer_name": "complete_planned_landuse",
      "checksum": "<sha256>",
      "feature_count": 660,
      "geojson": {"type": "FeatureCollection", "features": []}
    }
  ]
}
```

当前交付要求：

- `current_landuse` 与 `complete_planned_landuse` 分层，且两侧按分类颜色绘制并保留地块边界；
- `changes` / `planned_project` / `planned_project_point` / `planned_facility` / `planned_road` /
  `planned_axis` 等 overlay 独立开关；没有真实产出就省略，不补造；
- `planning_preview.png` 是一个文件、两个带标题 panel：左现状，右规划；右侧显示规划颜色、变化
  地块、项目面和足够小的项目/设施定位点；
- `planning_map.html` 可独立切换 current/planned/overlay 图层；
- `complete_planned_landuse.geojson` 必须从同一 `DeliverySpatialSnapshot` 读取，不能由 renderer 另行推导；
- `DeliveryManifest` 的 `statutory_complete=false` 或 `diagnostic_only` 必须在 UI 中显著显示，不能当作法定成果。
- 当 `DeliverySpatialSnapshot.change_summary` 的 `modified/split/merged/created/removed` 总数为 0 时，UI
  必须显示“无地类变更/全部保留现状”；项目点或设施点只能显示为定位 overlay，不能显示为已完成的地块建设。

前端不要凭 `feature_count=660` 判断规划成功。必须检查：规划分类是否变化、`changes` 是否有实际
项目/地块、项目属性是否有 `target_id`/类型/来源、定位点是否与项目关联，以及交付 gate 是否通过。

## 6. SSE 与 resume 的边界

事件最少包含 `event_id`、`seq`、`session_id`、`occurred_at`、`type`、`data`。`seq` 由持久事件仓库
拥有；在线 hub 只广播，不生成关键业务事实。

推荐客户端策略：

1. 建立 SSE 连接并保存最后一个 `seq`；
2. 收到 `stage_completed`/`artifact_committed` 后按 key 拉取 artifact；
3. 收到 `delivery_ready` 后同时拉取 `/delivery` 与 `/map-layers`，再读取 `render_artifacts`；
4. 连接中断后带 `Last-Event-ID` 重连；若服务返回 `resync_required`，先拉 `/state`，再按当前 refs 补齐；
5. 只有用户提交当前真实 Human Review 的 `event_id`/decision 时才调用 human-review；不要用 SSE 重播代替图 resume；
6. 普通历史 checkpoint resume 是后端创建新 `branch_id` 的显式操作，前端只展示返回的 branch/checkpoint 信息。

## 7. 缓存与一致性

缓存 key 使用 `artifact_key + descriptor_digest`，而不是 artifact type、文件名或 revision。收到新 descriptor
时替换当前视图；旧 descriptor 仍可作为审计引用，但不能写回当前 branch。

同一响应内的 `DeliverySpatialSnapshot`、GeoJSON、render layers 和 manifest 必须能通过 descriptor/parent
digest 追溯到同一交付 checkpoint。若 digest 或 parent 校验失败，显示诊断状态并停止地图“成功”展示。

## 8. StepReport 前端展示

StepReport 是运行审计投影，不是新的业务状态。每条 artifact 记录至少显示：`key`、`digest`、
`descriptor_digest`、`schema_id`、`producer_stage`、`run_id`、`branch_id` 和 `parent_digests`。
用户点击“查看产物”时调用显式 artifact-key endpoint；不要把 Markdown 中的摘要重新解析成状态。

## 9. 当前代码位置

| 能力 | 当前实现 |
|---|---|
| v1 routes/SSE | `backend/app/api/v1/routes.py` |
| artifact descriptor contract | `backend/app/modules/schema/contracts/artifact_descriptor.py` |
| CAS blob/named ref | `backend/app/infrastructure/artifacts/repository.py` |
| workflow artifact boundary | `backend/app/infrastructure/artifacts/runtime.py` |
| current/planned/render/export snapshot | `backend/app/modules/spatial_ops/io/delivery_snapshot.py`、`backend/app/agent/deliver/delivery_snapshot_builder.py` |
| double-panel renderer | `backend/app/agent/deliver/delivery_renderer.py`、`backend/app/tools/gis/static_render.py` |
| StepReport | `backend/app/modules/evidence/step_report.py`、`backend/app/modules/evidence/stage_report.py` |

实现状态和未完成模块以 `docs/design/10_IMPLEMENTATION_STATUS.md` 为准；本文不把文件存在或
deterministic replay 宣称为真实规划完成。
