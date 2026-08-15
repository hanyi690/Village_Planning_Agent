# Wave Roadmap — 后续波次 B-M（项目驱动式规划管线逐模块完善）

> Wave A 已交付：advisory_crosswalks 隔离、22 个契约文件、6 个 ports、ArtifactStore + 审查包协议。
> 每个波次完成后生成审查包（summary.md + artifact.json + trace.json + preview.geojson）并进入 awaiting_review，
> 通过后才切换下一波次；旧路径在对应新模块通过后原子删除。

## 全局验收条件（每波次通用）
- 默认测试不依赖网络、外部服务或 gitignored 数据并全部通过
- 架构不变式无 modules → agent/services、spatial → kg、kg → data 反向依赖
- 活动规划链对跨体系映射符号扫描为零（advisory_crosswalks 隔离区已建立）
- 每个模块能单独运行、重放并生成标准审查包

| 波次 | 模块 | 关键变更 | 审查包内容 | 消除的已知问题 |
|---|---|---|---|---|
| B | L1 OBSERVE | 保留 12 维并行 `AnalysisReport(content + instruction + provenance)`；每个 worker 完成后用共享 compiler core 的 `L1_OBSERVATION` profile 并行生成 `L1DimensionFragment`；唯一的确定性 `l1_aggregate` 合并为 `L1Snapshot` 并执行 G1 Evidence Gate；现状分类仅为 `ClassificationRef` 事实 | 12 份原报告、12 份 fragment、事实/证据/约束/问题/证据缺口、aggregate trace、GateDecision | legacy summary 被误当作结构化事实 |
| C | EXPLORE | 删除候选地块/BBox 决策/intent 写入；只返回 EvidenceBundle | 请求、证据、来源、置信度、未解决项 | - |
| D | L2 STRATEGIZE | 独立策略子图 + 一致性 Gate；输出 L2Strategy；不生成坐标/候选/分区 | 目标—问题—策略—证据矩阵、策略冲突 | - |
| E | L3 PLAN | 从"先列分区面积"改为生成 PlanningProgram；项目需求/用地需求/实施计划子图 | 项目表、土地需求表、项目依赖图、遗漏项 | - |
| F | PARSE | 复用 Wave B 建立的共享 compiler core，以 `L3_PLANNING` profile 实现独立顶层 Intent Compiler 子图；Hybrid PARSE 三模式（COMPILE/REPAIR/REVISE）：确定性抽取优先，LLM 只产出结构化 CompilationPatch，确定性合并 + 复验；缺失规划内容回传 L3，低置信度/大改写走人工审查；编译为 IntentCompilationResult + SpatialReferenceSpec，不再建立第二套解析器 | 源字段→结构化字段逐项对应、编译诊断、补丁清单、profile trace | PARSE 双轨和重复解释 |
| A.1 | PARSE 契约 + 文档 | PARSE 顶层阶段契约落地：ParseMode/CompilationStatus/PatchOperation/CompilationPatch/ParseDiagnostic/ParseTrace/ParseRevisionRequest；IntentCompilationResult 升级为根 artifact（保留 intent/compilation_errors 兼容字段）；agent-graph.md + roadmap 记录 Hybrid PARSE 设计 | 契约定义、单测、架构文档 | - |
| G | GROUND | 注入 Gazetteer/SemanticQuery/SpatialQuery ports 消除对 KG 反向依赖；生成 CandidateSite | 候选区域 GeoJSON、候选地块组合、约束覆盖、未解析原因 | spatial_ops→kg 反向依赖 |
| H | SELECT | 硬约束过滤 + 多因子评分 + 冲突分配；输出 SiteSelectionDecision；删除"第一个可用候选"逻辑 | 完整排名、淘汰理由、最终组合、地图预览 | - |
| I | EXECUTE | Land Design Worker 生成项目轮廓 + ParcelChangeSet；其他 Worker 只消费决定；删除现状驱动 ZoneGenerator/MIP 正式路径 | PlannedState、操作日志、面积守恒、地块谱系、前后对比图 | 8 个 EXECUTE 链 advisory_crosswalks 违规 |
| J | VALIDATE | 独立 Gate；校验硬约束/面积/拓扑/重叠/连续性/可达性/契约完整性/规划分类缺失；按责任阶段标记 | ValidationReport、责任阶段归属 | - |
| K | RECONCILE | PlanningIntervention→SpatialReferenceSpec→CandidateSite→SiteSelectionDecision→ParcelChangeSet→PlannedState 覆盖矩阵 | 覆盖矩阵、不一致清单 | - |
| L | DELIVER | 仅 Validate+Reconcile 通过的版本可导出；DeliveryManifest；缺规划分类时阻止"完整法定成果" | 交付清单、溯源、未决人工项 | - |
| M | BOOTSTRAP 集成 | 目标主图替换六节点图；State 只留阶段/Gate/context/artifact 引用/issues/human_review；Graphify 依赖图 | 主图拓扑、阶段状态机、依赖图 | kg→data 反向依赖 |

