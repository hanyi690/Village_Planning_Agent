# 前端对接：Typed Artifact 消费（Frontend Integration）

> 回答"前端如何消费 typed artifact，而不是解析 Markdown 文本"。
> 配套文档：[frontend.md](./frontend.md)（前端架构/SSE）、[backend-api.md](./backend-api.md)（后端 API 总览）、
> [../design/00_SYSTEM_DESIGN.md](../design/00_SYSTEM_DESIGN.md)（系统设计：三类权威产物）。

## 1. 概述

后端流水线（L1/L2/L3 + post-L3 链 PARSE → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER）
会为每个阶段产出 **typed artifact**（类型化、带版本、带元数据的 JSON 产物），并统一持久化到
`FilesystemArtifactStore`。

**核心原则**（见 00_SYSTEM_DESIGN.md §2）：

> Markdown 报告、SSE 事件、UI 展示都是 typed artifacts 的**视图**，不是新的事实源。

因此前端应当：

- 把 typed artifact 作为**权威数据源**（如 L1 现状快照、L2 策略、L3 干预、PlannedState 规划成果）；
- 用 **SSE 事件** 作为"何时去拉取"的信号，SSE 本身只做增量提示，不做完整数据传递；
- **不要**从 Markdown 报告里正则解析事实/指标/图层——那些都已被后端编译进 artifact 的 payload；
- 通过只读查询端点按 `artifact_type` 拉取，并用 `?version=N` 追溯历史版本。

## 2. 快速开始

前端对接一条完整规划流程的最小闭环：

```
1. POST /api/sessions                     创建会话，得到 session_id
        │
2. GET  /api/sessions/{id}/stream         EventSource 监听 SSE（单通道）
        │
3. SSE  layer_completed / gis_result      "信号"：某个权威产物已就绪
        │
4. GET  /api/sessions/{id}/artifacts      列出全部 artifact ref（含 artifact_type / revision）
        │
5. GET  /api/sessions/{id}/artifacts/{type}  按类型拉取 payload（权威数据）
        │
6. GET  /api/sessions/{id}/render-layers  把 PlannedState 转成 GeoJSON 图层（喂给 MapLibre）
```

```bash
# 1. 创建会话
curl -X POST http://localhost:8000/api/sessions \
  -F "project_name=测试村" -F "village_data=xxx" -F "task_description=xxx"
# => { "session_id": "sid_xxx", "stream_url": "...", "status": "running" }

# 2. 监听 SSE（另一终端）
curl -N http://localhost:8000/api/sessions/sid_xxx/stream

# 3. 收到 layer_completed / gis_result 后，拉取 artifact 列表
curl http://localhost:8000/api/sessions/sid_xxx/artifacts

# 4. 按类型拉取权威产物（如 L1 现状快照）
curl http://localhost:8000/api/sessions/sid_xxx/artifacts/L1Snapshot

# 5. 拉取渲染图层（PlannedState -> GeoJSON）
curl http://localhost:8000/api/sessions/sid_xxx/render-layers
```

## 3. 12 个 typed artifact 参考

所有 artifact 共享同一个查询方式（按 `artifact_type`），下表说明各自的**用途、生产者/消费者、
关键字段（前端消费常用）**。完整字段以 `backend/app/modules/schema/contracts/*.py` 为准。

