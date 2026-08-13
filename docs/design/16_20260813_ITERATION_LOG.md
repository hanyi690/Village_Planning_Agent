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

### 13.6 最新真实验收基线（session `7441d174-4155-466a-809c-6efbb6236061`）

- 真实验收运行 628.49 秒后失败；已完成 TARGET_PROJECTION、GROUND、SELECT、
  EXECUTE、VALIDATE，但缺少 RECONCILE、DELIVER。最终不是文件权限或 SQLite 锁，
  而是 VALIDATE 返回 `executor_human_required:unresolved`，HUMAN approve 后进入
  `END_DIAGNOSTIC`。
- L1 产出 57 facts、0 constraints；KG 有 25,068 triples、365 road intersects、
  1,708 touches，但 `gazetteer_combo_entries=0`，且同轮 KG 三次均 `cache_hit=False`。
- L3 产出 119 claims / 119 interventions，同时保留 38 个 severity=error 的
  `claim_set_diagnostic`，依赖关系和 evidence gaps 均为 0；现有 L3 Gate 对该错误码
  不阻断，错误规划程序仍进入 TARGET_PROJECTION。
- TARGET_PROJECTION 产出 58 project、41 zone、13 facility、2 axis、5 road；
  另有 93 spatial refs 和 45 diagnostics。5 条 road 的 width 均误取散文中第一个数字，
  将 16/8/5 km 的长度错误解释为 16/8/5 m 路宽；41 条 zone 的 `area_ha` 全为空。
- GROUND 的 village flash mapping 以 `'m-1'` 失败，本轮只回填 102 个 intent anchors；
  79 个候选中有 25 个直接包含全部 466 个现状地块，另有大量 31-125 地块的宽候选。
  候选置信度仅为 0/0.7/1 三档，14 个目标 unresolved。
- Suitability 只是将 grounding confidence 原样投影为 score；79 个候选全部
  hard-feasible。SELECT 的 `road_access`、`service_coverage` 固定为 0，未消费项目内
  DEM、坡度、路网可达性、设施服务、灾害成本等规划因素。
- SELECT 119 个 assignment：74 ready、32 placed、13 unplaced。41 zone 和 5 road
  被标为 ready 后交给 EXECUTE，未完成跨目标的全局空间冲突分配。
- EXECUTE 119 个 task result：94 succeeded、12 failed、13 deferred；其中 polygon
  succeeded 35、point succeeded 32、action succeeded 26、line succeeded 1。
  5 个 road 全部 `road_target_unresolved`；road worker 三轮均
  `stage generator skipped: None`。
- zone worker 对每个 zone 独立生成 parcel changes，merge 虽检测冲突仍无条件合并。
  最终 PlannedState 有 3,290 条 parcels，但只有 466 个唯一 BSM，重复 2,824 条；
  466 个 BSM 全部产生冲突分类。`zones=[]`、`roads=[]`，仅有 1 axis、8 facilities、
  24 project points；3,290 条 changeset 的 `project_ref` 全为空。
- EXECUTE review 连续三轮均为 467 violations。VALIDATE 最终失败项为硬约束、
  12,495 对 overlap 和 12 个 target traceability；continuity/accessibility 在没有
  planned road/zone 的情况下通过，属于空集合式通过，不能证明规划质量。

## 14. 规划生成逻辑审查结论（2026-08-13）

### 14.1 当前产物的真实性质

当前系统已不再只是“报告生成器”，也已能把部分项目/设施落为点、把部分目标送入
zone/road worker；但最新结果仍不是可用规划方案，而是：

```text
多维 LLM 项目清单
  → 宽松 Gate 放行错误/重复目标
  → 弱地名接地并静默扩大候选池
  → 置信度代替适宜性
  → 各 zone 独立重分类同一批地块
  → merge 保留冲突
  → VALIDATE 发现大规模重叠但没有可执行调整
  → HUMAN / END_DIAGNOSTIC
```

### 14.2 相比人类规划流程的主要缺口

1. 人类规划先形成统一的约束底图和评价因子，再综合需求、服务半径、交通和地形生成
   候选；当前 L1 constraints=0，DEM 仅摄取元数据，Suitability 没有实际评价模型。
2. 人类会把跨专题重复表述归并为一个项目，并建立前置依赖、规模和实施顺序；当前
   119 个 intervention 无 dependencies，同一道路/保护/修复事项可跨维度重复落地。
3. 人类分区需要全局唯一分配、功能层级和冲突消解；当前每个 zone 独立改写候选 BSM，
   同一地块可同时被改成多种地类。
4. 人类道路设计先区分现状道路提质与新建道路，再确定端点、走廊、等级、断面和
   地形成本；当前长度被误识别为路宽，端点为空，canonical generator 没有输入。
5. 人类会针对校验结果修改具体目标、排除具体地块或重建具体几何；当前 EXECUTE 三轮
   重跑没有消费新的调整，VALIDATE executor 主要生成 `relax` 元数据，无法消除 466 个
   BSM 冲突或补齐道路端点。

### 14.3 后续修复顺序与 resume 边界

1. **从 L3 修**：`claim_set_diagnostic` error 必须阻断；跨维度项目归并；补依赖、
   规模、单位与 output-kind 一致性。由于 PlanningProgram 本身错误，不能只从 EXECUTE
   resume；修复后应复用 L1/L2 artifact，从 L3 重跑。
