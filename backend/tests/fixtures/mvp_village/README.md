# MVP 金田村固定回放夹具

本目录是村庄规划 Agent 的 MVP 验收固定回放夹具（"fixed replay fixture"），
对应 `docs/design/10_IMPLEMENTATION_STATUS_CURRENT_20260818.md` 的当前可验证边界及
MVP 场景（现状报告 + GIS → L1Snapshot → L2Strategy → PlanningProgram →
IntentCompilationResult → GroundingResult → SiteSelectionDecision →
ExecutionPlan → Project/Zone/Facility/Road Workers → ParcelChangeSet →
PlannedState → ValidationReport → ReconciliationReport → DeliveryManifest）。

## 职责边界

- 仅提供"输入数据"，不包含任何预期输出；验收断言由各测试自行构造。
- 数据为**副本**（Copy-Item），非符号链接，保证 Windows 环境下稳定可读。
- 夹具目录保持只读语义：测试不应修改其中的文件。

## 数据来源

- `gis/`：10 个 GeoJSON，复制自
  `data/gis/jintian/current/`（泗水镇金田村现状 GIS 数据）：
  - `admin_boundary_line.geojson`：561 条行政界线（MultiLineString）
  - `annotation.geojson`：34 个注记点（Point，含"注记/分类"属性）
  - `boundary.geojson`：1 个村庄范围多边形（MultiPolygon）
  - `construction_zone.geojson`：139 个村庄建设用地地块（MultiPolygon）
  - `ecological_protection.geojson`：5 个生态保护地块（MultiPolygon）
  - `farmland_protection.geojson`：88 个基本农田保护地块（MultiPolygon）
  - `geological_hazard_points.geojson`：40 个地质灾害隐患点（Point）
  - `historical_protection.geojson`：3 个历史文化保护范围（MultiPolygon）
  - `landuse.geojson`：660 个现状用地地块（MultiPolygon，含 DLBM/DLMC 地类）
  - `road.geojson`：131 条现状道路（MultiLineString）
- `current_report.md`：现状报告，复制自
  `docs/MinerU_markdown_泗水镇金田村现状报告_2056637054755487744.md`。

## 用途

- MVP 纵向链 smoke/type 级验收：验证夹具可读、typed artifacts 可导入、
  后 L3 链构建函数可导入。
- 为后续端到端验收提供**固定、可复现**的输入基线（数据变更不影响断言）。

## 已知限制

- 均为静态快照：上游 `data/gis/jintian/current/` 或报告更新后需手动重新复制。
- 未做坐标参考系（CRS）与拓扑检查；使用前由测试按需解析。
- 不包含预期产物，也不包含 LLM/DB/链运行所需的环境假设。