| # | artifact_type | 用途 | 生产者 → 消费者 | 前端何时消费 |
|---|---------------|------|------------------|--------------|
| 1 | `L1Snapshot` | L1 现状快照：核验后的事实、约束、问题、机会、证据缺口 | L1 子图 → L2/L3/Explore | L1 层完成后展示现状分析 |
| 2 | `L2Strategy` | L2 策略：发展目标、空间结构、实施优先级、策略冲突 | L2 子图 → L3/Select/Explore | L2 层完成后展示策略页 |
| 3 | `PlanningProgram` | L3 干预：项目/设施/道路/分区等规划干预及其依赖、遗漏 | L3 子图 → PARSE/Explore | L3 层完成后展示干预清单 |
| 4 | `IntentCompilationResult` | PARSE 编译结果：typed intent + 空间引用规格 + 诊断 + 编译状态 | PARSE → Ground/Select/Execute | 解析阶段完成后展示编译诊断 |
| 5 | `GroundingResult` | GROUND：候选地块 `candidates[CandidateSite]`、未解析项、空间查询证据 | Ground 子图 → Select | 空间接地阶段展示候选地块 |
| 6 | `SiteSelectionDecision` | SELECT：选中组合、完整排序、淘汰项、决策因素 | Select 子图 → Execute | 选址阶段展示选址结果/排序 |
| 7 | `ExecutionPlan` | EXECUTE 调度：worker 任务、依赖、intent、site_selection | Execute 子图 → Worker | 执行阶段展示任务进度 |
| 8 | `ParcelChangeSet` | 地块变更：`changes[ParcelChange]`（含 derived_from_bsms） | Execute → Validate/Reconcile | 执行后展示地块变更表 |
| 9 | `PlannedState` | 规划成果：parcels/zones/facilities/roads/axes | Execute → Validate/Reconcile/Delivery | **渲染图层**的权威来源 |
| 10 | `ValidationReport` | 校验报告：checks、overall_passed、issues_by_stage | Validate → Reconcile | 校验阶段展示通过/失败 |
| 11 | `ReconciliationReport` | 对账：coverage_matrix、inconsistencies | Reconcile → Delivery | 对账阶段展示覆盖率/不一致 |
| 12 | `DeliveryManifest` | 交付：deliverables、traceability、pending_human_items、delivery_gate | Deliver → Export/Render/Report | 最终交付状态展示 |

### 3.1 各 artifact 关键字段

#### `L1Snapshot`（模块 `l1_observe`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `facts` | `string[]` | 核验后的现状事实 |
| `constraints` | `string[]` | 现状约束 |
| `issues` | `StageIssue[]` | 现状问题（severity/code/message） |
| `opportunities` | `string[]` | 发展机会 |
| `evidence_gaps` | `EvidenceGap[]` | 证据缺口（gap_id/dimension/severity） |
| `classification_refs` | `ClassificationRef[]` | 用地分类引用 |

#### `L2Strategy`（模块 `l2_strategize`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `development_goals` | `string[]` | 发展目标 |
| `spatial_structure` | `string` | 空间结构表述 |
| `implementation_priorities` | `string[]` | 实施优先级 |
| `strategy_conflicts` | `StrategyConflict[]` | 策略冲突（between/severity） |
| `evidence_refs` | `string[]` | 证据引用 |

#### `PlanningProgram`（模块 `l3_plan`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `interventions` | `PlanningIntervention[]` | 干预项（intervention_id/name/category/scale/implementation_phase） |
| `dependencies` | `InterventionDependency[]` | 干预依赖（from/to/dependency_type） |
| `omissions` | `string[]` | 遗漏项 |
| `program_issues` | `ProgramIssue[]` | 程序级问题 |
| `l1_snapshot_ref` / `l2_strategy_ref` | `string` | 上游 artifact 引用（可追溯） |

#### `IntentCompilationResult`（模块 `parse`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `typed_intent` | `SpatialPlanningIntent` | 类型化规划意图 |
| `spatial_reference_specs` | `SpatialReferenceSpec[]` | 空间引用规格 |
| `project_requirements` | `ProjectRequirement[]` | 项目需求 |
| `diagnostics` | `ParseDiagnostic[]` | 编译诊断（severity/code/message） |
| `compilation_status` | `CompilationStatus` | draft/validated/needs_repair/needs_review/committed/rejected |
| `confidence` | `number` | 置信度 0~1 |

#### `GroundingResult`（模块 `ground`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `candidates` | `CandidateSite[]` | 候选地块（site_id/source_parcels/available_area_ha/metrics） |
| `unresolved` | `StageIssue[]` | 未解析的空间引用 |
| `spatial_query_evidence` | `SpatialQueryEvidence[]` | 空间查询证据 |