2. **修 TARGET_PROJECTION**：道路长度/宽度结构化拆分，zone 面积从量化字段映射，
   禁止硬编码自然村名单；追加 unsupported diagnostics 后必须重算 Gate。
3. **修 GROUND fail-closed**：删除 zone/facility 的全村候选回退；解析失败保持 typed
   unresolved；修复 flash cluster mapping，并保证 candidate geometry/provenance 完整。
4. **实现真实 Suitability/SELECT**：接入 DEM 高程/坡度、灾害、基本农田/生态约束、
   现状路网可达性、设施服务覆盖和面积承载；跨所有目标做全局分配而非逐目标 ready。
5. **重构 zone materialization**：每个 BSM 最终只能有一个权威规划地类；保护区、
   功能区和用地分类分层表达；冲突不能一边诊断一边继续写入 PlannedState；补齐
   target/project lineage 和 PlannedZone。
6. **重建 road contract**：区分 existing-road upgrade 与 new corridor；先获得可审计
   端点/现状路段，再用 DEM/土地摩擦面或现状路网做路径计算；无输入时显式 unresolved。
7. **让调整真正被 worker 消费**：VALIDATE 的 overlap/hard-constraint/road-unresolved
   应生成目标级排除、重分配或重建参数；以 artifact checksum 计算最早失效阶段，
   仅重跑该阶段及下游。
8. **最后优化渲染**：只有 roads/zones/points 的权威几何稳定后，再补标签、比例尺、
   规划变更高亮、道路分级、图例一致性和避让。最新可用真实 PNG 的 MiniMax 审查仍为
   道路不可见、点位无标签、变更难辨、无比例尺；最新失败 session 因未到 DELIVER
   没有新 PNG，不能用旧图冒充最新成果。

## 15. 第十一轮迭代：所有规划对象的源头语义编译（2026-08-13）

### 15.1 边界纠正

真实产物暴露的 `16 km → width_m=16` 不是一个正则精度问题，而是阶段责任倒置：
L3 Claim 只保存通用 `quantity/scale/statement`，专业参数在 Claim→Proposal 时丢失，
TARGET_PROJECTION 被迫重新解释自然语言。修订后的边界为：

```text
L3 专题 LLM（严格 JSON）
  → Provider Draft（原始量值 + 原始单位）
  → 确定性 Semantic Compiler（单位换算 + 闭集 + 范围校验）
  → PlanningClaim v2（类型化对象语义）
  → Proposal → Intervention（原样传递）
  → 跨专题 Program Critic（只做去重/依赖）
  → TARGET_PROJECTION（纯字段映射）
  → GROUND（Bundle/KG/DEM 空间证据）
```

TARGET_PROJECTION 不再提取文本中的“第一个数字”，也不再从硬编码自然村名单猜道路
连接对象。缺少源头结构时输出 typed error 并定向返回 L3。

### 15.2 统一对象语义契约

新增共享 `planning_semantics.py`，并把以下参数贯通
`PlanningClaimDraft → PlanningClaim → ProgramProposal → PlanningIntervention`：

- **道路**：action、road_level、length、roadbed_width、pavement_width、
  alignment_refs、connects；Draft 保留 m/km，Normalizer 统一为米并校验路基宽不小于
  路面宽、宽度 1–30m、长度大于 30m。
- **设施**：facility_type、action（保留/新建/扩建/迁建/修复）、service_radius、
  capacity/capacity_unit、footprint_area；距离转米、占地转平方米。
- **发展轴/廊道**：action、axis_type、direction、reference_features、connects、
  corridor_width；不得退化为普通道路。
- **土地分区/保护/修复/项目范围**：materialization_role 闭集为
  `land_use_assignment / protection_overlay / restoration_overlay /
  project_footprint`。保护和修复角色由类别契约确定，不依赖后置模型猜测；真正土地
  用途配置必须提供面积范围并统一为公顷。
- **一般项目**：project_type、action、capacity、footprint_area；point 项目继续保留
  location_hints，非空间管理措施保持 action，不进入几何流程。
- **自定义分区**：仍使用独立 CustomZoneTarget + 指定 BSM/规则契约，不与普通 L3
  zone 混同。

### 15.3 局部 LLM 自修复与 Resume

- L3 每个专题首次生成即按 ClaimDraftSet v2 function schema 输出；temperature 调整为
  0.1。
- Semantic Compiler 返回对象级错误，只把当前专题完整 ClaimSet 连同确定性反馈交给
  同一低成本模型重修，默认最多 2 次；不会因为一条道路宽度错误重跑 L1/L2 或其他
  11 个 L3 专题。
- `PlanningClaimSet.schema_version` 升为 2.0；旧 v1 artifact 在 aggregate 产生
  `legacy_claim_schema_requires_recompile`，禁止复用缺少类型化语义的旧产物。
- 聚合后的 LLM 已缩减为 Program Critic：只可从确定性候选对中选择跨专题重复项并
  补充无环依赖，不得 patch 道路/设施/分区字段、不得降级源头 error；有源头 error 时
  Critic 完全不调用，直接返回对应 L3 dimension。
- Program Critic 按完整 prompt hash 原子缓存到 session run 目录；MiniMax 将嵌套数组
  序列化为 JSON 字符串时，仅在 provider boundary 解码，内部契约不放宽。

### 15.4 Gate 与投影

