# 2026-08-13 真实 LLM 全链迭代日志

> 本文记录 2026-08-13 真实 LLM 全链（L1→L3→TARGET_PROJECTION→GROUND→SELECT→EXECUTE→VALIDATE→RECONCILE→DELIVER）迭代过程。宿主进程持续写锁 `10_IMPLEMENTATION_STATUS.md`，因此最新状态同步到本文。

## 1. 本轮里程碑

- 06 EXECUTE 接入 Worker typed contracts + CAS 产物引用（parcel_changeset/planned_state/layout_configs/execution_diagnostics）。
- 03 IntentGraph 与 IntentCompiler 打通，作为 TARGET_PROJECTION 与 EXECUTE 的权威输入。
- 04/09 GROUND 引入 PlaceEvidenceIndex 与 `unresolved_reason` 输出，支持按空间引用定位。
- 12 地名解析覆盖 village/facility/road/water/area 等 L1 facts 实体类型。
- 09 road 输出根从 `F:\output` 改为 `run_tmp_root()/road`（不再越权写盘）。

## 2. 主要修复清单

| # | 修复 | 涉及文件 |
|---|---|---|
| 1 | 层 gate 残留：phase 为权威游标，Send payload 清除 `layer_just_completed`（after_analysis/aggregate 不再误判） | `workflow/conversation/edges.py`, `workflow/layers/layer_router.py`, `completion_node.py`, `layer_aggregate_node.py` |
| 2 | PlaceEvidenceIndex 绑定 water/road/area/facility L1 facts + bundle parcels + DLMC 关键词兜底 | `evidence/index/place_evidence_index.py` |
| 3 | resolve_spec 支持 12 类实体/方向/流域 + mention 正向子串匹配 | `spatial/grounding/resolver.py` |
| 4 | spec_mapper 从 `problem_addressed` 拆分位置/道路/水系/区域等，57 条 unresolved 归因到 spec | `data/ingestion/compiler/spec_mapper.py` |
| 5 | GROUND 输出 `unresolved_reason` 供 spec 追踪（06/12 复用） | `domain/ground/aggregate.py` |
| 6 | IntentGraph 与 IntentCompiler 接入 TARGET_PROJECTION | `workflow/stages/target_projection.py` |
| 7 | road_generator 输出根由 `parents[6]` 修正为 `PROJECT_ROOT`/`run_tmp_root()/road` | `domain/materialization/road_generator.py` |
| 8 | execute_node 返回完整 artifact refs（parcel_changeset/planned_state/layout_configs/execution_diagnostics 入 CAS） | `workflow/stages/execute.py` |
| 9 | 测试自动 approve 所有 HUMAN 断点：`while` + review 轮询 + 指纹/watchdog | `tests/acceptance/test_real_graph_resume_delivery_auto.py` |

## 3. 第四轮真实全链（2026-08-13 凌晨，首次通过）

- `test_real_graph_resume_delivery_auto.py::test_real_graph_resume_delivery`：**PYTEST_EXIT 0**。
- L1→L3→TARGET_PROJECTION→GROUND→SELECT→EXECUTE→VALIDATE→RECONCILE→DELIVER 全部走通。
- `delivery=partial`，render 11 层 PNG/HTML。
- GROUND unresolved 57 → 26（-54%），road T003-T008 开始有候选。

## 4. 视觉 MCP 检查（MiniMax-M3）

- 检查 `planning_preview.png`：渲染为现状+规划叠加，点位/项目面可见。
- 12 设施点 + 19 项目点成图；planned_road 为 0（road 全 defer）。

## 5. 遗留问题

1. **road 未落地**：5+ 个 road target 全 defer。
   - GROUND unresolved：T001/T002/T009/T010 等（村名/道路名无数据）。
   - SELECT `selection_no_candidate`：T003-T005 虽有 GROUND 候选但 SELECT/portfolio 未通过。
   - VALIDATE `validate_structural_failure`：T003-T005 因 EXECUTE 无 road worker 产出而失败。
   - road_generator Stage2.6 gate：unresolved/`connects=[]` 无端点 → bbox/anchor 不足以自动路由，
     `automatic_route_generation_allowed=false` → 不跑 stage4 → 无 planned_road。
   - 已修 `_to_road_target` 带 connects/width/road_level；真实 run 中 target 仍 `connects=[]`，
     需要从 L3 文本/现有道路参考提取端点，否则接受 defer。
2. **zone 未产出**：zone worker 0 条 changeset（详见 §11 根因链）。
3. 渲染质量问题：标题遮挡、无比例尺、道路无分级线宽、无标注、图例 13 色仅 3-4 主色显示。

