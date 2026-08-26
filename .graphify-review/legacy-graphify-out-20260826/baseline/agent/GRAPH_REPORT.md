# Graph Report - graphify-tmp-staging\agent  (2026-08-07)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1164 nodes · 2258 edges · 64 communities (57 shown, 7 thin omitted)
- Extraction: 92% EXTRACTED · 8% INFERRED · 0% AMBIGUOUS · INFERRED: 183 edges (avg confidence: 0.75)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `7863f666`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- execute_agent.py
- select_aggregate
- post_l3_main_nodes.py
- state.py
- execute/__init__.py
- build_ground_review_package
- validate_aggregate
- compile_node.py
- layer_aggregate_node
- l3_plan/aggregate.py
- deliver_aggregate
- create_unified_planning_graph
- l1_aggregate
- layer_router.py
- build_l2_review_package
- road_generator.py
- analyze_dimension
- reconcile_aggregate
- analyze_l3_dimension
- analyze_l2_dimension
- merge_worker_results
- changeset_to_planned_state
- build_validate_review_package
- dimension_runtime.py
- vocab_extractor.py
- agent.py
- generate_llm_patches
- build_reconcile_review_package
- build_deliver_review_package
- build_parse_review_package
- DataPipeline
- parse/__init__.py
- apply_patches
- retrieve_evidence
- compile_program_async
- after_conversation
- render_layers.py
- build_execution_plan
- ExploreFlashAgent
- conversation_node
- parse/aggregate.py
- evaluate_reconcile_gate
- execute_tools_node
- evaluate_validate_gate
- stage_audit.py
- evaluate_deliver_gate
- gis_pipeline_state.py
- save_step_report
- retrieve_from_reports
- generate_professional_data_section
- retrieve_from_kg
- retrieve_from_bundle
- retrieve_from_instructions
- enrich_summary_background
- generate_summary
- _pass_gate
- publish_dimension_delta
- publish_dimension_start
- common/__init__.py
- deliver/__init__.py
- retrievers/__init__.py
- reconcile/__init__.py
- validate/__init__.py

## God Nodes (most connected - your core abstractions)
1. `ExecuteAgentState` - 32 edges
2. `create_unified_planning_graph()` - 26 edges
3. `analyze_dimension()` - 24 edges
4. `analyze_l2_dimension()` - 21 edges
5. `analyze_l3_dimension()` - 21 edges
6. `compile_program_async()` - 18 edges
7. `select_node()` - 17 edges
8. `build_execute_agent_graph()` - 17 edges
9. `validate_aggregate()` - 16 edges
10. `_require_context()` - 15 edges

## Surprising Connections (you probably didn't know these)
- `_maybe_extract_bindings()` --calls--> `load_artifact()`  [INFERRED]
  plan_state/completion_node.py → bootstrap/artifact_runtime.py
- `l1_aggregate()` --calls--> `require_frozen_context()`  [INFERRED]
  l1_observe/aggregate.py → bootstrap/context_guard.py
- `l2_aggregate()` --calls--> `require_frozen_context()`  [INFERRED]
  l2_strategize/aggregate.py → bootstrap/context_guard.py
- `l3_aggregate()` --calls--> `require_frozen_context()`  [INFERRED]
  l3_plan/aggregate.py → bootstrap/context_guard.py
- `analyze_dimension_node()` --calls--> `analyze_dimension()`  [INFERRED]
  bootstrap/graph.py → l1_observe/analysis_node.py

## Import Cycles
- None detected.

## Communities (64 total, 7 thin omitted)

### Community 0 - "execute_agent.py"
Cohesion: 0.05
Nodes (82): _adjustment_get(), _allocate_empty_zone_targets(), _allocated_geojson_from_changes(), _apply_constraint_adjustments(), _assign_custom_zone_features(), _axis_worker(), _axis_worker_node(), _build_custom_planning_layer() (+74 more)