#### `SiteSelectionDecision`（模块 `select`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `selected_combination` | `string[]` | 最终选中组合（site_id 列表） |
| `full_ranking` | `RankedCandidate[]` | 完整排序（rank/score/score_breakdown） |
| `eliminated` | `EliminatedCandidate[]` | 淘汰项及原因 |
| `decision_factors` | `object` | 决策因素 |
| `review_status` | `string` | auto/pending_review/human_approved |

#### `ExecutionPlan`（模块 `execute`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `plan_id` | `string` | 执行计划 ID |
| `worker_tasks` | `WorkerTask[]` | worker 任务（task_id/worker_type/depends_on） |
| `dependencies` | `object[]` | 任务依赖 |
| `intent` / `site_selection` | `any` | 上游 PARSE/SELECT 引用（内嵌或 None） |

#### `ParcelChangeSet`（模块 `execute`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `changes` | `ParcelChange[]` | 地块变更（bsm/action/derived_from_bsms/before·after_classification/new_area_ha） |
| `area_conservation_verified` | `boolean` | 面积守恒校验 |
| `geometry_validity_verified` | `boolean` | 几何有效性校验 |

#### `PlannedState`（模块 `execute`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `parcels` | `PlannedParcel[]` | 规划地块（bsm/planning_land_use/zone_type/geometry(WKT)/area_ha） |
| `zones` | `PlannedZone[]` | 规划分区（zone_type/name/geometry/area_ha） |
| `facilities` | `PlannedFacility[]` | 设施（name/facility_type/lon/lat/service_radius） |
| `roads` | `PlannedRoad[]` | 道路（name/road_level/width_m） |
| `axes` | `PlannedAxis[]` | 轴带 |

> 前端一般**不直接**消费 PlannedState 里的 WKT 几何，而是用 `render-layers` 端点拿到现成的 GeoJSON。

#### `ValidationReport`（模块 `validate`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `checks` | `ValidationCheck[]` | 校验项（check_id/check_name/passed/responsible_stage/fix_suggestion） |
| `overall_passed` | `boolean` | 总体是否通过 |
| `issues_by_stage` | `Record<string, ValidationIssue[]>` | 按责任阶段分组的失败问题 |

#### `ReconciliationReport`（模块 `reconcile`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `coverage_matrix` | `CoverageMatrix` | 干预→地块覆盖矩阵（rows 含 status: covered/partial/missing） |
| `inconsistencies` | `ReconciliationInconsistency[]` | 意图与成果不一致项 |

#### `DeliveryManifest`（模块 `deliver`）

| 字段 | 类型 | 说明 |
|------|------|------|
| `deliverables` | `Deliverable[]` | 交付物（deliverable_id/type/path/format） |
| `traceability` | `TraceabilityEntry[]` | 追溯链（intervention→selection→change→planned） |
| `pending_human_items` | `HumanItem[]` | 待人工处理项（item_id/description/blocking） |
| `delivery_gate` | `DeliveryGate` | 出口硬门槛（land_balance_closed/three_line_violations/zones_complete...） |
| `statutory_complete` | `boolean` | 法定成果是否完整 |

## 4. Artifact 查询端点