## 依赖顺序
B → C（EXPLORE 横向服务，可并行于 B/D/E）→ D → E → F → G → H → I → J → K → L → M。
G 需要 C 的证据契约；H 需要 G 的 GroundingResult；I 需要 H 的 SiteSelectionDecision + LandDesignBrief。

## Wave B 追加验收条件

- 12 个 L1 维度保持现有并行调度；不新增 12 个顶层 aggregate 节点。
- 原报告正文、`【INSTRUCTION】`、ReportStore、SSE 和 L2/L3 报告共享行为不变。
- 每个维度完成后立即生成一份可单独审查、带 provenance 和 compilation trace 的
  `L1DimensionFragment`。
- `l1_aggregate` 只消费 fragment，执行确定性合并、冲突检查和证据缺口归并；不得调用 LLM，
  不得重新解析 12 份报告正文。
- `DimensionReport.summary` 明确为 legacy/non-authoritative；EXPLORE `report_summary_index`
  明确为独立规则索引，两者均不能替代 typed artifact。
- G1 Evidence Gate 只消费 `L1Snapshot` 和显式 evidence gaps，返回 PASS / EXPLORE / HUMAN。

## 关键约束（源自主 spec §2/§3）
- 现状地类只提供：分类代码与名称（ClassificationRef）、几何/面积/权属、利用状态/转换成本/适宜性、与道路/设施/居民点/控制线的关系。禁止从现状 DLBM 自动推出规划用途/规划分区/三生空间/项目位置。
- 规划分区改为后置综合结果（由 L2 空间结构 + 已选项目 + 规划地块 + 控制线 + 非建设性干预生成）。
- 受控地块重构：项目轮廓可跨多个现状地块；split_ratio 只能作为面积提示，实际切割由项目轮廓/切割线/约束几何执行；源地块面积守恒、几何有效、无未说明重叠；记录 derived_from_bsms 谱系。
- 跨体系映射保留在 advisory_crosswalks 隔离区，默认禁用、不提供给 LLM；L2/L3/PARSE/GROUND/SELECT/EXECUTE 禁止导入。
- 未明确规划分类的未调整地块使用 preserve，不自动伪造规划编码。

## Wave A 交付物（已完成）
- schema/advisory_crosswalks/（隔离区 + 19 YAML + 静态扫描测试）
- schema/contracts/ 22 个契约文件（输入/输出/控制全覆盖）+ 6 个 ports
- services/artifact_store.py + services/review_package.py（.run-tmp/{run_id}/{module}/）
- 13 个阶段 I/O 契约覆盖：Bootstrap/Router/L1/Explore/L2/L3/PARSE/GROUND/SELECT/EXECUTE/VALIDATE/RECONCILE/DELIVER