### Community 1 - "select_aggregate"
Cohesion: 0.07
Nodes (56): DemandPoint, PlacementDecision, ScoredCandidate, candidate_site_to_parcels(), filter_parcels_for_target(), grounding_to_candidate_parcels(), CandidateParcel, CandidateSite (+48 more)

### Community 2 - "post_l3_main_nodes.py"
Cohesion: 0.10
Nodes (56): _accumulate_gate(), _adopt_context(), _collect_human_items(), collect_human_review_items(), _context_version(), deliver_node(), _detect_retry_exhaustion_stage(), _dump() (+48 more)

### Community 3 - "state.py"
Cohesion: 0.05
Nodes (46): get_next_phase(), PlanningPhase, Enum, Phase machine: PlanningPhase enum + layer/phase/wave conversion helpers.  Migrat, _invoke_extraction(), layer_completion_check(), _maybe_extract_bindings(), Any (+38 more)

### Community 4 - "execute/__init__.py"
Cohesion: 0.09
Nodes (48): ClassificationRef, build_parcel_change_set(), _classification(), design_all(), design_facility_parcel(), design_project_footprint(), design_project_parcel(), design_zone_parcel() (+40 more)

### Community 5 - "build_ground_review_package"
Cohesion: 0.09
Nodes (39): build_candidate_site(), ground_aggregate(), Any, CandidateSite, GroundingResult, PlanningContext, SpatialReferenceSpec, GROUND subgraph aggregate - deterministic orchestrator over SpatialResolver.  Co (+31 more)

