# 前端与后端集成边界

> 本文只描述当前前端接入方式。完整开发步骤见
> [`../frontend/API_SSE_DEVELOPER_GUIDE.md`](../frontend/API_SSE_DEVELOPER_GUIDE.md)。

## 1. 当前入口

前端通过 `/api/v1` 访问会话、状态、事件、人工审核、恢复、交付、地图图层和 artifact
资源。后端路由位于 `backend/app/api/v1/routes/`，公开模型位于
`backend/app/api/v1/contracts.py`；前端不得引用后端内部 domain model。

```text
create session
  → subscribe /events
  → read /state and /delivery
  → human-review or resume when paused
  → map-layers / artifacts for rendering and inspection
```

## 2. SSE 断线处理

1. 保存最近的 event id/sequence；
2. 断线后请求 `events/sync?after=N`；
3. 有缺口时重新读取 `/state` 和 `/delivery`；
4. 只有用户明确提交 resume/human-review 时才恢复图，不因连接重建而恢复图。

SSE 事件是公开 projection，不是前端的业务事实仓库；最终显示状态应以 state/delivery
查询为准。

## 3. 地图与交付

地图只消费 `map-layers` 的 `RenderLayers` projection。current、planned、change、项目、
设施、道路、轴线和土地平衡应来自同一个 `DeliverySpatialSnapshot`。前端不重新计算
规划地块，不从旧文件路径猜产物，也不把现状复制图标为规划完成。

## 4. 验证

```powershell
python -m pytest backend/tests/contracts backend/tests/core -q
Set-Location frontend
npm run lint
npm run build
```

若 API contract、OpenAPI 或事件字段变化，必须同时更新 `frontend/src/` 类型、本文和开发
指南；历史路径只能保留在 dated audit 中。