## 波次交付说明
> Wave B 已交付：共享 compiler core + `L1_OBSERVATION` profile + `L1DimensionFragment` +
> 确定性 `l1_aggregate`（→`L1Snapshot`）+ G1 Evidence Gate + L1 审查包；8 commits（035f81aa→006c9850）。
> 主图接线属 Wave M。状态：awaiting_review。

> Wave C 已交付：`retrieve_evidence()` 统一证据服务 + `ExplorationRequest` 富化 +
> `SpatialCognitionEvidence` + `render_evidence_prompt_section`；8 commits（7c88eb98→20cf29b0）。
> 状态：awaiting_review。

> Wave D 已交付：共享基础设施提取至 `app/agent/common/dimension_runtime.py`；`L2Strategy` 富化 +
> `L2_STRATEGY` profile + `analyze_l2_dimension` worker + `l2_aggregate` + G2 Gate + L2 审查包 +
> 护栏；9 commits（7d916156→fe0ad94d）。主图接线属 Wave M。状态：awaiting_review。

> Wave E 已交付：`PlanningProgram` 富化 + `L3ProgramFragment` + `L3_PLANNING` profile +
> `analyze_l3_dimension` worker（分层依赖 L1→analysis_report/L2→planning_concept）+
> `load_layered_dependency_reports` + `l3_aggregate` + G3 Gate + L3 审查包 + 护栏；9 commits
> （b392d519→b3afbeba）。主图接线属 Wave M。状态：awaiting_review。

> Wave F 已交付：独立顶层 `app/agent/parse/` PARSE 子图（`compile_program` 消费 `PlanningProgram`
> 产出 `IntentCompilationResult + SpatialReferenceSpec`）；REVISION compiler profile 实现（确定性补丁应用）；
> Hybrid 三模式骨架（COMPILE 确定性抽取优先 + REPAIR/REVISE 路由 + `apply_patches` 确定性合并复验 +
> `evaluate_parse_gate` 4 路由 PASS/REPAIR/REVISE/HUMAN）；确定性 `spec_mapper`（directional/attributive/
> topological/composed，无 LLM）；`provenance` 通用化（source_module）；PARSE 审查包；护栏测试
> （不导入 legacy `parse_agent` / 不导入 advisory_crosswalks）。legacy `parse_agent.py` 桥接层共存；
> 主图接线属 Wave M。状态：awaiting_review。

> Wave G 已交付：扩展 `GazetteerPort`/`SpatialQueryPort`（`resolve`/`resolve_candidates`）+ kg 侧
> adapters（`app/modules/kg/adapters/`）；消除 3 处 spatial_ops→kg 违规导入（架构不变式 5→4 失败）；
> 独立 `app/agent/ground/` GROUND 子图（`ground_aggregate` 消费 `SpatialReferenceSpec[]` 产出
> `GroundingResult` + `CandidateSite[]`；`evaluate_ground_gate` 3 路由 PASS/EXPLORE/HUMAN；审查包 8 节）；
> PlanningContext 工厂接线 ports；护栏测试。主图接线属 Wave M。状态：awaiting_review。

> Wave H 已交付：独立 `app/agent/select_graph/` SELECT 子图（`select_aggregate` 消费
> `GroundingResult + SpatialPlanningIntent` 产出 `SiteSelectionDecision + LandDesignBrief`，复用
> `spatial_ops/selection.py`：硬约束过滤含最小面积 + 多因子评分 + priority-sequential 冲突分配；
> `evaluate_select_gate` 3 路由 PASS/RETRY_GROUND/HUMAN；审查包 8 节 + 地图预览）；最小面积硬过滤 +
> `_PROHIBITED_CONSTRAINTS` 三处合并；`_execute_project_node` 重写为消费 `SiteSelectionDecision`
> （遗留首选候选逻辑保留为回退路径，Wave M 删除）；护栏测试。主图接线属 Wave M。状态：awaiting_review。