### Community 6 - "validate_aggregate"
Cohesion: 0.11
Nodes (39): SimpleNamespace, _check_id_to_stage(), _check_to_issue(), Any, ValidationCheck, ValidationReport, VALIDATE subgraph — deterministic orchestration of the 9 checks into a typed Val, Map a check to its issues_by_stage key (the responsible_stage Literal value as-i (+31 more)

### Community 7 - "compile_node.py"
Cohesion: 0.10
Nodes (34): _extract_area_ratio(), _feature_props(), format_bound_spatial_intent(), _match_category_code(), _project_category(), Any, SpatialPlanningIntent, Strict, tool-free conversion of Explore/Binder artifacts to planning intent.  Mi (+26 more)

### Community 8 - "layer_aggregate_node"
Cohesion: 0.09
Nodes (30): ArtifactReplayError, context_ref_for(), _jsonable(), load_artifact(), migrate_legacy_artifacts(), payload_checksum(), Any, Reference-only workflow state helpers.  The graph stores small references and re (+22 more)

### Community 9 - "l3_plan/aggregate.py"
Cohesion: 0.11
Nodes (28): InterventionDependency, _dedup(), _dedup_by_id(), _dedup_dependencies(), enrich_program_from_upstream(), l3_aggregate(), merge_program_fragments(), Any (+20 more)

### Community 10 - "deliver_aggregate"
Cohesion: 0.09
Nodes (28): build_deliverables_from_export(), _build_planned_view(), build_traceability_from_coverage(), collect_upstream_human_items(), deliver_aggregate(), CoverageMatrix, DeliveryManifest, HumanItem (+20 more)

### Community 11 - "create_unified_planning_graph"
Cohesion: 0.16
Nodes (26): analyze_dimension_node(), apply_human_review_decision(), await_human_review(), create_unified_planning_graph(), execute_tools_node(), prepare_human_review(), publish_human_review_pause(), Any (+18 more)

### Community 12 - "l1_aggregate"
Cohesion: 0.13
Nodes (24): _dedup(), _dedup_location_facts(), _dedup_sources(), l1_aggregate(), merge_fragments(), Any, EvidenceSource, L1Snapshot (+16 more)

### Community 13 - "layer_router.py"
Cohesion: 0.12
Nodes (25): advance_phase_node(), l1_worker_node(), l2_worker_node(), l3_worker_node(), layer_router_node(), layer_router_noop(), Any, Send (+17 more)

### Community 14 - "build_l2_review_package"
Cohesion: 0.13
Nodes (23): _dedup(), _dedup_sources(), l2_aggregate(), merge_strategy_fragments(), Any, EvidenceSource, L2Strategy, L2 aggregate node - merge L2StrategyFragments into L2Strategy.  Wave D decision: (+15 more)

### Community 15 - "road_generator.py"
Cohesion: 0.24
Nodes (23): _as_dict(), _default_kg_retry_adapter(), execute_road_planning_from_agent_state(), _fc(), _gis_payload(), _infer_action(), _intent_road_targets(), _layer_config() (+15 more)

### Community 16 - "analyze_dimension"
Cohesion: 0.13
Nodes (21): analyze_dimension(), _build_prompt(), _build_revision_completed(), create_dimension_state(), _dependency_summary(), _extract_intent_targets(), _extract_landuse_metrics(), _extract_natural_villages() (+13 more)

### Community 17 - "reconcile_aggregate"
Cohesion: 0.20
Nodes (19): CoverageMatrixRow, build_coverage_matrix(), _chain_status(), check_l3_l4_target_coverage(), _inc(), CoverageMatrix, ReconciliationInconsistency, ReconciliationReport (+11 more)

### Community 18 - "analyze_l3_dimension"
Cohesion: 0.16
Nodes (18): L3 PLAN subgraph - independent worker.  L3 detail planning has its own worker (a, analyze_l3_dimension(), _build_prompt(), _build_revision_completed(), _dependency_summary(), _extract_natural_villages(), _get_llm(), _location_evidence() (+10 more)

### Community 19 - "analyze_l2_dimension"
Cohesion: 0.18
Nodes (16): generate_summary_regex(), Layer-1 only: deterministic regex extraction (zero LLM, instant).      Returns t, L2 STRATEGIZE subgraph - independent worker.  L2 strategy analysis has its own w, analyze_l2_dimension(), _build_prompt(), _build_revision_completed(), _dependency_summary(), _get_llm() (+8 more)

### Community 20 - "merge_worker_results"
Cohesion: 0.21
Nodes (17): _change_after_code(), _change_after_wkt(), _change_bsm(), _dedup_layout_configs(), _detect_bsm_conflicts(), merge_worker_results(), Any, ParcelChangeSet (+9 more)

### Community 21 - "changeset_to_planned_state"
Cohesion: 0.16
Nodes (17): _axis_target_to_planned_axis(), _change_to_planned_parcel(), changeset_to_planned_state(), _facility_target_to_planned_facility(), _geometry_area_ha(), Any, ParcelChange, ParcelChangeSet (+9 more)

### Community 22 - "build_validate_review_package"
Cohesion: 0.32
Nodes (17): _build_accessibility(), _build_area_conservation(), _build_check_summary(), _build_gate_decision(), _build_provenance(), _build_spatial_checks(), _build_stage_attribution(), build_validate_review_package() (+9 more)

### Community 23 - "dimension_runtime.py"
Cohesion: 0.18
Nodes (16): DependencyError, _display_report(), load_dependency_reports(), load_layered_dependency_reports(), Any, RAGRetrievalLog, Shared dimension runtime infrastructure for L1/L2/L3 analysis nodes.  Extracted, Load same-layer and cross-layer dependency reports.      Returns (deps, same_lay (+8 more)

### Community 24 - "vocab_extractor.py"
Cohesion: 0.24
Nodes (15): _default_dlbm_for(), extract_vocabulary_deterministic(), extract_vocabulary_from_reports(), _extract_vocabulary_llm(), _is_protection(), _parse_rules(), Any, L3 报告 → session 功能区词汇表提取器（LLM 自由给色，确定性 fallback）。  Migrated from agent/gis/vocab (+7 more)

### Community 25 - "agent.py"
Cohesion: 0.20
Nodes (13): _action_for(), _domain_for(), explore_planning_text(), _instructions_from_l3_table(), _mentions(), Path, Independent Explore Flash agent — text -> ExplorationInstructionCollection.  The, Convert every formal L3 row into one evidence-preserving instruction. (+5 more)

### Community 26 - "generate_llm_patches"
Cohesion: 0.19
Nodes (15): _build_prompt(), CompilationPatchList, _finalize_patches(), generate_llm_patches(), _is_patchable_path(), BaseModel, CompilationPatch, IntentCompilationResult (+7 more)

### Community 27 - "build_reconcile_review_package"
Cohesion: 0.33
Nodes (15): _build_area_drift(), _build_backward_lineage(), _build_chain_coverage(), _build_coverage_summary(), _build_gate_decision(), _build_inconsistency_list(), _build_provenance(), build_reconcile_review_package() (+7 more)

### Community 28 - "build_deliver_review_package"
Cohesion: 0.36
Nodes (14): _build_classification(), build_deliver_review_package(), _build_deliverables(), _build_exit_gate(), _build_gate_decision(), _build_human_items(), _build_provenance(), _build_statutory_completeness() (+6 more)

### Community 29 - "build_parse_review_package"
Cohesion: 0.25
Nodes (14): build_parse_review_package(), _collect_target_meta(), _iter_targets(), Any, ArtifactRef, GateDecision, IntentCompilationResult, SpatialReferenceSpec (+6 more)

### Community 30 - "DataPipeline"
Cohesion: 0.19
Nodes (8): DataPipeline, Any, Unified data pipeline: structured_summary -> ToolRegistry -> professional_data., Unified tool execution pipeline.      Flow:     1. Read tool config for the dime, Execute tools for a dimension and return aggregated results.          Args:, Read tool names from dimension config (phases.yaml)., Keep only tools that exist in the TOOL_REGISTRY., Build tool execution context from summary and state.

### Community 31 - "parse/__init__.py"
Cohesion: 0.19
Nodes (11): evaluate_parse_gate(), _is_empty_intent(), GateDecision, IntentCompilationResult, PARSE gate node - 4-route evaluator (Hybrid routing).  Pure function: IntentComp, PARSE subgraph - deterministic compile/repair/revise pipeline.  Wave F: PARSE is, IntentCompilationResult, ParseDiagnostic (+3 more)

### Community 32 - "apply_patches"
Cohesion: 0.25
Nodes (13): _apply_append(), apply_patches(), _apply_remove(), _apply_update(), _is_supported_path(), Any, CompilationPatch, IntentCompilationResult (+5 more)

### Community 33 - "retrieve_evidence"
Cohesion: 0.23
Nodes (11): EvidenceBundle, ExplorationRequest, ExplorationResult, EXPLORE 能力引擎 — 概要层与访问层组装。  EXPLORE 在本仓库有两层实现并存：  1. **桥接 agent（Flash LLM 可选）** —, SpatialCognitionEvidence, Render an ExplorationResult as a unified markdown prompt section.      Replaces, Translate a gate's EXPLORE pending_requests into evidence retrievals.      Wave, Retrieve evidence from all session sources for a planning stage.      Searches: (+3 more)

### Community 34 - "compile_program_async"
Cohesion: 0.26
Nodes (13): _coerce_specs(), compile_program(), compile_program_async(), CompilationPatch, GateDecision, IntentCompilationResult, PlanningProgram, SpatialReferenceSpec (+5 more)

### Community 35 - "after_conversation"
Cohesion: 0.29
Nodes (10): get_layer_dimensions(), after_conversation(), _dispatch_current(), _infer_dim_from_feedback(), Any, Send, 统一路由逻辑 - 简化版  使用 LangGraph Send API 实现动态路由。 纯函数风格，配置驱动。  路由函数： - after_conversat, 对话后路由 - 新架构核心      处理：     1. 级联修订：feedback 存在时计算影响树     2. 推进意图：AdvancePlanning (+2 more)

### Community 36 - "render_layers.py"
Cohesion: 0.30
Nodes (11): build_render_layers(), _feature_collection(), _function_zone_layer(), _normalize_layer(), Any, Render-layer derivation for the DELIVER stage.  Builds the ``render_result`` lay, Derive the renderable layer list from PlannedState + layout_configs.      Priori, Parse a WKT string into a GeoJSON geometry dict; None on failure. (+3 more)

### Community 37 - "build_execution_plan"
Cohesion: 0.24
Nodes (11): build_execution_plan(), _intent_list(), Any, ExecutionPlan builder — thin layer over intent targets + SELECT output.  Wave O:, Read a list field off a typed intent or a legacy intent dict., Unwrap an IntentCompilationResult to its typed SpatialPlanningIntent., Defensively read an identifier off a typed target / dict / bare value., From intent targets + site_selection generate WorkerTask list + dependency graph (+3 more)

### Community 38 - "ExploreFlashAgent"
Cohesion: 0.23
Nodes (7): _chunks(), ExploreFlashAgent, Any, Small tool-capable exploration unit with a deterministic safe baseline.      Lif, Construct the independently configured Flash model on demand., KG tool facade that cannot fall back to another session., SessionKGQuery

### Community 39 - "conversation_node"
Cohesion: 0.24
Nodes (10): ChatPromptTemplate, _build_prompt(), conversation_node(), _get_llm_with_tools(), Any, Conversation node — central router (brain).  Binds advance_planning_intent / gis, Lazy-init the LLM+tools chain (cached across calls)., Build the ChatPromptTemplate with phase / config filled in. (+2 more)

### Community 40 - "parse/aggregate.py"
Cohesion: 0.29
Nodes (10): _content_to_review_package(), _load_program(), parse_aggregate(), Any, ArtifactRef, ReviewPackage, Top-level PARSE aggregate - orchestration + public API.  Wave F: COMPILE mode is, Resolve the PlanningProgram from state (object, or artifact via store). (+2 more)

### Community 41 - "evaluate_reconcile_gate"
Cohesion: 0.31
Nodes (10): _dominant_stage(), _error_counts(), evaluate_reconcile_gate(), GateDecision, ReconciliationReport, RECONCILE gate - 4-way responsibility router over a ReconciliationReport.  Mirro, Count error-severity inconsistencies per responsible_stage (skips empty)., Return (stage, count) of the unique max, or (None, max) on a tie. (+2 more)

### Community 42 - "execute_tools_node"
Cohesion: 0.27
Nodes (9): ToolMessage, execute_tools_node(), _invoke_single(), _normalize_name(), Any, Tool execution node — dispatches tool calls via LangChain BaseTool.ainvoke.  Fil, Normalize tool name: resolve PascalCase aliases to registered snake_case., Invoke a single tool call with SSE publishing. (+1 more)

### Community 43 - "evaluate_validate_gate"
Cohesion: 0.31
Nodes (10): _dominant_stage(), _error_counts(), evaluate_validate_gate(), GateDecision, ValidationReport, VALIDATE gate evaluator - 5-way responsibility router over a ValidationReport., Count error-severity ValidationIssues per stage (skips empty stages)., Return (stage, count) of the unique max, or (None, max) on a tie. (+2 more)

### Community 44 - "stage_audit.py"
Cohesion: 0.36
Nodes (9): audited_stage(), _checksum(), _gate_route(), _input_snapshot(), _jsonable(), Any, Stage-level audit wrapper for the real session planning graph.  The wrapper reco, Decorate an async graph node with started/completed/failed reports. (+1 more)

### Community 45 - "evaluate_deliver_gate"
Cohesion: 0.36
Nodes (8): _blocking_categories(), deliver_gate_route(), evaluate_deliver_gate(), DeliveryManifest, GateDecision, DELIVER gate - 3-way router over a DeliveryManifest.  Mirrors the RECONCILE/VALI, Categorize blocking human items by their item_id prefix., Return the deterministic route: "PASS"|"RETRY_VALIDATE"|"HUMAN".

### Community 46 - "gis_pipeline_state.py"
Cohesion: 0.28
Nodes (8): GISPipelineInput, GISPipelineOutput, GISPipelineState, BaseModel, GIS Agent state — unified Pydantic BaseModel following LangGraph best practices., Fields the API caller must provide to invoke the pipeline., Fields the pipeline returns to the frontend after completion., Complete internal state of the GIS layout pipeline.      All nodes in the StateG

### Community 47 - "save_step_report"
Cohesion: 0.38
Nodes (6): Save a StepReport. Non-fatal on error., save_step_report(), compare_intent_to_layout(), Any, EXPLORE verification — compare L3 text targets vs L4 geometry (post-execute)., save_explore_verification()

### Community 48 - "retrieve_from_reports"
Cohesion: 0.33
Nodes (6): _extract_spatial_findings(), EvidenceFact, EvidenceSource, Report retriever - search L1/L2/L3 AnalysisReports for spatial evidence., Search L1/L2/L3 reports for spatial findings relevant to the dimension.      Ret, retrieve_from_reports()

### Community 49 - "generate_professional_data_section"
Cohesion: 0.38
Nodes (6): _format_dict_result(), generate_professional_data_section(), Any, Unified professional data formatter for all planning layers.  Replaces the dupli, Format professional_data dict into prompt-injectable text.      Args:         di, Format a dict-type tool result into a prompt section.

### Community 50 - "retrieve_from_kg"
Cohesion: 0.33
Nodes (5): EvidenceFact, SpatialCognitionEvidence, KG retriever - session KG cognition + topology facts for L2/L3., Retrieve KG three-layer cognition + topology facts.      Returns (facts, cogniti, retrieve_from_kg()

### Community 51 - "retrieve_from_bundle"
Cohesion: 0.40
Nodes (4): EvidenceFact, EvidenceSource, Retrieve spatial group statistics from the VillageBundle snapshot.      Returns, retrieve_from_bundle()

### Community 52 - "retrieve_from_instructions"
Cohesion: 0.40
Nodes (4): EvidenceFact, EvidenceSource, Extract 【INSTRUCTION】 sections from reports as structured evidence.      Instruc, retrieve_from_instructions()

### Community 53 - "enrich_summary_background"
Cohesion: 0.33
Nodes (4): enrich_summary_background(), publish_dimension_complete(), Publish DIMENSION_COMPLETE SSE event (parses structured_summary JSON)., Background task: Flash-LLM summary enrichment + DB update. Non-fatal.

### Community 54 - "generate_summary"
Cohesion: 0.50
Nodes (4): generate_summary(), Generate structured summary JSON string with fallback., _generate_summary(), Generate structured JSON summary for a dimension report (delegates to shared run

### Community 55 - "_pass_gate"
Cohesion: 0.67
Nodes (3): _pass_gate(), GateDecision, Construct a force-pass GateDecision for a stage (approve path).

## Knowledge Gaps
- **7 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_unified_planning_graph()` connect `create_unified_planning_graph` to `state.py`, `after_conversation`, `conversation_node`, `layer_aggregate_node`, `layer_router.py`?**
  _High betweenness centrality (0.275) - this node is a cross-community bridge._
- **Why does `execute_node()` connect `post_l3_main_nodes.py` to `execute_agent.py`, `changeset_to_planned_state`, `build_execution_plan`, `ExploreFlashAgent`?**
  _High betweenness centrality (0.221) - this node is a cross-community bridge._
- **Why does `_require_context()` connect `post_l3_main_nodes.py` to `layer_aggregate_node`?**
  _High betweenness centrality (0.196) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `create_unified_planning_graph()` (e.g. with `bootstrap_context_node()` and `apply_human_review_decision()`) actually correct?**
  _`create_unified_planning_graph()` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `analyze_dimension()` (e.g. with `analyze_dimension_node()` and `l1_worker_node()`) actually correct?**
  _`analyze_dimension()` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `analyze_l2_dimension()` (e.g. with `l2_worker_node()` and `enrich_summary_background()`) actually correct?**
  _`analyze_l2_dimension()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Should `execute_agent.py` be split into smaller, more focused modules?**
  _Cohesion score 0.0519219736087206 - nodes in this community are weakly interconnected._