## 6. 设计对齐（Bundle / portfolio / 分类）

### 6.1 几何必须来自 Bundle

- 02_DATA_PERSISTENCE：VillageBundle 是几何权威，GeoJSON 不进 State。
- 09：GROUND 的 BSM/source parcel → geometry 回查是硬契约（`available_geometry_wkt`），
  失败显式 `GEOMETRY_UNAVAILABLE`，禁止静默空 geometry。
- SELECT/worker 的 anchor 全部来自 bundle parcels；road 输出在 workspace/bundle 内，不越权写盘。

### 6.2 portfolio ready 语义

- `build_portfolio_decision` 的 `ready` 不能仅靠未满足项为空；solver INFEASIBLE 时
  SELECT gate HUMAN 让 zone/road 显式 defer。ready = 能被 EXECUTE worker（zone MIP /
  road planner / axis / facility）真正处理。
- line/action 目标不进 parcel portfolio；road 是 line 目标，不应进 parcel changeset。

### 6.3 LLM 自助分类生成器

- EXECUTE 对 polygon/parcel 目标 fail-closed：`classification_decision_required` 时
  HUMAN 必须提供附录5 闭集代码。
- 新增 `domain/program/classification_generator.py`：L3 aggregate 后对 polygon 目标用
  MiniMax with_structured_output（function calling）生成分类，含 rationale + evidence_refs。
- MiniMax 输出 `<think>` 可能导致 results 解析为 None：最多 3 次重试。
- LLM 全量失败时回退 category（不推断规划代码）；apply 后 0 unresolved，EXECUTE 不再 fail-closed。
- 验证：57/57 polygon 目标全部获得闭集代码。

### 6.4 第三次迭代验证

- delivery=partial、13 层渲染、deferral 75、traceability 119。
- parcel changeset 从 0 → 1 个 reclassify（后提升至 1-6 个）。
- GROUND unresolved 57 → 35（zone-ish 14、road 3）。

### 6.5 视觉 MCP 复核

- PNG 显示“地类变更 1 个”（第 3 轮）→ 14 设施点 + 20 项目点成图。
- 确认不再是“现状复制图”，而是现状+规划叠加。

### 6.6 剩余断点

1. **planned_road 空**：road target 全 defer（GROUND unresolved TRA-002/003/006 + SELECT/portfolio）。
2. **zone 34 全 defer**：GROUND unresolved zone-ish 14（CL-004/RES/SL 等）+ SELECT/portfolio。
3. 渲染质量项待优化。

## 7. 第三轮迭代（2026-08-13 续）

### 7.1 编码事故修复（重要）

- 发现：多次通过 PowerShell 管道向 Python 传递中文源码导致 **UTF-8 中文损坏为 `?`**，
  且已提交到 HEAD（compile.py 的 `_ROAD_LEVEL_KEYWORDS`、place_evidence_index 的
  `_WATER_DLMC/_ROAD_DLMC/_FACILITY_DLMC`、classification_generator 的 prompt、
  spec_mapper/resolver 的注释均损坏）。
- 修复：以 UTF-8 脚本文件 + Unicode 转义重写所有损坏行，恢复中文；统一 LF。
- 教训：此后所有含中文的 Python 修改一律使用 UTF-8 脚本文件（Set-Content -Encoding UTF8）
  而非管道内联。

### 7.2 resolver 增强

- `_normalize_spec_mention` 修复"12个自然村"→全村标记（原 `token[:-4].isdigit()` 判断 bug）。
- `_split_mentions`：组合位置（'乡道Y122沿线、县道X038沿线'）拆分为离散 mention 逐个解析合并 BSM。

### 7.3 真实全链验证（第 4 次通过）

- delivery=partial、13 渲染层、**parcel changeset 4 个 reclassify**（耕地→水域等真实变更）、
  19 项目点 + 18 设施点 + 4 项目面 + 37 定位点。
- GROUND unresolved 25（继续下降）。
- 视觉 MCP：变更成图、点位成图；仍无 planned_road；标题被绿色注释框遮挡、无比例尺。

### 7.4 剩余断点

- **zone 30+42 全 defer**：SELECT assignment 中 zone deferred reason 为空（测试 approve 的
  defer 路径覆盖），需查 `_record_target_deferrals`/apply_human_review_decision 对 zone 的
  deferred_target_ids 来源。
- **road 7-9 全 defer**：GROUND unresolved 部分 + SELECT defer。
- 渲染：标题遮挡、比例尺、道路分级。


## 8. 第四轮迭代（2026-08-13 续）