- L3 Gate 现在阻断所有仍为 severity=error 的 ProgramIssue，而不是仅阻断错误码白名单。
- 历史自由文本 diagnostic 迁移时只有“provider returned no structured claim set”等实质
  缺失视为 error；说明性生成备注为 audit，已完成的归一化为 warning，避免假错误和真
  错误同时漏检。
- TARGET_PROJECTION 为 road/facility/axis/zone/空间 project 分别检查源头语义；错误
  diagnostic 使 Gate fail-closed 并返回 L3。保护/修复投影为项目 overlay，不再进入
  ZoneTarget 土地重分类。
- GROUND 富化后的 target_projection ref 通过统一
  `stage_completion_patch(output_refs=...)` 传递，移除节点内手工重写 root
  `artifact_refs` 的架构例外。

### 15.5 验证状态

- 新增源头编译、错误反馈、对象跨边界传递、Critic 权限边界、缓存、纯投影和 Gate
  测试。
- 集中 pytest：`196 passed`；所有 basetemp 位于 `backend/.run-tmp/pytest/`，未产生
  分散 `.pytest_cache`。
- 已启动真实 session `e36b7d66-c830-4c61-9232-703f3dec3a8f`，实时日志为
  `backend/.run-tmp/logs/real-llm-live.log`；因 Claim schema 已发生源头变化，本轮必须从
  L3 重新生成，不能仅从 TARGET_PROJECTION/EXECUTE resume。后续需用 step report
  验证每类项目的类型参数覆盖率、道路端点/现状路段输入、分区唯一分配、DEM 适宜性和
  最终渲染。

### 15.6 真实 L3 运行暴露的恢复断点与修复

session `e36b7d66-c830-4c61-9232-703f3dec3a8f` 的真实日志进一步证明：问题不只在
规划参数，还在并发恢复语义。

- 12 个 L3 专题以 provider semaphore=3 执行；旧实现把 300 秒总超时包在整个
  ClaimSet 生成与全量重修外层，排队时间也计入 provider timeout。`landscape` 完成后，
  其余 10 个专题几乎同时超时/熔断。
- 并发 worker 的 `fatal_error/provider_failures/dimension_retry_counts` 原本没有进入
  compact `WorkflowState` reducer channel，恢复只能看到“层未完成”，看不到完整失败
  维度集合。
- HUMAN 默认继续后，`after_analysis` 将 10 个“未完成”专题再次当作“尚未派发”，
  在约 1 秒内重复 fan-out，最终 `GraphRecursionError`。提高 recursion limit 只会增加
  重复 LLM 调用，不能修复状态机。

修复后的恢复协议：

1. provider timeout 只包围实际 `ainvoke`，不包含 semaphore 排队；源头语义修复只发送
   validator 拒绝的 claim，不再重发已通过的整套 ClaimSet。
2. 初始生成和每轮局部修复均按“完整 prompt + validator feedback + schema version”
   做 sha256 内容缓存，先原子落盘再进入下游编译；同 session checkpoint resume 命中
   cache，不重复消耗模型。
3. 三类 provider 失败信息成为 compact root state 的一等 reducer channel；并行失败
   不再被 runtime adapter 丢弃。
4. HUMAN 的 accept/approve/retry 对基础设施失败统一解释为“恢复所有且仅恢复失败
   dimension”；写入一次性 `provider_resume_dimensions`，由独立 Command 节点消费并
   `Send` 精确 fan-out。它不是业务修订，不设置 `is_revision`，也不会重跑已完成专题。
5. 每个 dimension 的恢复预算有界；超过预算进入 diagnostic artifact，而不是再次
   HUMAN/dispatch 循环。

本轮集中回归更新为 `201 passed`，新增 compact failure channel、精确 resume dispatch、
预算耗尽和局部 claim replacement 测试。

### 15.7 Exa / Context7 对照结论

- Exa 检索到的 GeoContra 将任务契约、静态/运行时/语义验证和 violation-guided bounded
  repair 分成显式对象；这支持当前“LLM 只生成候选、确定性 GIS 契约验收、只修失败项”
  的边界，而不支持在 TARGET_PROJECTION 用自由文本第一个数字补字段。
- Schema-guided extraction 案例强调 schema-first、provenance、validator-guided minimal
  repair，并明确 repair 是 schema-invalid 输出的 fallback，不是替代源头约束的常规
  后处理；因此本轮把道路/设施/轴线/分区/项目参数前移到 ClaimDraft v2。
- Context7 的 LangGraph 1.0.8 文档确认 `Command(update=..., goto=Send[])` 可在同一原子
  控制步骤中消费恢复状态并动态 fan-out；interrupt 所在节点 resume 时会从头执行，
  所有外部副作用必须幂等或缓存。
- Context7 的 Rasterio 文档确认 DEM 可通过 CRS/transform/nodata 检查、windowed read
  和 sample 接入。当前项目只有 DEM 文件与摄取元数据，尚未形成坡度/高程适宜性，
  下一轮应在 SELECT 前建立可缓存的 terrain evidence，而不是让 LLM 猜地形。

## 16. 第十二轮迭代：Road Contract 与候选准备侧线（2026-08-13）

### 16.1 真实实现与日志断点

本轮先回看 `06_TARGET_PROJECTION_EXECUTE.md`、`09_INTEGRATION_BREAKPOINTS.md`、
`12_PLACE_NAME_RESOLUTION.md`、本日志第 13–15 节以及真实运行日志，再审查
`RoadTarget → Stage 2.6 → Stage 3 → Stage 4/RoadGenerator`。结论如下：

