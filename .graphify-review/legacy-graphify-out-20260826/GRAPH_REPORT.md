# Graph Report - backend/app/agent  (2026-08-06)

## Corpus Check
- 108 files · ~53,981 words
- Verdict: corpus is large enough that graph structure adds value.

## Summary
- 1055 nodes · 1626 edges · 72 communities (61 shown, 11 thin omitted)
- Extraction: 89% EXTRACTED · 11% INFERRED · 0% AMBIGUOUS · INFERRED: 186 edges (avg confidence: 0.79)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)
- [[_COMMUNITY_Community 0|Community 0]]
- [[_COMMUNITY_Community 1|Community 1]]
- [[_COMMUNITY_Community 2|Community 2]]
- [[_COMMUNITY_Community 3|Community 3]]
- [[_COMMUNITY_Community 4|Community 4]]
- [[_COMMUNITY_Community 5|Community 5]]
- [[_COMMUNITY_Community 6|Community 6]]
- [[_COMMUNITY_Community 7|Community 7]]
- [[_COMMUNITY_Community 8|Community 8]]
- [[_COMMUNITY_Community 9|Community 9]]
- [[_COMMUNITY_Community 10|Community 10]]
- [[_COMMUNITY_Community 11|Community 11]]
- [[_COMMUNITY_Community 12|Community 12]]
- [[_COMMUNITY_Community 13|Community 13]]
- [[_COMMUNITY_Community 14|Community 14]]
- [[_COMMUNITY_Community 15|Community 15]]
- [[_COMMUNITY_Community 16|Community 16]]
- [[_COMMUNITY_Community 17|Community 17]]
- [[_COMMUNITY_Community 18|Community 18]]
- [[_COMMUNITY_Community 19|Community 19]]
- [[_COMMUNITY_Community 20|Community 20]]
- [[_COMMUNITY_Community 21|Community 21]]
- [[_COMMUNITY_Community 22|Community 22]]
- [[_COMMUNITY_Community 23|Community 23]]
- [[_COMMUNITY_Community 24|Community 24]]
- [[_COMMUNITY_Community 25|Community 25]]
- [[_COMMUNITY_Community 26|Community 26]]
- [[_COMMUNITY_Community 27|Community 27]]
- [[_COMMUNITY_Community 28|Community 28]]
- [[_COMMUNITY_Community 29|Community 29]]
- [[_COMMUNITY_Community 30|Community 30]]
- [[_COMMUNITY_Community 31|Community 31]]
- [[_COMMUNITY_Community 32|Community 32]]
- [[_COMMUNITY_Community 33|Community 33]]
- [[_COMMUNITY_Community 34|Community 34]]
- [[_COMMUNITY_Community 35|Community 35]]
- [[_COMMUNITY_Community 36|Community 36]]
- [[_COMMUNITY_Community 37|Community 37]]
- [[_COMMUNITY_Community 38|Community 38]]
- [[_COMMUNITY_Community 39|Community 39]]
- [[_COMMUNITY_Community 40|Community 40]]
- [[_COMMUNITY_Community 41|Community 41]]
- [[_COMMUNITY_Community 42|Community 42]]
- [[_COMMUNITY_Community 43|Community 43]]
- [[_COMMUNITY_Community 44|Community 44]]
- [[_COMMUNITY_Community 45|Community 45]]
- [[_COMMUNITY_Community 46|Community 46]]
- [[_COMMUNITY_Community 47|Community 47]]
- [[_COMMUNITY_Community 48|Community 48]]
- [[_COMMUNITY_Community 49|Community 49]]
- [[_COMMUNITY_Community 50|Community 50]]
- [[_COMMUNITY_Community 51|Community 51]]
- [[_COMMUNITY_Community 52|Community 52]]
- [[_COMMUNITY_Community 53|Community 53]]
- [[_COMMUNITY_Community 54|Community 54]]
- [[_COMMUNITY_Community 55|Community 55]]
- [[_COMMUNITY_Community 56|Community 56]]
- [[_COMMUNITY_Community 57|Community 57]]
- [[_COMMUNITY_Community 58|Community 58]]
- [[_COMMUNITY_Community 59|Community 59]]
- [[_COMMUNITY_Community 60|Community 60]]
- [[_COMMUNITY_Community 61|Community 61]]
- [[_COMMUNITY_Community 62|Community 62]]
- [[_COMMUNITY_Community 63|Community 63]]
- [[_COMMUNITY_Community 64|Community 64]]
- [[_COMMUNITY_Community 65|Community 65]]
- [[_COMMUNITY_Community 66|Community 66]]
- [[_COMMUNITY_Community 67|Community 67]]
- [[_COMMUNITY_Community 68|Community 68]]
- [[_COMMUNITY_Community 69|Community 69]]
- [[_COMMUNITY_Community 71|Community 71]]