### 8.1 ledger 去重（阻断 defer 循环膨胀）

- 现象：`validate_structural_failure` 50 条、zone 61 条 ledger 条目（同一 target 重复
  defer：GROUND → SELECT → VALIDATE 循环累积），deferral_summary 虚高。
- 修复：`append_ledger` 按 target_id 去重（只保留首次）；`build_target_deferrals`
  输入内部去重。
- 效果：ledger 不再膨胀，VALIDATE 重复 defer 循环被阻断。

### 8.2 真实全链验证（第 5 次通过）

- `PYTEST_EXIT 0`；delivery=partial、13 渲染层。
- GROUND unresolved 稳定在 25-27（解析率提升自 57）。
- 点位/项目面持续成图；地类变更 1-4 个（L3 每轮产出不同）。

### 8.3 zone/road 剩余根因（下一轮专项）

- **zone 36-45 全 deferred**：site_selection 中 zone deferred reason 为空（SELECT→
  HUMAN defer 路径），plan_builder 对 ready zone 也未生成 parcel_transformation task
  （worker_tasks 无该类型）——需查 SELECT 对 zone 的 assignment 生成与 plan_builder 的
  zone 分支。
- **road 7-9 全 deferred**：GROUND unresolved（TRA 等）+ SELECT/plan 链路。
- fixture 无村级边界数据是部分 zone（村名定位）解析的数据限制。


## 9. 第五轮迭代（2026-08-13 续）

### 9.1 GraphInterrupt resume 契约修复

- 现象：VALIDATE 阶段 HUMAN approve 后，图 resume 立即进入下一个 HUMAN gate
  （validate approve -> deferral -> 再 HUMAN），LangGraph `astream` 抛 GraphInterrupt，
  `resume_from_interrupt` 未捕获 -> 提交接口 500 -> 测试失败。
- 修复：`resume_from_interrupt` 捕获 GraphInterrupt 并视为合法的"新 HUMAN 暂停"
  （final_state 反映新的 pending interrupt，调用方继续轮询 review 端点）。

### 9.2 composed 并行位置取并集

- 现象：zone spec（'北部、东北部、金田河沿岸、古驿道沿线'）用 op="and"（交集），
  方向 bbox 与实体 BSM 交集常空 -> unresolved。
- 修复：`spec_mapper` composed 默认 op="and" -> "or"（并列位置取并集）；
  resolver 后缀增加"流域"（'金田河流域' -> '金田河'）。

### 9.3 分类生成器 max_targets 修复

- 现象：pending 70 但 max_targets=60 截断，10 个 polygon 目标未分类 -> EXECUTE fail-closed。
- 修复：max_targets 60 -> 200，全量覆盖（70/70 验证通过）。

### 9.4 真实全链验证（第 6 次通过）

- `PYTEST_EXIT 0`；delivery=partial、deferral 79（从 106 下降）。
- 15 项目点 + 15 设施点 + 完整 planned_landuse。
- VALIDATE 多层 HUMAN（GraphInterrupt）现在可正常推进。

### 9.5 剩余断点（数据/解析限制）

- **zone 50 全 deferred**：GROUND 对村名/方向区域 zone 解析不足（fixture 无村级边界，
  KG cluster 无村名绑定）——需村界数据或 LLM 位置提取。
- **road 6 全 deferred**：GROUND unresolved + Stage2.6 端点确认门控。
- 渲染：标题遮挡、比例尺、道路分级。


## 10. 第六轮迭代（2026-08-13 续）

### 10.1 GROUND 解析持续提升（57 -> 9）

- 正向子串匹配：长 mention（'金田河沿线农业发展区'）包含实体名（'金田河'）也能匹配。
- DLMC 关键词兜底：mention 含村道/乡道/道路/河/林地/山体时，绑定对应 DLMC 地块组。
- 全村模式覆盖 '全村12个自然村'（原正则要求纯数字开头）。
- 效果：GROUND unresolved 57 -> 10 -> 9；parcel changes 0-6 个真实 reclassify。

### 10.2 真实全链验证（第 8 次通过）

- `PYTEST_EXIT 0`；delivery=partial、deferral 50。
- 真实地类变更 3 个；15-31 设施点、项目点持续成图。

### 10.3 zone 剩余根因（VALIDATE defer 循环）

- zone 30 全在 deferral_ledger（即使 GROUND 解析成功、分类 resolved）。
- SELECT 对 zone 兜底 ready（不检查 GROUND unresolved），但 ledger 已含 zone ->
  plan_builder 全放 deferred_tasks -> VALIDATE 对未执行目标报 structural failure ->
  测试 approve 再 defer -> 循环。