1. session `7441d174-4155-466a-809c-6efbb6236061` 的 5 个 road target 全部
   `road_target_unresolved`，最终 `roads=[]`；该真实结果仍是最近一次到达 EXECUTE 的
   road 基线。后续 session `e36b7d66-c830-4c61-9232-703f3dec3a8f` 在 L3 provider
   恢复处中断，没有产生新的 road execution 结果，不能把旧 PNG/旧道路数当作新成果。
2. 原 `RoadTarget` 把 `new/upgrade/widen/harden/repair` 放在同一扁平结构中，却没有规定
   不同 action 的空间证据义务。`candidate_bsms/path_bsms/bbox` 只能说明附近地块，不能
   证明“要改哪条现状路、哪几个路段”。
3. `_road_targets_to_stage2()` 在没有端点时仍创建 `${target_id}-start/end` demand；
   `connects` 的自由文本名称、方向代理坐标和有来源的精确端点被写入同一数据形状。这会
   把“没有输入”伪装成“有两个 demand、等待 Stage 2.6 解析”。
4. Stage 4 `_candidate_requests()` 只有 `action == new` 才创建完整的 text road request；
   upgrade/repair/harden 没有“绑定现状 edge 后执行 segment operation”的独立分支，可能
   退化成普通端点接入或根本不产生 request。
5. Stage 1 虽生成确定性的 `E000001...` edge id，但当前 network builder 没有保留原始
   road feature id 到 edge 的 lineage；fixture 的 131 条 current road 又只有
   `Shape_Length`，没有道路名称。因而“Y122 提质”在现有数据链中无法自动证明对应哪段
   真实现状道路。
6. `terrain_router.py` 和 Stage 4 已有 DEM、坡度、土地成本、环境约束与 least-cost path
   实现，但 `RoadGenerator` 当前构造 `RoadPlanningConfig` 时没有传 `dem_grid_path`，
   所以项目内 DEM 并未进入真实 road 生成，仍走 `geometric_corridor_family`。

### 16.2 新增 typed road planning input

新增 `contracts/domain/road_planning.py`，把可执行道路输入拆为判别联合：

- `ExistingRoadPlanningInput`：只允许 upgrade/widen/harden/repair；必须绑定经过当前路网
  catalog 验证的 `existing_road_feature_ids` 或 `existing_road_segment_ids`，并携带带
  checksum 的 current-network artifact。没有 road id 时不能用村域、候选 BSM 或文本
  `alignment_refs` 替代。
- `NewCorridorPlanningInput`：只允许 new；必须有两个互异、resolved、带 CRS、source
  artifact、source feature/entity 和 evidence refs 的端点；必须至少有 current network、
  DEM 或 land-friction 中的一类版本化路由证据。
- `RoadRoutingEvidence`：独立表达 current network、DEM、land friction、hazard 和 spatial
  constraints，并校验 artifact role 与字段一致。
- `RoadCandidatePreparationResult`：只有 `ready` 或 typed `unresolved`；unresolved 时
  `planning_input=None`，禁止下游悄悄产生全村/随机/代理候选。

`RoadTarget` 已追加 `road_planning_kind`、现状 feature/segment ids、端点实体引用、完整
端点 evidence、routing evidence 等字段；TARGET_PROJECTION 仅根据源头 typed action
确定 `new_corridor` 或 `existing_road_intervention`，不从散文重新猜测。

### 16.3 独立 fail-closed candidate preparation

新增 `spatial/network/road_candidate_preparation.py`。其输入为 RoadTarget 与当前 session
的 `RoadEvidenceCatalog`，输出 typed batch：

- existing 类检查 road id 是否真实存在于权威 current-road feature/Stage1 segment 集；
- new 类只接受完整 endpoint evidence，或从 catalog 中按合法 entity ref 取得完整 evidence；
- 单独的 `connects=[地点名称]`、方向生成的 `start_anchor/end_anchor`、candidate BSM、bbox、
  path BSM 均不会升级为可执行端点；
- 无证据输出稳定 diagnostic code，例如 `ROAD_EXISTING_BINDING_MISSING`、
  `ROAD_EXISTING_SEGMENT_NOT_FOUND`、`ROAD_ENDPOINT_PROVENANCE_MISSING`、
  `ROAD_ROUTING_EVIDENCE_MISSING`；
- batch 只收集真正 ready 的 inputs，不为 unresolved target 补默认候选。

该模块通过 `spatial.network` lazy export 暴露，但本轮**没有把它硬塞进旧
RoadGenerator/Stage 2.6**。原因是旧链路仍把所有 action 转成 demand/endpoints；直接调用
会出现“一边新合同 fail-closed，一边旧适配器继续造伪端点”的双重语义。应按下节顺序
接入，而不是在 generator 内加一层 if。

### 16.4 Exa 案例对照