## God Nodes (most connected - your core abstractions)
1. `analyze_dimension()` - 21 edges
2. `analyze_l2_dimension()` - 17 edges
3. `analyze_l3_dimension()` - 17 edges
4. `select_node()` - 16 edges
5. `execute_node()` - 14 edges
6. `reconcile_node()` - 14 edges
7. `execute_road_planning_from_agent_state()` - 14 edges
8. `validate_node()` - 13 edges
9. `deliver_node()` - 13 edges
10. `validate_aggregate()` - 13 edges

## Surprising Connections (you probably didn't know these)
- `analyze_dimension_node()` --calls--> `analyze_dimension()`  [INFERRED]
  backend/app/agent/bootstrap/graph.py → backend/app/agent/l1_observe/analysis_node.py
- `_persist_artifact()` --calls--> `store_artifact()`  [INFERRED]
  backend/app/agent/bootstrap/post_l3_main_nodes.py → backend/app/agent/bootstrap/artifact_runtime.py
- `_load_ref_artifact()` --calls--> `load_artifact()`  [INFERRED]
  backend/app/agent/bootstrap/post_l3_main_nodes.py → backend/app/agent/bootstrap/artifact_runtime.py
- `_load_ref_artifact()` --calls--> `migrate_legacy_artifacts()`  [INFERRED]
  backend/app/agent/bootstrap/post_l3_main_nodes.py → backend/app/agent/bootstrap/artifact_runtime.py
- `apply_human_review_decision()` --calls--> `_dump()`  [INFERRED]
  backend/app/agent/bootstrap/graph.py → backend/app/agent/bootstrap/post_l3_main_nodes.py

## Communities (72 total, 11 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.05
Nodes (59): _coerce_specs(), compile_program(), compile_program_async(), _content_to_review_package(), _load_program(), parse_aggregate(), Top-level PARSE aggregate - orchestration + public API.  Wave F: COMPILE mode is, Async top-level PARSE pipeline with the LLM patch route activated.      Mirrors (+51 more)

### Community 1 - "Community 1"
Cohesion: 0.08
Nodes (56): _accumulate_gate(), _collect_human_items(), collect_human_review_items(), _context_patch(), _context_version(), deliver_node(), _dump(), _dump_list() (+48 more)

### Community 2 - "Community 2"
Cohesion: 0.05
Nodes (46): advance_phase_node(), l1_worker_node(), l2_worker_node(), l3_worker_node(), layer_router_node(), layer_router_noop(), Layer router + L1/L2/L3 dimension worker nodes for the unified planning graph., Gate PASS phase advance node.      Called when ``after_analysis`` sees a PASS ga (+38 more)

### Community 3 - "Community 3"
Cohesion: 0.08
Nodes (36): candidate_site_to_parcels(), filter_parcels_for_target(), grounding_to_candidate_parcels(), Adapters bridging GroundingResult candidates to CandidateParcel objects., Keep parcels tagged for ``target_ref`` plus any untargeted parcels.      Untarge, _breakdown_from_scored(), build_land_design_brief(), build_site_selection_decision() (+28 more)

### Community 4 - "Community 4"
Cohesion: 0.08
Nodes (28): BaseModel, GISPipelineInput, GISPipelineOutput, GISPipelineState, GIS Agent state — unified Pydantic BaseModel following LangGraph best practices., Fields the API caller must provide to invoke the pipeline., Fields the pipeline returns to the frontend after completion., Complete internal state of the GIS layout pipeline.      All nodes in the StateG (+20 more)

### Community 5 - "Community 5"
Cohesion: 0.08
Nodes (28): layer_aggregate_node(), Layer aggregate node - wires L1/L2/L3 aggregates after layer completion.  Wave M, Update the EXPLORE retry counter based on the layer gate decision.      Non-PASS, Invoke the layer-specific aggregate based on `layer_just_completed`., _update_explore_retry(), _dedup(), l1_aggregate(), merge_fragments() (+20 more)