> Wave I 已交付：`app/agent/execute/land_design_worker.py`（项目/分区/设施 parcel 变更 → `ParcelChangeSet`，
> 复用 `parcel_ops.py` 的 reclassify/merge/split/create + `derived_from_bsms` 谱系）+ `planned_state_builder.py`
> （`ParcelChangeSet → PlannedState`）+ EXECUTE 审查包（操作日志/面积守恒/地块谱系/前后对比图）；`_execute_project_node`
> 产出 Polygon 项目轮廓（删除首选候选逻辑）；`_execute_layout_node` 确定性 zone reclassify（无 MIP，删 2 处
> `MIPZoneAllocator.solve`）；`_execute_facility_node` 决策驱动（无 KG POI 查找）；`_write_l4_node` 消费
> `ParcelChangeSet`；原子删除 8 个 EXECUTE 链 advisory_crosswalks 违规文件（`mip_allocator`/`mip_solver`/
> `planning_zone_mapper`/`zone_generator`/`land_use_zone_generator`/`space_control_generator`/`zone_type_deriver`/
> `generate.py`，violation budget 11→3）+ 修复 3 处调用点（`_execute_axis_node` 改用 `AxisBuilder`、
> `pipeline.py` 确定性化、`gis_test_routes.py` 优雅降级）；护栏测试。主图接线属 Wave M。状态：awaiting_review。

> Wave J 已交付：独立 `app/agent/validate/` VALIDATE 子图——`checks.py` 8 类确定性检查
> （硬约束/面积守恒/拓扑/重叠/连续性/可达性/契约完整性/规划分类缺失）含 `responsible_stage` 归因；
> `validate_aggregate` 产出 typed `ValidationReport`（`issues_by_stage` 按阶段分组）；`evaluate_validate_gate`
> 5-way 责任路由（PASS/RETRY_EXECUTE/SELECT/GROUND/L3/HUMAN，按 error issue 主导阶段）；VALIDATE 审查包 8 节；
> `_validate_node` 重写为消费 VALIDATE 子图（`state.validation_report`，删除 `LayoutValidator` 与 3-round
> silent fallthrough，改 human 终止）；修复 stale `test_execute_custom_zoning`（pre-existing 失败 4→3）；
> 原子删除最后 3 个 advisory_crosswalks 违规文件（`layout_validator`/`compare_layouts`/`dynamic_zoning`，
> violation budget **3→0**，全局"活动规划链对跨体系映射符号扫描为零"达成）+ 修复 4 处调用点
> （`validate.py`/`gis_test_routes.py`×2 改接 `validate_aggregate`、`pipeline.py` 三路对比优雅降级、
> `_analytics/__init__.py` 移除 re-export）；护栏测试。主图接线属 Wave M。状态：awaiting_review。

> Wave K 已交付：独立 `app/agent/reconcile/` RECONCILE 子图——`reconciliation_contracts.py` 富化
> （typed `CoverageMatrixRow` 对齐 `TraceabilityEntry` + `ReconciliationInconsistency.responsible_stage`）；
> `checks.py` 6 类链覆盖检查（干预→spec→候选→选择→变更→planned，按 BSM 线索 +
> `ProjectTarget.project_id`==intervention_id + positional alignment 重建链）+ 定量偏差（面积 vs 文本）；
> `reconcile_aggregate` 产出 `ReconciliationReport`（`CoverageMatrix` 按 covered/partial/missing + 不一致清单）；
> `evaluate_reconcile_gate` 4-way 路由（PASS/RETRY_L3/RETRY_EXECUTE/HUMAN，PARSE/GROUND/SELECT 主导→HUMAN）；
> RECONCILE 审查包 8 节（覆盖矩阵摘要/链覆盖详情/不一致清单/面积偏差/阶段归因/向后谱系/Gate 决定/来源追溯）；
> 吸收 `_build_l3_l4_consistency_report`（L3 targets→PlannedState 覆盖，`check_l3_l4_target_coverage`，
> 删除 execute_agent 遗留 dict helper，`state.reconciliation_report` 字段已加）；护栏测试。主图接线属 Wave M。
> 状态：awaiting_review。