- 下一轮需查 VALIDATE pending 对 deferred_tasks 目标的包含路径（validate_checks
  traceability/coverage），确保已显式 deferral 的目标不再触发 failure。


## 11. zone 落地的完整根因链（第六轮追踪结论）

1. GROUND unresolved 9（村名类为主，如 营仔村）-> HUMAN defer（spatial_reference_unresolved）。
2. SELECT pending（unplaced/portfolio_unmet）-> HUMAN defer 6 个（selection_no_candidate）。
3. 其余 ~21 个 zone（解析成功）在 SELECT 阶段生成 parcel_transformation task。
4. EXECUTE 的 zone worker 对 25 个 zone **无任何产出**（execution_result 中 0 个 zone
   task_result）——zone worker 未生成 changeset。
5. VALIDATE 报 25 个 zone structural failure -> HUMAN approve 时 defer
   （validate_structural_failure 35 条）-> defer_plan_tasks 修订 plan ->
   最终 execution_plan 的 worker_tasks 无 parcel_transformation、deferred_tasks 30。
6. delivery=partial（zone/road 全 defer 属合法终态）。

下一轮专项：EXECUTE zone_worker 对 zone target 的 allocator 调用与产出（candidate_bsms
回填、PuLP allocator 输入），目标是让 zone 产出 changeset 进入 planned_landuse。


## 12. 第九轮迭代：GraphInterrupt 表象下的 SQLite 写锁根因修复

### 12.1 现象

- VALIDATE 第二次 HUMAN（`validation_retry_execute`，error_issue_count=2）submit_review 时
  `resume_from_interrupt` 抛异常，测试在 `test_real_graph_resume_delivery_auto.py:447` 失败。
- 第一眼误判为 `except GraphInterrupt` 没生效；实际异常链是：
  1. resume 后图推进到新 HUMAN gate，`await_human_review` 抛 GraphInterrupt（合法暂停）。
  2. pregel loop 在清理阶段持久化 interrupt checkpoint（`_checkpointer_put_after_previous` → `aput`）。
  3. 同一进程内业务引擎（SQLAlchemy）与 LangGraph checkpointer（裸 aiosqlite）在验收测试中
     共用同一 SQLite 文件，写事务冲突 → `sqlite3.OperationalError: database is locked`。
  4. 该 OperationalError 掩盖了 GraphInterrupt 并逃逸到 API → 500 → 测试失败。

### 12.2 修复

- `backend/app/database/engine.py`：
  - checkpointer 连接 `aiosqlite.connect(..., timeout=30)` + `PRAGMA busy_timeout=30000`。
  - SQLAlchemy 引擎连接 `PRAGMA busy_timeout=30000`（业务写等待而非立即失败）。
- `backend/app/infrastructure/runtime/planning_runtime_service.py`：
  - `resume_from_interrupt` 的 astream 循环增加一次性重试：仅对 “database is locked /
    database table is locked / sqlite_busy” 类瞬态错误重放同一 `Command(resume=...)`
    （锁失败意味着 checkpoint 未写入，重放安全且有界）；GraphInterrupt 仍视为合法新暂停。

### 12.3 依据

- 设计文档 02/09：pending interrupt 只能用对应 `Command(resume=...)` 恢复；
  resume 后再次 interrupt 是合法新 pause，不是失败。
- exa/网络检索：SQLite checkpoint 并发写推荐 `busy_timeout` 30s + 指数退避重试。
- 后续验证：重跑 `_run_acceptance.py` 确认 VALIDATE 多层 HUMAN 可连续推进直至 delivery。

## 13. 第十轮迭代：GROUND 地名增强 + zone/road 执行链解锁（2026-08-13）

### 13.1 现象与断点

1. **代码编码损坏**：`spec_mapper.py` 的 feature-name 后缀元组被 PowerShell
   中文编码破坏成 `"?"`，河流/道路后缀匹配完全失效；`place_evidence_index.py`
   第 144 行注释同样损坏。已全局扫描 `backend/app` 并修复。
2. **`_first_label` 解包 bug**：`graph.predicate_objects()` 返回二元组，原代码
   `for _, predicate, obj in ...` 每次抛 `ValueError` 并被 `except: return`
   吞掉 —— 这导致 **KG 实体名称从未进入 PlaceEvidenceIndex**（residential_cluster
   的注册也一直静默失败），是“KG 语义增强实体没有落实”的根因之一。
3. **GROUND 只注册自然村**：`_register_kg_names` 只处理 `residential_cluster`，
   Facility/Road/WaterBody/AdministrativeVillage/PlaceRef/Zone 都没有注册。