三个只读端点（`backend/app/api/artifact_routes.py`）返回结构一致：`session_id + revision +
artifact_ref（ArtifactRef）+ manifest（+ payload）`。

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/sessions/{session_id}/artifacts` | 列出该会话最新 artifact ref 列表 |
| GET | `/api/sessions/{session_id}/artifacts/{artifact_type}` | 按类型取 payload + manifest（可 `?version=N`） |
| GET | `/api/sessions/{session_id}/artifacts/{artifact_type}/ref` | 只取 ref 元数据 + manifest（可 `?version=N`） |

### 4.1 列出所有 artifact

```bash
curl http://localhost:8000/api/sessions/sid_xxx/artifacts
```

```json
{
  "session_id": "sid_xxx",
  "artifacts": [
    {
      "context_version": "2026-08-05T00:00:00Z",
      "artifact_id": "l1_snapshot_abcd1234",
      "module": "l1_observe",
      "run_id": "sid_xxx",
      "artifact_type": "L1Snapshot",
      "revision": "v1"
    },
    {
      "context_version": "2026-08-05T00:00:00Z",
      "artifact_id": "l2_strategy_abcd1234",
      "module": "l2_strategize",
      "run_id": "sid_xxx",
      "artifact_type": "L2Strategy",
      "revision": "v1"
    }
  ],
  "count": 2
}
```

- 返回的是**最新 revision** 的 ref；已存在的 artifact 才出现，未产生的阶段不会出现。
- 会话存在但没有 artifact 时返回 `count: 0` 与空数组；会话不存在且无 artifact 时返回 404。

### 4.2 按类型取 payload（带 manifest）

```bash
# 取最新版本
curl http://localhost:8000/api/sessions/sid_xxx/artifacts/PlannedState