### Community 6 - "Community 6"
Cohesion: 0.08
Nodes (30): _planned_state_builder_node(), Write L4 planned entities (PlannedParcel, PlannedZone, PlannedFacility, etc.) to, Produce the authoritative PlannedState from the merged ParcelChangeSet., _write_l4_node(), ExecuteAgentState, EXECUTE Agent state - execution layer sub-state.  Migrated from agent/gis/execut, LangGraph reducer: upsert WorkerResult entries by worker_type.      Re-running a, EXECUTE Agent internal state.      Carries upstream inputs (PARSE intent + KG co (+22 more)

### Community 7 - "Community 7"
Cohesion: 0.07
Nodes (31): PlanningPhase, AgentState, DimensionSummary, _merge_artifact_refs(), _merge_config(), _merge_dict_of_dicts(), _merge_dict_of_lists(), _merge_explore_outputs() (+23 more)

### Community 8 - "Community 8"
Cohesion: 0.1
Nodes (32): _check_id_to_stage(), _check_to_issue(), VALIDATE subgraph — deterministic orchestration of the 9 checks into a typed Val, Map a check to its issues_by_stage key (the responsible_stage Literal value as-i, Run all 9 VALIDATE checks and aggregate their findings into a ValidationReport., validate_aggregate(), _check(), check_accessibility() (+24 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (28): analyze_dimension_node(), apply_human_review_decision(), await_human_review(), create_unified_planning_graph(), execute_tools_node(), human_review_node(), prepare_human_review(), publish_human_review_pause() (+20 more)

### Community 10 - "Community 10"
Cohesion: 0.1
Nodes (25): build_candidate_site(), ground_aggregate(), GROUND subgraph aggregate - deterministic orchestrator over SpatialResolver.  Co, Lightweight evidence re-check for GROUND EXPLORE retries.      Gathers a small,, Map one resolved spec to a ``CandidateSite``.      Deterministic scheme: the sit, Resolve all specs through ``SpatialResolver`` into a ``GroundingResult``.      D, retrieve_evidence(), evaluate_ground_gate() (+17 more)

### Community 11 - "Community 11"
Cohesion: 0.16
Nodes (23): build_parcel_change_set(), _classification(), design_all(), design_facility_parcel(), design_project_footprint(), design_project_parcel(), design_zone_parcel(), _geometry_to_wkt() (+15 more)

### Community 12 - "Community 12"
Cohesion: 0.12
Nodes (20): build_deliverables_from_export(), _build_planned_view(), build_traceability_from_coverage(), collect_upstream_human_items(), deliver_aggregate(), DELIVER aggregate — deterministic delivery manifest orchestrator.  Builds a type, Run deliver checks and build a typed DeliveryManifest., Map each CoverageMatrixRow to a TraceabilityEntry (Wave K -> Wave L bridge). (+12 more)

### Community 13 - "Community 13"
Cohesion: 0.18
Nodes (21): _as_dict(), _default_kg_retry_adapter(), execute_road_planning_from_agent_state(), _fc(), _gis_payload(), _infer_action(), _intent_road_targets(), _layer_config() (+13 more)

### Community 14 - "Community 14"
Cohesion: 0.11
Nodes (15): Translate a gate's EXPLORE pending_requests into evidence retrievals.      Wave, Retrieve evidence from all session sources for a planning stage.      Searches:, retrieve_evidence(), retrieve_evidence_for_gate(), Retrieve spatial group statistics from the VillageBundle snapshot.      Returns, retrieve_from_bundle(), Extract 【INSTRUCTION】 sections from reports as structured evidence.      Instruc, retrieve_from_instructions() (+7 more)

### Community 15 - "Community 15"
Cohesion: 0.14
Nodes (16): Enum, analyze_dimension(), _build_prompt(), _build_revision_completed(), _extract_intent_targets(), _extract_landuse_metrics(), _extract_natural_villages(), _get_llm() (+8 more)

### Community 16 - "Community 16"
Cohesion: 0.13
Nodes (18): build_execute_agent_graph(), _checkpoint_safe(), _checkpoint_safe_node(), _execution_review_node(), _geometry_materialize_node(), _merge_worker_results_node(), EXECUTE Agent - spatial execution subgraph.  Migrated from agent/gis/execute/age, Route after execution review: pass -> END, fail -> retry (max 3 rounds -> human) (+10 more)

### Community 17 - "Community 17"
Cohesion: 0.16
Nodes (16): _dedup(), _dedup_by_id(), _dedup_dependencies(), enrich_program_from_upstream(), l3_aggregate(), merge_program_fragments(), L3 aggregate node - merge L3ProgramFragments into PlanningProgram.  Wave E decis, Load L1/L2 artifacts by run_id convention and enrich the program.      Sets ``l1 (+8 more)

### Community 18 - "Community 18"
Cohesion: 0.25
Nodes (14): build_coverage_matrix(), _chain_status(), check_l3_l4_target_coverage(), _inc(), Deterministic chain-coverage reconciliation orchestrator.  Aggregates the six RE, reconcile_aggregate(), check_candidate_selection_coverage(), check_change_planned_coverage() (+6 more)

### Community 19 - "Community 19"
Cohesion: 0.2
Nodes (14): ArtifactReplayError, context_ref_for(), _jsonable(), load_artifact(), migrate_legacy_artifacts(), payload_checksum(), Reference-only workflow state helpers.  The graph stores small references and re, Build the unified map from one legacy checkpoint without copying payloads. (+6 more)

### Community 20 - "Community 20"
Cohesion: 0.16
Nodes (13): publish_dimension_complete(), Publish DIMENSION_COMPLETE SSE event (parses structured_summary JSON)., Render an ExplorationResult as a unified markdown prompt section.      Replaces, render_evidence_prompt_section(), L2 STRATEGIZE subgraph - independent worker.  L2 strategy analysis has its own w, analyze_l2_dimension(), _build_prompt(), _build_revision_completed() (+5 more)

### Community 21 - "Community 21"
Cohesion: 0.17
Nodes (13): publish_dimension_delta(), Publish a single DIMENSION_DELTA SSE event (throttling handled by caller)., L3 PLAN subgraph - independent worker.  L3 detail planning has its own worker (a, analyze_l3_dimension(), _build_prompt(), _build_revision_completed(), _extract_natural_villages(), _get_llm() (+5 more)

### Community 22 - "Community 22"
Cohesion: 0.22
Nodes (14): _change_after_code(), _change_bsm(), _dedup_layout_configs(), _detect_bsm_conflicts(), merge_worker_results(), merge_worker_results - unified WorkerResult merge into ParcelChangeSet + layout_, True when every change carries a non-empty, valid WKT geometry., True when non-create changes preserve a positive area (create adds area). (+6 more)

### Community 23 - "Community 23"
Cohesion: 0.3
Nodes (13): _build_accessibility(), _build_area_conservation(), _build_check_summary(), _build_gate_decision(), _build_provenance(), _build_spatial_checks(), _build_stage_attribution(), build_validate_review_package() (+5 more)

### Community 24 - "Community 24"
Cohesion: 0.22
Nodes (13): _allocate_empty_zone_targets(), _assign_custom_zone_features(), _build_custom_planning_layer(), _function_zone_layer(), Build the function_zone layer from reclassified ParcelChange entries., Tag every landuse feature with its custom zone (pending for unclaimed parcels)., Build the custom_planning_zone layer via the vocabulary-driven generator (no MIP, MIP-allocate parcels for zone targets with no candidate_bsms.      The unclaimed (+5 more)

### Community 25 - "Community 25"
Cohesion: 0.24
Nodes (12): _default_dlbm_for(), extract_vocabulary_deterministic(), extract_vocabulary_from_reports(), _extract_vocabulary_llm(), _is_protection(), _parse_rules(), L3 报告 → session 功能区词汇表提取器（LLM 自由给色，确定性 fallback）。  Migrated from agent/gis/vocab, LLM 输出 rules → TypingRule（有界谓词白名单，非法谓词丢弃）。 (+4 more)

### Community 26 - "Community 26"
Cohesion: 0.19
Nodes (7): DataPipeline, Unified data pipeline: structured_summary -> ToolRegistry -> professional_data., Unified tool execution pipeline.      Flow:     1. Read tool config for the dime, Execute tools for a dimension and return aggregated results.          Args:, Read tool names from dimension config (phases.yaml)., Keep only tools that exist in the TOOL_REGISTRY., Build tool execution context from summary and state.

### Community 27 - "Community 27"
Cohesion: 0.27
Nodes (12): _build_area_drift(), _build_backward_lineage(), _build_chain_coverage(), _build_coverage_summary(), _build_gate_decision(), _build_inconsistency_list(), _build_provenance(), build_reconcile_review_package() (+4 more)

### Community 28 - "Community 28"
Cohesion: 0.23
Nodes (11): DependencyError, load_dependency_reports(), load_layered_dependency_reports(), RAGRetrievalLog, Shared dimension runtime infrastructure for L1/L2/L3 analysis nodes.  Extracted, Load same-layer and cross-layer dependency reports.      Returns (deps, same_lay, Load same-layer + split cross-layer dependency reports.      For L3 the cross-la, Run RAG retrieval for a dimension. Returns (context_str, RAGRetrievalLog|None). (+3 more)

### Community 29 - "Community 29"
Cohesion: 0.29
Nodes (11): _build_classification(), build_deliver_review_package(), _build_deliverables(), _build_exit_gate(), _build_gate_decision(), _build_human_items(), _build_provenance(), _build_statutory_completeness() (+3 more)

### Community 30 - "Community 30"
Cohesion: 0.17
Nodes (12): _adjustment_get(), _apply_constraint_adjustments(), _build_landuse_geojson(), _build_parcel_by_bsm(), _parcel_from_feature(), _prepare_inputs_node(), Resolve the current land-use GeoJSON from gis_bundle or gis_data., Read a field from a legacy adjustment dict or an attribute-carrying object. (+4 more)

### Community 31 - "Community 31"
Cohesion: 0.27
Nodes (10): build_render_layers(), _feature_collection(), _function_zone_layer(), _normalize_layer(), Render-layer derivation for the DELIVER stage.  Builds the ``render_result`` lay, Derive the renderable layer list from PlannedState + layout_configs.      Priori, Parse a WKT string into a GeoJSON geometry dict; None on failure., Normalize one layout_config entry to the {layerType, layerName, data} shape. (+2 more)

### Community 32 - "Community 32"
Cohesion: 0.18
Nodes (10): 职责边界, 目录文件, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/execute 子包（EXECUTE 空间执行）, 图拓扑（来自 `build_execute_agent_graph` 实际边） (+2 more)

### Community 33 - "Community 33"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/deliver 子包（DELIVER 交付清单） (+1 more)

### Community 34 - "Community 34"
Cohesion: 0.2
Nodes (10): _facility_worker(), _footprint_geometry(), _parcel_geometry(), _project_worker(), _project_worker_node(), Prepared parcel index, falling back to a fresh build when empty.      Direct nod, Polygon footprint for a planned feature.      Prefer the change's after geometry, Project worker: place each L3 project on the SSD-selected parcel.      Consumes (+2 more)

### Community 35 - "Community 35"
Cohesion: 0.22
Nodes (10): _axis_worker(), _axis_worker_node(), _intent_list(), A task runs when no explicit routing was set, or when it is routed.      Legacy, Axis worker: development-axis layer (decision-driven from intent)., Road worker: planned road network generation.      Primary path: the injected ``, Read a list field off a typed intent or a legacy intent dict., _road_worker() (+2 more)

### Community 36 - "Community 36"
Cohesion: 0.2
Nodes (9): 一、定位, 二、目录结构, 四、输入输出契约, 五、相关文档, 三、桥接 agent（agent.py）, agent/explore 子包（EXPLORE 能力引擎）, code:block1 (explore/), code:block2 (explore(planning_text) -> ExplorationInstructionCollection) (+1 more)

### Community 37 - "Community 37"
Cohesion: 0.29
Nodes (9): _extract_area_ratio(), _feature_props(), format_bound_spatial_intent(), _match_category_code(), _project_category(), Strict, tool-free conversion of Explore/Binder artifacts to planning intent.  Mi, Match a project/zone name against the session vocabulary categories., From evidence text: '15.39%' → 0.1539; else '0.15公顷' → None (needs total). (+1 more)

### Community 38 - "Community 38"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/ground 子包（GROUND 空间接地） (+1 more)

### Community 39 - "Community 39"
Cohesion: 0.2
Nodes (9): 职责边界, 流程图（12-worker → fragment → snapshot → gate）, 目录文件, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/l1_observe 子包（L1 现状观察） (+1 more)

### Community 40 - "Community 40"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/l2_strategize 子包（L2 策略推导） (+1 more)

### Community 41 - "Community 41"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/l3_plan 子包（L3 详细规划） (+1 more)

### Community 42 - "Community 42"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/parse 子包（PARSE 意图编译） (+1 more)

### Community 43 - "Community 43"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/reconcile 子包（RECONCILE 全链对账） (+1 more)

### Community 44 - "Community 44"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/select 子包（SELECT 选址决策） (+1 more)

### Community 45 - "Community 45"
Cohesion: 0.2
Nodes (9): 职责边界, 目录文件, 流程图, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/validate 子包（VALIDATE 规划校验） (+1 more)

### Community 46 - "Community 46"
Cohesion: 0.36
Nodes (8): _dominant_stage(), _error_counts(), evaluate_reconcile_gate(), RECONCILE gate - 4-way responsibility router over a ReconciliationReport.  Mirro, Count error-severity inconsistencies per responsible_stage (skips empty)., Return (stage, count) of the unique max, or (None, max) on a tie., Return the deterministic route:     "PASS"|"RETRY_L3"|"RETRY_EXECUTE"|"HUMAN"., reconcile_gate_route()

### Community 47 - "Community 47"
Cohesion: 0.31
Nodes (7): execute_tools_node(), _invoke_single(), _normalize_name(), Tool execution node — dispatches tool calls via LangChain BaseTool.ainvoke.  Fil, Normalize tool name: resolve PascalCase aliases to registered snake_case., Invoke a single tool call with SSE publishing., Execute non-routing tool calls from the last AIMessage in parallel.

### Community 48 - "Community 48"
Cohesion: 0.22
Nodes (8): 一、定位, 二、目录结构, 三、实现, 四、输入输出契约, 五、相关文档, agent/tools 子包（工具执行节点）, code:block1 (tools/), code:block2 (输入:  state（messages 最后一条带 tool_calls）)

### Community 49 - "Community 49"
Cohesion: 0.36
Nodes (8): _dominant_stage(), _error_counts(), evaluate_validate_gate(), VALIDATE gate evaluator - 5-way responsibility router over a ValidationReport., Count error-severity ValidationIssues per stage (skips empty stages)., Return (stage, count) of the unique max, or (None, max) on a tie., Return the deterministic route:     "PASS"|"RETRY_EXECUTE"|"RETRY_SELECT"|"RETRY, validate_gate_route()

### Community 50 - "Community 50"
Cohesion: 0.25
Nodes (7): 职责边界, 目录文件, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/explore/retrievers 子包（确定性证据检索器）

### Community 51 - "Community 51"
Cohesion: 0.29
Nodes (6): 职责边界, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/common 子包（共享维度运行时）

### Community 52 - "Community 52"
Cohesion: 0.29
Nodes (6): 职责边界, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/conversation_router 子包（中央路由）

### Community 53 - "Community 53"
Cohesion: 0.43
Nodes (6): _blocking_categories(), deliver_gate_route(), evaluate_deliver_gate(), DELIVER gate - 3-way router over a DeliveryManifest.  Mirrors the RECONCILE/VALI, Categorize blocking human items by their item_id prefix., Return the deterministic route: "PASS"|"RETRY_VALIDATE"|"HUMAN".

### Community 54 - "Community 54"
Cohesion: 0.29
Nodes (7): _allocated_geojson_from_changes(), _execution_error(), _facility_worker_node(), landuse features with reclassified parcels tagged with their planning land use., Determine which execution sub-tasks to run based on intent.      Layout is the c, _route_tasks_node(), _zone_worker_node()

### Community 55 - "Community 55"
Cohesion: 0.29
Nodes (6): 职责边界, 输入/输出契约, 依赖方向, 禁止行为, 相关文档, agent/plan_state 子包（上游状态 + 层完成检测）

### Community 56 - "Community 56"
Cohesion: 0.4
Nodes (5): Save a StepReport. Non-fatal on error., save_step_report(), compare_intent_to_layout(), EXPLORE verification — compare L3 text targets vs L4 geometry (post-execute)., save_explore_verification()

### Community 57 - "Community 57"
Cohesion: 0.4
Nodes (5): _format_dict_result(), generate_professional_data_section(), Unified professional data formatter for all planning layers.  Replaces the dupli, Format professional_data dict into prompt-injectable text.      Args:         di, Format a dict-type tool result into a prompt section.

### Community 58 - "Community 58"
Cohesion: 0.4
Nodes (4): 入口, 依赖边界, Agent 编排层, HITL

### Community 59 - "Community 59"
Cohesion: 0.5
Nodes (4): generate_summary(), Generate structured summary JSON string with fallback., _generate_summary(), Generate structured JSON summary for a dimension report (delegates to shared run

## Knowledge Gaps
- **426 isolated node(s):** `Reference-only workflow state helpers.  The graph stores small references and re`, `Raised when a replay cannot prove artifact identity.`, `Return the stable context reference carried by a workflow state.`, `Persist an artifact idempotently and return its JSON reference.`, `Load and validate a typed artifact from refs; return None when absent.` (+421 more)
  These have ≤1 connection - possible missing edges or undocumented components.
- **11 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.