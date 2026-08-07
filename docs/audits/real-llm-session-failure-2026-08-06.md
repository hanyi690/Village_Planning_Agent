# Real LLM Session 验收结果：失败断点

## 结论

本次确实启动了真实 FastAPI lifespan、真实 SQLite、真实 Session、真实报告上传、全部 10 个 GIS GeoJSON 上传和真实规划图初始化；但没有到达 LLM 调用，也没有生成 DELIVER 图层。

因此不能称为“真实 LLM 全链路已跑通”。

## Session

- Session ID：`396cf062-9743-4cbc-9097-fe35136c1399`
- LLM 配置：仓库 `.env` 的 OpenAI-compatible DashScope / `qwen3.7-plus`
- 真实输入：`current_report.md` + 10 个 GIS GeoJSON
- FastAPI lifespan：通过
- LangGraph graph 初始化：通过
- Session 创建：通过
- 文件写入 SQLite：通过
- LLM 调用：未到达
- PARSE：未到达
- DELIVER/render layers：未产生

## 首个断点

断点位于：

`Session 上传 → DataCatalog bundle ingest → admin_area / pandas-geopandas 处理`

日志证据：

- `current_annotation`：34 features ingested，warnings 0
- `boundary`：1 feature ingested
- 多个约束图层成功 merge
- `current_road`：131 features ingested
- `landuse_current`：660 parcels ingested，15 个 DLBM codes
- `admin_area`：0 features ingested，warnings 561
- 随后 Windows fatal exception：`access violation`
- 线程栈落在 `pandas.core.dtypes.base.__hash__` / `pandas.core.internals.blocks.new_block`，调用链经过 `planning_context` / `session_kg` / GIS geometry processing

## 为什么没有渲染结果

没有执行到 `DELIVER`，所以这次真实 LLM Session 没有合法的 `RenderLayers` artifact，也没有新的 GeoJSON/PNG 输出。

之前的 `real-session-stage-report-sample.md` 是确定性 adapter 回归样例，不是本次真实 LLM 运行结果；其中的 `function_zone` 是 fake execute 输入派生的单个 Polygon，不能作为真实 LLM 规划结果。

## 下一修复目标

1. 先隔离并修复 `admin_area` ingest 的 561 warnings。
2. 对 `session_kg.ensure_session_kg` 的 geopandas/pandas 数据转换增加小批量、类型稳定和单线程边界。
3. 重新运行本文件对应的真实 LLM Session 测试。
4. 只有真实运行到 DELIVER 并生成 `RenderLayers` 后，才更新为真实 LLM PASS 报告。

## 第二次真实运行（2026-08-06 20:38）

- Session ID：`4ecea00e-ab8b-4259-aced-84ea2f1a2c5f`
- 修复已验证：660 parcels、131 roads、34 annotations、1 boundary 成功加载；
  `compute_parcel_relations` 生成 1691 touches、6048 nearby、416 connected、365 road-intersects。
- 真实 LLM 已实际调用：L1 的 12 个维度均完成，单次响应约 60–116 秒；L2 已开始并完成
  `resource_endowment`、`planning_positioning`。
- 运行在 300 秒 pytest 硬超时处终止，尚未到达 DELIVER，因此仍不能声明真实全链路 PASS。
- 首个剩余停滞点是远程 LLM TLS/HTTP 请求耗时，而不是 GIS 原生崩溃；pytest 输出了完整线程栈并强制退出。

已提交的修复：

1. `admin_boundary_line.geojson` 先于宽泛 `boundary` 规则识别，避免线要素按 `admin_area` 面模型解析。
2. 真实上传按文件名补齐 `construction_zone`、`farmland_protection`、`ecological_protection`、
   `historical_protection`、`geological_hazard_points` 类型。
3. 道路连通长度计算移除重复 Polygon union，改为两个不重叠地块的交叠长度之和，避免 Windows GEOS 崩溃/停滞。
4. 真实 LLM 集成测试超时从 300 秒提高到 900 秒；仍受 pytest-timeout 硬退出保护。

## 第三次真实运行（2026-08-07，session `e77b4e69-aa94-43bb-b758-1c9b77fe5d6d`）

- 配置中的真实 LLM 完成 L1（12/12）、L2（4/4，L1Snapshot facts 已作为显式输入且 gate PASS）和 L3（12/12，gate PASS）。
- L1Snapshot 实际保存 2 条 session-KG facts、15 个 source refs；L2 StepReport 记录 `l1_fact_count=2` 和同一 snapshot ref，KG → L1 → L2 链路已被真实审计。
- 首次 post-L3 PARSE 暴露 `TypeError: cannot unpack non-iterable NoneType object`：远程模型返回了不可解析的 patch path，`parse/merge_node.py` 未对 `_resolve_parent(...) is None` 做 fail-closed 处理。
- 已修复 UPDATE/ADD/REMOVE 三条路径：非法 patch 现在记录 `SCHEMA_MISMATCH` 诊断，不再让后台任务崩溃。
- 本次运行在修复前的 PARSE 断点停止，因此没有伪造 RenderLayers。下一次真实运行需要验证 PARSE→GROUND→SELECT→EXECUTE→VALIDATE→RECONCILE→DELIVER 并落盘渲染产物。
## 2026-08-07 rerun: L2 EXPLORE exhaustion checkpoint

- Session `3a737df0-0338-4179-ab04-d9f2dd580ef7` used the real report and all
  uploaded GIS layers with the configured LLM.
- L1 completed `PASS` with `fact_count=8` and `kg_fact_count=2`.
- L2 produced a usable artifact but remained on `EXPLORE`; one dimension
  returned a very short response and the business retry budget was exhausted.
- The first routing defect was that an existing `HUMAN` gate returned `END`
  instead of entering the persisted HITL nodes. This is fixed in
  `conversation_router/edges.py`; subsequent exhaustion now creates review
  items and an interrupt checkpoint rather than silently stopping.
- No rendering claim is made for this run because it stopped before PARSE.

## 2026-08-07 final19 rerun: canonical gazetteer fixed, L2 gate semantics exposed

- Session `7189f0e9-4311-4b57-bcf5-35d04a52ef04` used the real
  `current_report.md` and all fixture GeoJSON layers. L1 completed with the
  literal `【INSTRUCTION】` contract preserved and the canonical `金田村`
  gazetteer alias written.
- L2 completed all four dimensions and produced a typed `L2Strategy`, but the
  model emitted one narrative `EvidenceGap` with an empty `required_fact`.
  The old gate treated that prose as an actionable EXPLORE request and routed
  to HUMAN after two retries. The gate now ignores such non-actionable prose
  while retaining explicitly missing facts as EXPLORE requests.
- This run stopped before PARSE, so it is not a Delivery PASS and has no valid
  RenderLayers claim. The next live run must be executed with the configured
  provider credentials after this gate fix.

## P1 test isolation

The core and live-session tests now change into pytest's unique `tmp_path`
before invoking the application. Relative `.run-tmp` artifacts therefore
cannot collide with a previous `s1` run. CI explicitly collects the live
integration test; it skips only in GitHub Actions when no provider key is
configured, instead of omitting the integration path.