# 指定版本（可选）
curl "http://localhost:8000/api/sessions/sid_xxx/artifacts/PlannedState?version=1"
```

```json
{
  "session_id": "sid_xxx",
  "artifact_type": "PlannedState",
  "revision": "v1",
  "artifact_ref": {
    "context_version": "2026-08-05T00:00:00Z",
    "artifact_id": "planned_state_abcd1234",
    "module": "execute",
    "run_id": "sid_xxx",
    "artifact_type": "PlannedState",
    "revision": "v1"
  },
  "payload": {
    "version": "v1",
    "parcels": [],
    "zones": [],
    "facilities": [],
    "roads": [],
    "axes": []
  },
  "manifest": {
    "artifact_id": "planned_state_abcd1234",
    "module": "execute",
    "run_id": "sid_xxx",
    "artifact_type": "PlannedState",
    "context_version": "2026-08-05T00:00:00Z",
    "revision": "v1",
    "created_at": "2026-08-05T00:00:00Z",
    "checksum": "sha256...",
    "payload_bytes": 1234
  }
}
```

### 4.3 只取 ref 元数据

```bash
curl http://localhost:8000/api/sessions/sid_xxx/artifacts/L1Snapshot/ref
```

返回结构同上，但**不含 `payload`**（`session_id + artifact_type + revision + artifact_ref + manifest`）。
适合前端先比对 `revision` / `context_version` 判断是否需要重新拉取 payload。

### 4.4 `?version=N` 用法

- `version` 是整数，对应 revision 名里的数字：`v1` → `1`、`v2` → `2`。
- 不传 `version` 时返回**最新** revision。
- 传不存在的版本返回 404，`detail` 会列出支持的版本：

```bash
curl -i "http://localhost:8000/api/sessions/sid_xxx/artifacts/L1Snapshot?version=99"
# HTTP/1.1 404 Not Found
# { "detail": "Version 99 not stored for L1Snapshot; supported versions: [1]" }
```

### 4.5 404 / 空处理

| 场景 | 行为 |
|------|------|
| 会话不存在且无 artifact | 404（`Session not found`） |
| 会话存在但该类型从未产出 | 404（`Artifact type not found: ... for session ...`） |
| 版本不存在 | 404（detail 含 supported versions） |
| 会话存在但尚无任何 artifact | 200，`artifacts: []`、`count: 0` |

> 前端应把"该类型 404"理解为"该阶段尚未完成"，配合 SSE 信号等待重试，而不是当作致命错误。

## 5. 渲染图层端点

`GET /api/sessions/{session_id}/render-layers`（`backend/app/api/render_routes.py`）
从最新 `PlannedState` artifact 派生 GeoJSON 图层（优先使用 live AgentState 的 `layout_configs`）。

```bash
curl http://localhost:8000/api/sessions/sid_xxx/render-layers
```

```json
{
  "session_id": "sid_xxx",
  "layers": [
    {
      "layerType": "function_zone",
      "layerName": "功能分区",
      "data": {
        "type": "FeatureCollection",
        "features": [
          {
            "type": "Feature",
            "properties": { "bsm": "A001", "planning_land_use": "住宅用地", "zone_type": "residential", "operation": "reclassify", "area_ha": 2.35 },
            "geometry": { "type": "Polygon", "coordinates": [] }
          }
        ]
      }
    }
  ]
}
```

### 5.1 layerType 说明

| layerType | layerName | 几何 | properties 关键字段 | 来源 |
|-----------|-----------|------|---------------------|------|
| `function_zone` | 功能分区 | Polygon | `bsm` / `planning_land_use` / `zone_type` / `operation` / `area_ha`（分区项另有 `name`） | PlannedState.parcels + zones |
| `facility_point` | 公共服务设施 | Point | `name` / `facility_type` / `service_radius` | PlannedState.facilities（lon/lat） |
| `planned_road` | 规划道路 | 无几何（metadata） | `name` / `road_level` / `width_m` | PlannedState.roads |
| `planned_project` | 规划项目 | 依 layout_configs | 见 layout_configs | live AgentState（可选合并） |

- 没有数据/几何的 layerType 会直接**省略**，响应只含非空图层。
- 找不到 `PlannedState` artifact 时返回 404（`PlannedState artifact not found for session`）。

### 5.2 MapLibre 渲染建议

参考 [frontend.md §5](./frontend.md)（`maplibre-gl` + `react-map-gl`，底图走天地图代理
`/api/tiles/tianditu/{layer_proj}/{z}/{y}/{x}`）：

- 每个 `layer` 元素作为一个 **GeoJSON source**（`map.addSource(layerType, { type: 'geojson', data: layer.data })`）；
- 按 `layerType` 决定渲染方式并分层，便于 `LayerTogglePanel` 开关：
  - `function_zone` → `fill`（按 `planning_land_use` 配色）+ 可选 `line` 描边；
  - `facility_point` → `circle`（按 `facility_type` 分类符号）；
  - `planned_road` → 无几何，可降级为表格/列表展示，或等后端补几何后转 `line`；
  - `planned_project` → 依几何类型 `fill` / `circle`；
- 图层名显示用 `layerName`（中文），内部 id 用 `layerType`；
- 重复拉取时先 `map.removeSource/removeLayer` 再重建，避免图层残留。

## 6. HITL 流程（人工审查）

post-L3 链在 `human_review` 节点会 **INTERRUPT 暂停**，等人工审批后才 resume 继续执行。

### 6.1 何时暂停

- 主图 AgentState 写入 `post_l3_status = "needs_human_review"`，并把待审 items 写入
  `post_l3_pending_review`；
- 前端可通过 SSE `pause` 事件、`GET /api/sessions/{id}/status` 的 `interrupt_info`，或直接轮询
  `GET /api/human-review/{session_id}` 探测暂停状态。

### 6.2 查询待审项

```bash
curl http://localhost:8000/api/human-review/sid_xxx
```

```json
{
  "session_id": "sid_xxx",
  "post_l3_status": "needs_human_review",
  "pending_items": [
    { "request_id": "hr_1", "stage": "parse", "request_type": "resolve_ambiguity", "context": {} }
  ],
  "count": 1
}
```

- `pending_items` 每项含 `request_id` / `stage` / `request_type` / `context`，供前端渲染审批面板；
- 会话不存在返回 404。

### 6.3 提交决策并 resume

```bash
curl -X POST http://localhost:8000/api/human-review/sid_xxx/resolve \
  -H "Content-Type: application/json" \
  -d '{"decisions": { "hr_1": { "action": "approve" } }}'