4. **deferral 自锁**：一旦 zone/road 被 HUMAN defer，`DeferralLedger` 永久保留，
   `plan_builder` 无条件放进 `deferred_tasks`，即使后续 GROUND/SELECT 已有解决
   证据也永不执行 → VALIDATE 反复 structural failure → 重复 defer 循环。
5. **road 无锚点**：`resolve_intent_anchors` 不处理 `road_targets`，connects
   （村北/村南）从不生成 start/end anchor，Stage 2.6 端点门控拒绝自动 route。
6. **GROUND 重复几何计算**：`_parcel_centroid` 为每个地块反复构造单元素
   GeoDataFrame，466 个地块 × 多个 POI 造成超长阻塞（曾被误判为 SQLite 死锁）。

### 13.2 修复

- **spec_mapper 精简 + 防假地名**：删除 40+ 硬编码后缀表，只保留自然村注册表
  与极少数安全后缀；`利/建/新` 等单字假地名不再产生；“村内道路/现状机耕路”
  等泛化词不会被当成地名（由 GROUND 证据索引 substring 匹配与 DLMC 兜底处理）。
- **GROUND flash-LLM mention 增强器**（`spatial/grounding/flash_mention_extractor.py`）：
  对 unresolved spec，用 flash 模型把原始散文拆成可定位地名列表（只输出文本，
  不产出 BSM/坐标）；结果按 sha256 内容缓存到 run 目录，resume/replay 不重复
  调用；模型不可用时回退确定性基线。
- **KG 多类型实体注册**：Facility/Road/WaterBody/AdministrativeVillage/
  ResidentialCluster/PlaceRef/Zone 全部注册，携带 BSM、WKT/POINT geometry、
  facility_type 别名、relation_refs；`relation_topology` 评分维度启用。
- **deferral 解锁**：`build_execution_plan` 对 ledger 中的 target，若本轮
  已有解决证据（candidate_bsms / selected_bsm / anchor / road 端点）则提升回
  `worker_tasks` 重新执行；无证据的仍保持 deferred。
- **road 锚点解析**：`resolve_intent_anchors` 增加 road 分支 —— 命名 connects
  解析 candidate_bsms，方位词 connects（村北/村南）用村中心 + 方向 bbox 生成
  start_anchor/end_anchor。
- **几何缓存**：`_parcel_centroid` 直连 Shapely；`build_parcel_centroid_cache`
  在 GROUND/PlaceEvidenceIndex 生命周期内共享，避免重复 GeoDataFrame 构造。

### 13.3 回归测试（54 passed）

新增：`test_spec_mapper_location_refs`、`test_flash_mention_extractor`、
`test_place_evidence_kg_types`、`test_plan_deferral_lift`、
`test_road_anchor_resolution`；连同几何缓存/selection cache/L1 契约等 54 项全过。

### 13.4 待验证（真实重跑）

- GROUND unresolved 是否下降（自然村以外实体能否解析）。
- zone 是否真正产出 parcel changeset 进入 planned_landuse。
- road 是否有 planned_road 图层与端点。
- 渲染 PNG 的道路连续性、分区差异、比例尺、点位重叠。

### 13.5 第二轮修复（2026-08-13 续）

1. **road 锚点链路补齐**：`resolve_intent_anchors` 此前在代码库中没有任何调用点，
   已在 `ground_node` 接入（gazetteer/KG anchor 解析后回写 target_projection
   artifact）。road 分支支持：命名 connects 解析 candidate_bsms、方位词
   connects（村北/村南）用村中心 + 方向 bbox 生成 start/end anchor。
2. **自然村→宅基地聚落映射**（`spatial/grounding/village_cluster_mapper.py`）：
   fixture 无村级边界（admin_boundary_line 的 BSM 与 landuse 不对应），KG 无
   12 自然村 ResidentialCluster；新增从 bundle DLBM=1340 宅基地 parcels 聚类的
   聚落识别，flash LLM 映射村名（带缓存、确定性回退），road/facility/zone 的
   村名 token 用 gazetteer 优先、聚落兜底。
3. **执行结果趋势**（第二轮真实 run）：polygon（zone/project）53 succeeded
   （较首轮 43 提升）、road 3 succeeded（较首轮 1 提升）、facility 32 succeeded。
4. **仍待解决**：road 无 connects 且语义无村名的 target（如“提质改造Y122乡道、
   各自然村”）端点缺失；VALIDATE 的 executor human_required（无 target_ids）
   会直接 END_DIAGNOSTIC，测试因此未达 RECONCILE/DELIVER。