> Wave L 已交付：独立 `app/agent/deliver/` DELIVER 子图——`delivery_manifest_contracts.py` 富化
> （`DeliveryManifest.statutory_complete` + `statutory_complete_breakdown`）；`checks.py` 3 类确定性检查
> （法定图层齐全/溯源完整/规划分类缺失，返回 `list[HumanItem]`）；`deliver_aggregate` 消费
> `PlannedState + ValidationReport + ReconciliationReport + 上游 Gate + export_result` 产出 typed
> `DeliveryManifest`（`traceability` 从 `CoverageMatrixRow` 机械映射填充（Wave K→L 桥），`deliverables`
> 从 export 包映射，`pending_human_items` 从检查 + 上游 HUMAN 门收集，`delivery_gate` 复用
> `spatial_ops/land_balance.check_delivery_gate` 不吸收）；`evaluate_deliver_gate` 3-way 路由
> （PASS/RETRY_VALIDATE（主导阻塞为 `classification_missing` 可修复）/HUMAN（导出失败/上游未决/并列））；
> `statutory_complete` = delivery_gate.passed AND 无 blocking 人工项 AND 规划分类完整，阻断缺规划分类时的
> "完整法定成果"（08_DELIVERABLES_COMPLIANCE.md §3）；DELIVER 审查包 8 节（交付清单/溯源谱系/出口门槛/
> 未决人工项/规划分类缺失/法定成果完整性/Gate 决定/来源追溯）；`ExecuteAgentState.delivery_manifest` 字段已加；
> 护栏测试。主图接线属 Wave M。状态：awaiting_review。

> Wave M1 已交付（BOOTSTRAP 集成 第一段——post-L3 链）：`app/agent/bootstrap/` 新增
> `post_l3_state.py`（`PostL3ChainState` typed artifact 引用链状态）+ `post_l3_nodes.py`
> （parse/ground/select/execute/validate/reconcile/deliver 7 节点，各包装对应 `*_aggregate` + gate）+
> `post_l3_chain.py`（`build_post_l3_chain` 图工厂，PASS 线性、非 PASS 记日志终止）；`gis_agent_node`
> 重写为消费 post-L3 链（替代 `layout_pipeline` 单体）；`StepReport.VALID_STAGES` 新增
> GROUND/SELECT/VALIDATE/RECONCILE/DELIVER；**`layout_pipeline.py`（1165 行）已删除**，`_build_trace_layer`
> 迁移至 `map_layers.build_trace_layer`；**`kg→data` 反向依赖消除**（`ports/bundle_assembly.py` +
> `data/bundle_assembly_adapter.py` + `PlanningPorts.bundle_assembly` 注入，`test_architecture_invariants`
> 全 8 通过）；修复 2 个 catalog_session_context 预存在失败（`upload_roads` 回退合并 + stale test stub）；
> AgentState conservative 新增 `delivery_manifest`/`reconciliation_report_ref`/`validation_report_ref`/
> `pending_requests`/`context_version`（遗留 `gis_*` 字段弃用不删）；护栏测试。**0 个预存在失败**
> （1247 passed）。遗留 `parse_agent.py` 桥接层保留（4 测试文件 + explore/agent + vocab_extractor +
> gis_test_routes 仍消费，Wave M2 再删）。主图拓扑仍为 6 节点（仅 `gis_agent_node` 内部替换）。
> 状态：awaiting_review。