```

```json
{
  "session_id": "sid_xxx",
  "resolved": true,
  "result": {}
}
```

- `decisions` 是自由结构（resume payload），key 建议用 `pending_items[].request_id`；
- resume 成功后 `post_l3_status` 变为 `resumed`，`pending_items` 清空，链继续执行并最终产出
  `DeliveryManifest` / `render-layers`。

### 6.4 前端 UI 建议（审批面板）

- 收到暂停信号后拉取 `getHumanReview`，展示"待审批 N 项"提示；
- 面板逐项展示 `stage` + `request_type` + `context`，提供 **通过 / 驳回并修改** 操作；
- 点击提交调用 `resolveHumanReview(sessionId, decisions)`；
- 提交期间禁用按钮（防重复提交），成功后清空面板并继续监听 SSE（等待 `gis_result` / `completed`）。

## 7. SSE 事件 → artifact 状态映射

SSE 是"信号"，artifact 端点才是"数据"。收到以下事件时前端应拉取对应权威产物：

| SSE 事件 | 含义 | 前端动作 |
|----------|------|----------|
| `layer_completed`（layer=1） | L1 层完成 | `GET artifacts/L1Snapshot` |
| `layer_completed`（layer=2） | L2 层完成 | `GET artifacts/L2Strategy` |
| `layer_completed`（layer=3） | L3 层完成 | `GET artifacts/PlanningProgram` |
| `gis_result` | post-L3 链完成，已产出规划成果 | `GET render-layers`（+ 可选 `PlannedState` / `DeliveryManifest` / `ValidationReport`） |
| `gis_layer_update` | GIS 图层增量更新 | 直接渲染事件内 `layers`，或全量刷新 `render-layers` |
| `pause` / `layer_paused` | 流程暂停（含 HITL） | 查询状态；若 `post_l3_status=needs_human_review` 则打开审批面板 |
| `completed` | 全部完成 | 最终刷新 `artifacts` + `render-layers`，展示交付状态 |
| `error` | 失败 | 展示错误，停止拉取 |

> 由于 SSE 事件只带"信号"（`layer` / `dimension_key` 等），数据一致性始终以 artifact 端点为锚，
> 断线重连后也只需重新拉取 `GET /artifacts` 对比 `revision` 即可补齐。

## 8. artifact ref 与版本管理

`ArtifactRef` 是前端追溯任何产物的"坐标"（前端类型见 `frontend/src/features/planning/api/types.ts`）：

```json
{
  "context_version": "2026-08-05T00:00:00Z",
  "artifact_id": "l1_snapshot_abcd1234",
  "module": "l1_observe",
  "run_id": "sid_xxx",
  "artifact_type": "L1Snapshot",
  "revision": "v1"
}
```

| 字段 | 说明 |
|------|------|
| `context_version` | 该 artifact 基于的上下文版本（同一轮规划流程内一致），用于追溯"这份数据是哪个上下文的产物" |
| `artifact_id` | 该 artifact 在模块内的唯一 ID |
| `module` | 生产者模块（`l1_observe` / `l2_strategize` / `l3_plan` / `parse` / `ground` / `select` / `execute` / `validate` / `reconcile` / `deliver`） |
| `run_id` | 运行 ID（post-L3 链中等于 `session_id`） |
| `artifact_type` | 类型名（即查询端点用的类型） |
| `revision` | 版本名（`v1`、`v2`...），对应 `?version=N` |

版本管理要点：

- 同一 `artifact_type` 可能多次修订（如 L3 修订后重新编译），每次写入一个新 revision；
- `GET /artifacts` 只列**最新** revision；要拿历史版本用 `?version=N`；
- `manifest` 中的 `created_at` / `checksum` / `payload_bytes` 可用来做缓存与完整性校验；
- `context_version` 变化说明上游上下文变了，旧 payload 不应与新的其他 artifact 混用。

## 9. GeoJSON 图层 schema

`render-layers` 的 `layers[]` 每项：

```
RenderLayer
├─ layerType: string        # 图层内部 id（如 function_zone）
├─ layerName: string        # 图层显示名（中文）
└─ data: FeatureCollection  # GeoJSON（type = "FeatureCollection"）
    ├─ type: "FeatureCollection"
    └─ features: Feature[]
        ├─ type: "Feature"
        ├─ properties: Record<string, unknown>   # 见 §5.1 各 layerType
        └─ geometry: Point | Polygon | ... | null
