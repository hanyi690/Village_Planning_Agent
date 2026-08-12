# 前端接入说明

前端只使用 `/api/v1`。会话创建后，以 `state` 作为控制状态、以 SSE 作为追加进度、以
`delivery`/`map-layers` 作为最终空间投影。

## 典型流程

```text
POST /api/v1/sessions
  → GET /state
  → GET /events (Last-Event-ID)
  → 若 human_review_pending：读取 human-review 并提交 event_id
  → delivery=complete|partial|diagnostic_only
  → GET /map-layers
```

`partial` 和 `diagnostic_only` 是合法终态，但不能在 UI 中显示为法定完整成果。`partial` 必须
展示 deferral summary；缺少现状或规划图层时应显示数据质量错误，而不是绘制空白或补造地块。

## 地图图层

`map-layers.layers[]` 每项是已由 DELIVER 写入的 FeatureCollection。`layer_type` 表示
`current/planned/overlay/constraint`，`layer_name` 是具体图层。至少应独立控制：

- `current_landuse`
- `complete_planned_landuse`
- `planned_changes`
- `planned_project`
- `planned_project_point`
- `facility_point`
- `planned_road`
- `development_axis`

项目/设施点的 marker 应足够小；规划地块仍须保留地块边界和地类颜色。PNG 是左右两个有标题
的现状/规划 panel，HTML 用于交互式单层切换。

详见 [frontend-integration.md](frontend-integration.md) 和
[output-lineage.md](output-lineage.md)。