- [新建农村道路选线研究](https://civil.pcampus.edu.np/journal/index.php/njce/article/view/2.1-6)
  明确以两个 obligatory points 为 origin/destination，先用技术、环境因素形成 friction
  surface，再生成并比较 least-cost paths。这支持“端点证据完整后才生成 new corridor”。
- [现状农村道路升级方法](https://link.springer.com/article/10.1007/s41062-016-0041-8)
  先从 GIS road database 和实测路况中识别需要升级/养护的具体 links，再按设施可达性
  和 link weight 排序。这支持“existing action 必须绑定真实 road feature/segment”，而
  不是重新画一条起终点线。
- [农村道路多模式可达性优化](https://link.springer.com/article/10.1007/s11116-022-10343-3)
  使用地形、土地覆盖、水系、现状道路和道路规格形成 travel-time/friction surface，并
  比较道路组合的服务可达性收益。这说明候选生成与后续全局 SELECT 都应消费同一组可
  审计空间成本，而不是让 LLM 或 grounding confidence 代替。

### 16.5 验证与下一接入边界

- 新增 8 个 road contract/candidate preparation 测试，覆盖 existing 缺 id、未知 segment、
  verified segment、new 伪端点、完整端点、entity catalog、缺路由证据和 batch 无回退。
- 定向回归：`14 passed`。
- Road 侧线完成时 core 集中回归为 `234 passed`；并行侧线合并后的最终复跑为
  `250 passed`，basetemp 为 `backend/.run-tmp/pytest/road-contract-final`；`compileall`
  通过；当前环境未安装 ruff，因而未声称 ruff 已验证。
- 真实 fixture smoke：用 `mvp_village/gis/road.geojson` 的 131 个现状 road features
  重建 Stage1，得到 176 个稳定 edge；以真实 `E000001` 和 edges artifact 的 SHA-256
  调用 candidate preparation，结果为 `ready/existing_road_intervention`；输入不存在的
  `E999999` 稳定返回 `unresolved + ROAD_EXISTING_SEGMENT_NOT_FOUND`。产物集中在
  `backend/.run-tmp/road-contract-smoke-6c87f0a2/`。

推荐接入顺序：

1. 在 Data/BOOTSTRAP 或 GROUND 前置生成带 source-feature lineage 的 current-road network
   artifact；每个 Stage1 edge 保留源 feature id/geometry checksum。
2. GROUND 对 existing action 把 `alignment_refs` 解析为真实 feature/segment ids；对 new
   action 把 connects 解析为两个 `RoadEndpointEvidence`。ambiguous/unresolved 保持原状态，
   禁止方向 bbox 自动升级为 confirmed。
3. 在进入 Stage 2.6 前调用 `prepare_road_candidates()`；其 unresolved diagnostics 进入
   GROUND/road gate。只有 `NewCorridorPlanningInput` 进入端点—路径生成；
   `ExistingRoadPlanningInput` 进入独立 segment-operation materializer。
4. 新建路径把 routing evidence 中的 DEM、land friction、hazard 和 constraints 显式映射
   到 `RoadPlanningConfig`，删除无 DEM 时的生产级 geometric family fallback；可以保留
   fallback 仅作测试/预览并明确标记非权威。
5. resume 边界按最早失效 artifact 决定：action/kind 错误回 L3；地点/road-id 绑定错误从
   GROUND 重跑；成本面变化从 candidate preparation/Stage4 重跑；不得为 road 断点重跑
   已有效的 L1/L2。

## 17. VALIDATE 调整消费与 Resume 失效边界侧线（2026-08-13）

### 17.1 实现前审查

- `ValidationReport.checks` 已有 `affected_target_ids` 与 `affected_parcels`，但旧
  `BoundedAdjustmentExecutor._candidate_from_check` 把两者合并到
  `affected_target_refs`，丢失“目标”和“地块”不同语义。
- 旧 executor 对 hard constraint、overlap、road unresolved 等所有失败统一写
  `bounded_params.adjustment_type="relax"`；这只产生了重试元数据，没有目标级排除、
  重分配、证据补齐或几何重建输入，和真实 session 中三轮 EXECUTE 结果不变一致。
- 文档 09 要求用 artifact 父版本/checksum 计算最早失效阶段；文档 13 要求复用
  ValidationReport/adjustment/artifact 体系且 fail-closed。因此本侧线不改 workflow
  路由和 worker，只补“finding → typed directive → impact plan”的纯函数边界。

### 17.2 新增闭集契约与编译规则

- 新增 `RepairDirective`，只允许四类：
  - `exclude_bsms`：硬约束命中，必须有 target ID 和明确 BSM；回到 SELECT。
  - `reallocate`：跨目标 overlap/worker conflict，必须有每个 target 与冲突 BSM；
    回到 SELECT 做全局重分配。
  - `rebuild_geometry`：topology/continuity/area materialization 错误，必须有 BSM 或
    已存在几何 evidence ref；回到 EXECUTE。
  - `require_source_evidence`：`road_unresolved` 先回 TARGET_PROJECTION 补道路模式、
    端点或现状路段契约；`road_anchor_unresolved/geometry_unavailable` 回 GROUND 补
    有 provenance 的目标级空间证据。
- 每条 directive 绑定 `target_id`、source violation ID、source artifact key/digest、
  affected BSM/evidence 与 sha256 issue fingerprint。契约没有任意
  `adjustment_type` 字段，`relax` 无法通过模型校验。
- 编译是 all-or-nothing：任一 violation 未绑定 target、需要 BSM 却缺 BSM、code
  不受支持或 source ref 非法，结果为 `blocked` 且不返回可执行 directives，避免只修
  容易的子集后继续写 PlannedState。

### 17.3 Artifact impact analysis

- `analyze_repair_impact(compilation, artifact_refs)` 先由 directive 类型得到候选边界，
  再核对源 violation checksum、重放所需上游 anchor 与递归 parent digest 链。
- 若 EXECUTE repair 的 `site_selection` 父 checksum 已变化，边界自动前移 SELECT；
  若 GROUND anchor 缺失则前移 TARGET_PROJECTION；若 `planning_program` 不存在或 L3
  以前的 lineage 无法验证，则整个 post-L3 resume `blocked`。
- 输出包含 `earliest_invalid_stage`、完整 `rerun_stages`、可复用/失效 artifact keys、
  target/directive IDs、输入 checksum 快照和 integrity issues；模块不调用 graph、
  不改 state，也不直接执行 worker。

### 17.4 验证与当前集成状态

- 新增 14 个测试，覆盖 hard constraint、overlap、road source/anchor unresolved、
  topology、无 BSM 但有道路 geometry evidence、未知/无 target finding、source checksum
  变化、parent checksum 变化和 L3 anchor 缺失。
- 侧线定向回归 `33 passed`；完整 `backend/tests/core` 为 `240 passed`，pytest
  basetemp 均集中在 `backend/.run-tmp/pytest/`。
- 当前状态是 **typed compiler/impact analyzer 已实现，workflow/worker 尚未接线**。
  后续集成应由 VALIDATE 调用 compiler，把 directives 写入现有 adjustment 输入，再按
  impact plan 选择历史 checkpoint；SELECT/EXECUTE worker 必须实际消费对应目标级字段
  后，才能将这一项从 PARTIAL 标为 CURRENT。
- 本节实现时 finding 生产端仍缺三处必要 lineage：`check_hard_constraints` 只返回 BSM、不返回
  target ID；`check_overlap` 只返回 pair count、不返回重叠对的 target/BSM；road worker
  的兜底 `road_unresolved` 没有 target ID。因此接入新 compiler 后这些真实问题会正确
  `blocked`，不会假装修复；这些 producer 缺口已在下述第 18 节继续修复。

## 18. VALIDATE Producer Lineage 主线接线（2026-08-13）

### 18.1 Hard constraint finding

- `ValidationCheck` 增加 `violation_id/code/evidence_refs`，保留原 `check_id` 作为检查类别。
- 硬约束不再把所有违规 BSM 聚合成一个无目标 finding；现在按
  `target + BSM + constraint_type` 产生独立 finding，目标来源只读取
  `PlannedParcel.derived_from_zone_target / project_ref`，不从名称或文本猜测。
- 每条 finding 携带 `planned-parcel:{BSM}`、`constraint:{type}` 与确定性
  `constraint-overlap:{digest}` evidence ref，可直接编译为目标级 `exclude_bsms`。
- 约束索引缺失和几何查询失败分别保持 `constraint_index_unavailable`、
  `hard_constraint_query_failed`，不伪装成可安全排除的 hard-constraint 命中。

### 18.2 Overlap finding

- overlap 只比较同一权威层内部的 polygon；不再把 parcel 与聚合 zone 的语义包含关系
  当成自重叠。
- 每个唯一重叠对输出独立 finding，包含具体 target pair、BSM pair、左右 feature
  evidence ref 和由 intersection WKB 计算的 overlap evidence ref；不再只有 pair count。
- 有完整 parcel lineage 的重叠可直接编译为每目标一条 `reallocate`；PlannedZone 当前
  没有 source BSM 字段，因此纯 zone overlap 仍按 `missing_bsm_lineage` fail-closed。

### 18.3 Road unresolved finding

- road worker 对所有未产出 geometry 的声明目标生成一条 target-bound finding，并按
  typed target/evidence 状态确定性区分：
  - `source_contract_missing` → `road_unresolved` → TARGET_PROJECTION；
  - `anchor_missing` → `road_anchor_unresolved` → GROUND；
  - `route_failed` → `road_route_failed` → EXECUTE。
- 分类不解析错误消息：existing-road 必须有现状 feature/segment 与 current-network
  evidence；new corridor 必须有两个 resolved endpoint 与 network/DEM/friction routing
  basis。只有这些输入完备而没有路线时才允许标记 `route_failed`。
- provider/stage generator 的原 diagnostics、diagnostic codes 与 evidence refs 保留，
  但无 target 的上游诊断只绑定到实际未产出的声明目标，不产生全局 road fallback。

### 18.4 Legacy adjustment 与验证

- `build_validation_report` 不再生成 `ConstraintAdjustment(adjustment_type="relax")`；
  `adjustments` 保持空列表，后续只允许 typed directive compiler 产生自动调整输入。
- 新增 6 个 producer-lineage 测试；validation/road/directive 定向回归 `38 passed`。
- 排除共享工作区中独立的 custom-zone 失败后，core scoped 回归 `282 passed`；完整 core
  为 `290 passed / 4 failed`，失败均位于既有 `test_custom_zone_changeset.py`，和本次
  validation/road 写集无依赖。隔离复跑该文件为 `10 passed / 3 failed`，未越界修改。

### 18.5 仍会阻断 directive compilation 的 finding

- `constraint_index_unavailable`、`hard_constraint_query_failed`：有意不支持自动排除；
  必须恢复约束证据或几何查询。
- `area_conservation`、`topology_validity/topology_gaps`、`continuity`：当前 producer
  仍缺 target/BSM/evidence 的完整组合。
- `accessibility`、`parcels_present`、`parcel_fields`、`changeset_flags`、`traceability`：
  尚未定义闭集 directive policy；不得自动重跑。
- `classification_missing` 虽已有 policy，但当前 finding 只返回 BSM、未返回对应 target。
- 纯 `PlannedZone` overlap 有 target 但无 source BSM；`road_target_identity_missing` 表示
  worker 被错误派发且没有声明 road target，两者都保持 fail-closed。

## 18. 全局 Zone 地块分配侧线（2026-08-13）

### 18.1 现有实现审查

`spatial/allocation/zone_allocator_adapter.py` 已有 PuLP/CBC 全局模型和
`ZoneAllocatorPort`，但旧契约只有 `targets: dict[str, float]`、任意类型候选和字符串
diagnostics。目标函数仅最大化不超过目标值的总分配面积，缺少 typed suitability、
逐目标缺口/超额、候选冲突、约束 provenance 和 target→candidate→parcel lineage。
此外，现有 zone worker 对没有 `candidate_bsms` 的目标会构造“未被其他目标占用的
全村 parcel pool”，与 06/09 的 GROUND/SELECT fail-closed 约束冲突。本侧线不修改该
worker，只提供后续替换所需的独立 canonical contracts 和 allocator。

### 18.2 新增独立契约与求解器

- `contracts/spatial/global_zone_allocation_contracts.py` 定义：
  `ZoneParcelFact`、`ParcelConstraint`、`ZoneParcelCandidate`、
  `ZoneCandidateSet`、`GlobalZoneAllocationProblem`、
  `AuthoritativeZoneParcelAssignment`、`ZoneAreaBalance`、结构化 diagnostic 和
  `GlobalZoneAllocationResult`。
- `spatial/allocation/global_zone_parcel_allocator.py` 复用现有 PuLP/CBC adapter 模式，
  但把所有 typed `ZoneTarget` 和 target-bound suitability candidates 放入一次全局
  求解。输入顺序统一排序、CBC 单线程并指定随机种子，使相同 artifact 可重放。
- 每个 BSM 有全局 `sum(x[target,bsm]) <= 1` 约束；结果契约再次验证 BSM 唯一性，
  防止后续误合并产生两个权威 `land_use_assignment`。
- 面积目标使用 shortfall/excess 显式变量；目标函数依次高惩罚缺口、惩罚超额、奖励
  suitability，并用稳定次序做最终 tie-break。每个 zone 输出请求面积、已分配面积、
  缺口、超额、容差和完成比例，不再用单个 `feasible` 掩盖局部失败。
- 分类未 resolved、面积缺失、candidate set 缺失、候选不属于 GROUND 输出、parcel
  facts/geometry/provenance 缺失、candidate hard-infeasible 或 parcel 约束阻断时均
  fail-closed；禁止扩大到全村候选池。
- 每项 assignment 带 deterministic lineage id、target/zone、instruction/report、
  claim refs、分类证据、适宜性证据、Bundle parcel/geometry ref 和考虑过的约束代码。
  几何本身仍由 VillageBundle 持有，不复制进 allocator artifact。
- `protection_overlay`、`restoration_overlay` 使用独立 pass-through contract；可以与
  land-use assignment 覆盖同一 BSM，但不进入排他 MIP，也不能出现在权威 assignments。
  这落实“用地分类、保护/修复 overlay 分层表达”，不按名称猜测角色。

### 18.3 当前验证与主线边界

- 新增 9 个测试，覆盖跨目标冲突消解、BSM 唯一性、面积缺口、target-specific 硬约束、
  overlay 非排他、完整 lineage、输入乱序重放、缺 parcel facts、未决分类、局部不可行
  和禁止全池回退。
- 相关 zone/custom-zone/SELECT 定向回归 `24 passed`；完整 core 回归
  `234 passed`。pytest basetemp 全部位于 `backend/.run-tmp/pytest/`。
- 本侧线按约束未修改 `select_service.py`、`land_design_worker.py`、`merge.py` 或
  `root_graph.py`，也尚未替换现有 zone worker，因此不能宣称真实 session 的 zone
  渲染已经改善；需由主线按下节集成后重跑真实 flow、step report 和最新 PNG。

### 18.4 后续主线集成点

1. **Suitability→Problem adapter**：在 SELECT 获得 DEM/坡度、灾害、基本农田/生态、
   路网可达性和面积承载后，为每个 ZoneTarget 形成 `ZoneCandidateSet`；从 Bundle
   形成 `ZoneParcelFact`，不得用空候选全村回退。
2. **全局 SELECT/EXECUTE 边界**：一次调用
   `DeterministicGlobalZoneParcelAllocator.allocate(problem)`，把 result 作为独立 CAS
   artifact；不得在每个 target 的 worker 内重复求解。
3. **Gate**：`MODEL_INVALID/INFEASIBLE/SOLVER_*` 阻断；`PARTIAL` 根据每个
   `ZoneAreaBalance` 生成目标级重选/排除指令。只有 `OPTIMAL` 或经规则允许的明确
   partial 才进入 materialization。
4. **Materialization**：只消费 `AuthoritativeZoneParcelAssignment` 生成 parcel change；
   overlay 走独立图层。写 PlannedState 前按 BSM 再校验唯一性，并把 assignment lineage
   传入 PlannedParcel/PlannedZone。
5. **VALIDATE/Resume**：面积缺口、约束阻断或冲突应回到 Suitability/全局分配阶段，
   由 artifact checksum 使该阶段及下游失效；分类/面积源头错误则回 TARGET_PROJECTION
   或 L3，不应从 EXECUTE 盲目重跑。

## 19. DEM 地形证据与 Terrain Suitability 侧线（2026-08-13）

### 19.1 设计与现状边界复核

- 依据 00/06，DEM 属于 SELECT 的候选证据，不属于 LLM 推断、GROUND 候选扩张或
  EXECUTE 几何兜底；地形模块只能测量候选，不能自行选择 BSM/坐标。
- `SpatialWorkspace.rasters.dem` 已有正式数据槽位，`DataCatalog` 也登记了 `dem`
  layer source；但默认 session Bundle 为保证离线可重放只隐式加载本地矢量，因此实现
  不能假设 DEM 必然已进入 workspace。
- 新模块采用明确的来源优先级：当前 `PlanningContext.workspace.rasters.dem` → 调用方
  注入的 Catalog `dem` source → 受 `allowed_roots` 约束的显式路径。没有硬编码村名、
  fixture 路径或绝对盘符；显式路径未给允许根目录时直接拒绝。
- 本侧线未修改 `workflow/stages/select.py`、`select_service.py` 或
  `workflow/root_graph.py`，也不把 terrain score 偷塞进现有 grounding confidence。

### 19.2 新增确定性证据契约与实现

- `contracts/spatial/terrain_evidence.py` 定义不含 raster array 的可持久化契约：
  `TerrainRasterMetadata`、`TerrainEvidence`、`TerrainStatistics`、
  `TerrainPointSampleSet`、`TerrainEvidenceProvenance`、
  `TerrainSuitabilityPolicy/Assessment`。
- `spatial/terrain/evidence.py` 使用 Rasterio window + geometry mask 读取 parcel、point、
  line 或 candidate geometry 所覆盖的有限像元；另提供 Rasterio `sample()` 点采样接口。
  读取前检查 CRS、transform 可逆性、像元轴正交性、bounds、band、nodata 和尺寸；
  invalid/outside/oversized/no-valid-cell 均返回 typed 状态，不扩张候选、不读取整幅 DEM。
- 坡度按 `atan(sqrt((dz/dx)^2+(dz/dy)^2))` 输出 degree。投影 CRS 使用轴单位换算为米；
  地理 CRS 使用窗口中心的椭球测地像元向量换算水平距离，禁止把经纬度直接当米。
  算法名、水平像元米尺度、CRS、transform、nodata、window、geometry/source SHA-256
  和 band 均写入 provenance。
- cache key 绑定 DEM 文件 SHA-256、subject lineage、规范化 geometry digest、geometry
  CRS 与技术配置；结果按 key 单文件原子写入调用方指定目录。读取时再次校验 cache key
  与 source checksum，cache hit 不改变 evidence id。模块不创建散落的默认缓存目录。
- `domain/suitability/terrain.py` 只消费上述证据并应用调用方显式传入的 policy；坡度软/
  硬阈值、最小有效率、可选高程范围和最大高差均不在 raster engine 中写死。证据无效
  返回 `unknown + hard_feasible=false`，超过硬阈值返回 `unsuitable`。

### 19.3 真实 DEM 与地块验证

- Catalog 解析的真实项目 DEM：EPSG:4326、3601×3601、Int16、1 arc-second、无显式
  nodata，文件 SHA-256 为
  `8adc723acdd5fb03bbd4bb08478b958de48c67c7263bd4ed1495874dc7a416e3`。
  `nodata_not_declared` 作为审计 diagnostic 保留，但 Rasterio dataset mask 与 finite check
  仍逐像元控制有效性，不因此伪造 nodata 值。
- 真实 Catalog Bundle 显式加载 `landuse_current + dem` 后得到 660 个现状地块。对真实
  BSM `441426211000049104` 通过 PlanningContext 路径执行 window 分析，读取窗口仅
  5×4 像元；地块内高程 421–425m、平均 423m，坡度约 4.14–6.29°，水平像元尺度约
  28.08m×30.77m，结果为 `ready`，source/geometry/window/checksum lineage 完整。
  这是模块 smoke 结果，不代表该地块已被 SELECT 选中。

### 19.4 测试与主线集成接口

- 新增 `backend/tests/core/test_terrain_evidence.py` 共 10 个测试，覆盖 projected plane
  坡度、window statistics、nodata、缺 CRS fail-closed、raster 外 geometry、窗口上限、
  Rasterio point sample、缓存/subject lineage、显式路径安全、PlanningContext 优先级、
  policy 适宜性和真实 Catalog DEM。
- 定向回归：terrain + suitability/data boundary 共 `15 passed`；DeprecationWarning 作为
  error 运行仍通过；`compileall` 通过。pytest basetemp 位于
  `backend/.run-tmp/pytest/terrain-contract-regression`。
- 后续主线应在 GROUND 已产生 target-bound candidate geometry 后，为每个 candidate 调用
  `TerrainEvidenceService.analyze_geometry(...)`，把 evidence ref 和
  `assess_terrain_suitability(...)` 结果并入统一 Suitability candidate features，再与灾害、
  基本农田/生态、路网可达性、服务覆盖和面积承载一起进入全局分配。任何
  `invalid_raster/outside_raster/no_valid_cells` 必须保留为不可用证据，不能退回 grounding
  confidence 或全村候选池。