```

```json
{
  "type": "FeatureCollection",
  "features": [
    {
      "type": "Feature",
      "properties": { "bsm": "A001", "zone_type": "residential", "area_ha": 2.35 },
      "geometry": { "type": "Polygon", "coordinates": [ [ [116.1, 39.9], [116.2, 39.9] ] ] }
    }
  ]
}
```

前端直接把这个对象塞进 MapLibre 的 GeoJSON source 即可，无需再解析 WKT。

## 10. 前端消费建议

### 何时拉取

- **SSE 驱动**：收到 `layer_completed` / `gis_result` / `completed` 才拉取对应 artifact；
- **刷新恢复**：页面刷新 / 断线重连（`sync?from_seq=N`）后，先 `GET /artifacts` 拿到全部 ref，
  再按需拉取需要展示的类型；
- **延迟拉取**：L1/L2/L3 报告展示页仍走现有 `reports/{dim_key}`，而"结构化面板/地图/对账/交付"走 artifact。

### 如何缓存

- 以 `artifact_type + revision`（或 manifest `created_at`）为 key 缓存 payload；
- 拉取前先 `GET /artifacts/{type}/ref`（轻量）比对 revision，变了才拉完整 payload；
- `manifest.checksum` 可用于本地校验；`payload_bytes` 过大时可考虑只取 ref。

### SSE 驱动更新

- SSE 事件不做业务数据传递（除 `gis_layer_update` 等增量图层），全部以 artifact 为准；
- `gis_result` 后应刷新 `render-layers` 而不是直接信任事件内嵌数据（事件可能被截断/精简）。

### 错误处理

- 404 = 阶段未完成 → 标记"等待中"，等下一个 SSE 信号重试（可带退避）；
- `render-layers` 404 = 尚无 PlannedState → 地图区显示空态；
- 网络错误 / SSE 断线 → 重连后走 `sync` + artifact 列表对账。

## 11. API 端点清单表

| 方法 | 路径 | 说明 | 响应要点 |
|------|------|------|----------|
| GET | `/api/sessions/{session_id}/artifacts` | 列出最新 artifact ref | `{session_id, artifacts[], count}` |
| GET | `/api/sessions/{session_id}/artifacts/{artifact_type}` | 取 payload + manifest（`?version=N`） | `{session_id, artifact_type, revision, artifact_ref, payload, manifest}` |
| GET | `/api/sessions/{session_id}/artifacts/{artifact_type}/ref` | 只取 ref 元数据（`?version=N`） | `{session_id, artifact_type, revision, artifact_ref, manifest}` |
| GET | `/api/sessions/{session_id}/render-layers` | PlannedState → GeoJSON 图层 | `{session_id, layers[{layerType, layerName, data}]}` |
| GET | `/api/human-review/{session_id}` | 查询暂停的 HITL 待审项 | `{session_id, post_l3_status, pending_items[], count}` |
| POST | `/api/human-review/{session_id}/resolve` | 提交决策并 resume 链 | `{session_id, resolved, result}` |
| GET | `/api/sessions/{session_id}/stream` | SSE 单通道（信号源） | `text/event-stream` |
| GET | `/api/sessions/{session_id}/sync?from_seq=N` | 断线重连补发事件 | `{events[], last_seq, from_seq}` |
| GET | `/api/sessions/{session_id}/status` | 会话状态（含 interrupt_info / post-L3 相关字段） | `{session_id, status, interrupt_info, ...}` |

对应前端客户端方法（`frontend/src/features/planning/api/planning-api.ts`）：
`getArtifacts` / `getArtifact` / `getArtifactRef` / `getRenderLayers` / `getHumanReview` /
`resolveHumanReview`；类型见 `frontend/src/features/planning/api/types.ts`
（`ArtifactListResponse` / `ArtifactResponse` / `ArtifactRefResponse` / `RenderLayersResponse` /
`HumanReviewListResponse` / `HumanReviewResolveResponse`）。
