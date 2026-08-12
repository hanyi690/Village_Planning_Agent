# 真实 GIS checkpoint-resume 交付审计

日期：2026-08-11  
范围：`jintian` 真实 GIS 输入、SQLite checkpoint resume、DELIVER 空间快照、HTML/PNG/GeoJSON 输出。

## 验证记录

本文件保留的是 2026-08-11 历史运行证据。原 deterministic fixture-only E2E 已按重构计划删除，
不能再作为当前测试入口；当前复现入口是 `backend/scripts/resume_graph_checkpoint.py`，需要操作者
提供真实数据库、run root 和 session id。这里的“真实”限定为真实 `jintian` GIS 与真实 LangGraph
checkpoint，不等同于真实 LLM/L3 规划内容。

## 真实产出

正式保留产物目录：

`F:\project\Village_Planning_Agent\run-artifacts\latest-real-delivery`

- `render/planning_map.html`
- `render/planning_preview.png`
- `spatial_snapshot/planned/complete_planned_landuse.geojson`
- `checkpoint_trace.json`

GeoJSON 检查结果：现状 660 个 Feature，规划 660 个 Feature，其中 657 个 preserved、3 个 modified；规划 GeoJSON SHA-256：`7DA7006E93F3BEE5CDC124F46EE2188171C1199E4103A72B9C51C46B04EE935E`。

HTML 含 `jintian`、`current_landuse`、`complete_planned_landuse`、`planned_changes`、`planned_project`、`planned_project_point` 图层。双图 PNG 是本次 DELIVER 实际写出的正式文件：

`F:\project\Village_Planning_Agent\run-artifacts\latest-real-delivery\planning_preview.png`

左侧和右侧均来自同一真实 660 地块输入并按地类属性着色；右侧另有 3 个 EXECUTE 变更地块、1 个 `planned_project` 项目面和 1 个 `planned_project_point` 小型定位点。zone/facility 的 intervention_id 不再被误当作 project_ref。输出不是矩形或 P001/P002/P003 合成数据。

## checkpoint 证据

```json
[
  {
    "next": ["human_review_wait"],
    "interrupts_after_resume": []
  }
]
```

含义是：先在真实 SELECT 人审断点持久化 SQLite checkpoint，重新打开同一数据库后 resume，继续到 DELIVER 并成功生成输出；resume 后没有再次停在人工审查点。

## 设计反馈结论

- Agent 只消费 bundle/context 和阶段契约；真实 GIS 读取、索引、约束过滤、空间运算和交付快照构建均在 data/spatial 层完成。
- `DeliverySpatialSnapshot` 是 current/planned/render/export/land balance 的唯一交付输入。
- SELECT 已对无几何、不可建设地类和目标面积不足执行硬过滤；被排除候选进入淘汰原因，而不是由 EXECUTE 盲目补救。
- pytest 临时目录统一为 `backend/.pytest-tmp`，正式交付证据独立保存在 `run-artifacts/latest-real-delivery`，两者不嵌套。
- 本审计不宣称法定成果完整性；它证明真实数据链路、checkpoint resume 和交付产物的一致性。