> Wave M2 已交付（BOOTSTRAP 集成 第二段--L1/L2/L3 aggregate 接线 + 门控重试 + 遗留清理）：
> - layer_aggregate_node 新增（completion_check -> layer_aggregate -> after_analysis）；L1/L2/L3 aggregate 在层完成后自动调用
> - fter_analysis 门控感知路由（PASS/EXPLORE/L1/L2/L3/HUMAN）
> - etrieve_evidence_for_gate EXPLORE 横向服务（门控驱动证据检索）
> - PostL3ChainState 重试字段（retry_counts/max_retries/explore_cache/human_review_items）
> - 6 门控完整重试循环（parse REPAIR/REVISE、ground EXPLORE、select RETRY_GROUND、validate 5-way、reconcile RETRY_L3/EXECUTE、deliver RETRY_VALIDATE），max 3 -> HUMAN
> - human_review_node HUMAN 路由处理
> - parse_agent.py（826 行）+ prompts.py（111 行）+ explore/node.py（214 行）已删除
> - _extract_instruction_tables -> parsing/tables.py；parse/parse_async -> parsing/text_parser.py；esolve_spatial_anchors -> spatial_ops/resolver.py`n> - Graphify AST 依赖图产物已生成
> - 1280 passed / 0 failures。状态：awaiting_review。

> Wave N 已交付（Flash LLM Summary + 死代码清理 + P1-P5 PARTIAL 点全修复）：
> - **N1 死代码清理**：删除 `explore/summaries.py`(301) + `bridge_advisor.py`(163) + `test_bridge_advisor.py`(103)（`_optimize_semantics` 旧路径早已被 `retrieve_evidence` 替代）；更新 `__init__.py`/`README.md`/`session_kg.py:4` 注释
> - **N2 摘要生成器**：重建 `core/instructor_client.py`；`modules/parsing/summary_generator.py` 重写为 Flash LLM 3 层 pipeline（regex 提取 → Instructor schema-enforced → 规则 fallback），`key_points`/`metrics`/`text_summary` 真实生成（此前恒为空）；接口签名不变
> - **N3 P1 SELECT 评分**：`rank_candidates` 返回 `ScoredCandidate`（不再丢弃分数）、`PlacementDecision` 加 `ranking/selected_score`、`aggregate.py` 用真实 proximity/construction/area_fit breakdown（`road_access`/`service_coverage` 仍为 0.0 stub，需外部路网/服务数据）
> - **N4 P4 RECONCILE**：`build_coverage_matrix` candidate→selection 改语义 ID 匹配（`source_parcels`∩BSM，替代位置索引）+ 打乱顺序测试（intervention→spec、spec→candidate 因 schema 无 join key 保留位置对齐）
> - **N5 P3 EXECUTE 闭环**：validate 对失败 check 合成 `ConstraintAdjustment`（Gap A）+ `_validate_node` 映射 legacy `{zone,action,delta_ha,reason,priority}`（Gap B）+ `_execute_layout_node` 读 `state.constraint_adjustments` 调整 zone target（Gap C）——重试循环从空转变为有反馈
> - **N6 P2 PARSE**：`parse/llm_patch.py` + `compile_program_async` 激活 LLM patch（REPAIR/REVISE 不再统一 NEEDS_REVIEW，仅 `human_review` 路由才设）；`post_l3_nodes.parse_node` 改 async 入口
> - **N7 P5 HITL**：post-L3 链 `human_review_node` 用 `interrupt()` 暂停 + checkpointer（全局 AsyncSqliteSaver）+ `services/post_l3_resume.py`（`Command(resume=...)` 恢复，结果写 `.run-tmp/post_l3/{sid}/result.json` + 回写主图 AgentState）+ `api/human_review_routes.py`（GET/POST resolve）；`gis_agent_node` 双路径捕获 interrupt；AgentState 新增 `post_l3_pending_review/thread_id/status/decisions`
> - 全量 **1307 passed / 0 failures**；护栏（architecture/crosswalk/bundle_assembly/kg→data）全绿；advisory_crosswalks budget 保持 0。状态：awaiting_review。

