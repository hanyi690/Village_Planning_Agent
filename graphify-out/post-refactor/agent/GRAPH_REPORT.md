# Graph Report - C:\Users\24957\AppData\Local\Temp\opencode\gfx-stage  (2026-08-08)

## Corpus Check
- cluster-only mode — file stats not available

## Summary
- 1206 nodes · 2277 edges · 72 communities (64 shown, 8 thin omitted)
- Extraction: 91% EXTRACTED · 9% INFERRED · 0% AMBIGUOUS · INFERRED: 210 edges (avg confidence: 0.77)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `ecc7e2d0`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- Community 0
- Community 1
- Community 2
- Community 3
- Community 4
- Community 5
- Community 6
- Community 7
- Community 8
- Community 9
- Community 10
- Community 11
- Community 12
- Community 13
- Community 14
- Community 15
- Community 16
- Community 17
- Community 18
- Community 19
- Community 20
- Community 21
- Community 22
- Community 23
- Community 24
- Community 25
- Community 26
- Community 27
- Community 28
- Community 29
- Community 30
- Community 31
- Community 32
- Community 33
- Community 34
- Community 35
- Community 36
- Community 37
- Community 38
- Community 39
- Community 40
- Community 41
- Community 42
- Community 43
- Community 44
- Community 45
- Community 46
- Community 47
- Community 48
- Community 49
- Community 50
- Community 51
- Community 52
- Community 53
- Community 54
- Community 55
- Community 56
- Community 57
- Community 58
- Community 59
- Community 60
- Community 61
- Community 62
- Community 63
- Community 64
- Community 65
- Community 66
- Community 67
- Community 68
- Community 69
- Community 70

## God Nodes (most connected - your core abstractions)
1. `ExecuteAgentState` - 31 edges
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

## Communities (72 total, 8 thin omitted)

### Community 0 - "Community 0"
Cohesion: 0.09
Nodes (59): _accumulate_gate(), _adopt_context(), _collect_human_items(), collect_human_review_items(), _context_version(), deliver_node(), _detect_retry_exhaustion_stage(), _dump() (+51 more)

### Community 1 - "Community 1"
Cohesion: 0.07
Nodes (55): CandidateParcel, DemandPoint, PlacementDecision, ScoredCandidate, _breakdown_from_scored(), build_land_design_brief(), build_site_selection_decision(), _candidate_site_to_parcels() (+47 more)

### Community 2 - "Community 2"
Cohesion: 0.08
Nodes (52): ClassificationRef, Any, EXECUTE Agent state - execution layer sub-state.  Migrated from agent/gis/execut, LangGraph reducer: upsert WorkerResult entries by worker_type.      Re-running a, _upsert_worker_results(), build_parcel_change_set(), _classification(), design_all() (+44 more)

### Community 3 - "Community 3"
Cohesion: 0.09
Nodes (39): build_candidate_site(), ground_aggregate(), Any, CandidateSite, GroundingResult, PlanningContext, SpatialReferenceSpec, GROUND subgraph aggregate - deterministic orchestrator over SpatialResolver.  Co (+31 more)

### Community 4 - "Community 4"
Cohesion: 0.07
Nodes (36): AgentState, create_initial_state(), DimensionSummary, Any, Single canonical state factory for production and tests.  All state construction, StateFactory, _merge_artifact_refs(), _merge_config() (+28 more)

### Community 5 - "Community 5"
Cohesion: 0.11
Nodes (39): SimpleNamespace, _check_id_to_stage(), _check_to_issue(), Any, ValidationCheck, ValidationReport, VALIDATE subgraph — deterministic orchestration of the 9 checks into a typed Val, Map a check to its issues_by_stage key (the responsible_stage Literal value as-i (+31 more)

### Community 6 - "Community 6"
Cohesion: 0.09
Nodes (30): ArtifactReplayError, context_ref_for(), _jsonable(), load_artifact(), migrate_legacy_artifacts(), payload_checksum(), Any, Reference-only workflow state helpers.  The graph stores small references and re (+22 more)

### Community 7 - "Community 7"
Cohesion: 0.11
Nodes (31): _extract_area_ratio(), _feature_props(), format_bound_spatial_intent(), _match_category_code(), _project_category(), Any, SpatialPlanningIntent, Strict, tool-free conversion of Explore/Binder artifacts to planning intent.  Mi (+23 more)

### Community 8 - "Community 8"
Cohesion: 0.11
Nodes (28): InterventionDependency, _dedup(), _dedup_by_id(), _dedup_dependencies(), enrich_program_from_upstream(), l3_aggregate(), merge_program_fragments(), Any (+20 more)

### Community 9 - "Community 9"
Cohesion: 0.09
Nodes (28): build_deliverables_from_export(), _build_planned_view(), build_traceability_from_coverage(), collect_upstream_human_items(), deliver_aggregate(), CoverageMatrix, DeliveryManifest, HumanItem (+20 more)

### Community 10 - "Community 10"
Cohesion: 0.13
Nodes (21): _action_for(), _chunks(), _domain_for(), explore_planning_text(), ExploreFlashAgent, _instructions_from_l3_table(), _mentions(), Any (+13 more)

### Community 11 - "Community 11"
Cohesion: 0.16
Nodes (26): analyze_dimension_node(), apply_human_review_decision(), await_human_review(), create_unified_planning_graph(), execute_tools_node(), prepare_human_review(), publish_human_review_pause(), Any (+18 more)

### Community 12 - "Community 12"
Cohesion: 0.13
Nodes (24): _dedup(), _dedup_location_facts(), _dedup_sources(), l1_aggregate(), merge_fragments(), Any, EvidenceSource, L1Snapshot (+16 more)

### Community 13 - "Community 13"
Cohesion: 0.13
Nodes (23): _dedup(), _dedup_sources(), l2_aggregate(), merge_strategy_fragments(), Any, EvidenceSource, L2Strategy, L2 aggregate node - merge L2StrategyFragments into L2Strategy.  Wave D decision: (+15 more)

### Community 14 - "Community 14"
Cohesion: 0.24
Nodes (23): _as_dict(), _default_kg_retry_adapter(), execute_road_planning_from_agent_state(), _fc(), _gis_payload(), _infer_action(), _intent_road_targets(), _layer_config() (+15 more)

### Community 15 - "Community 15"
Cohesion: 0.13
Nodes (21): analyze_dimension(), _build_prompt(), _build_revision_completed(), create_dimension_state(), _dependency_summary(), _extract_intent_targets(), _extract_landuse_metrics(), _extract_natural_villages() (+13 more)

### Community 16 - "Community 16"
Cohesion: 0.14
Nodes (20): enrich_summary_background(), Background task: Flash-LLM summary enrichment + DB update. Non-fatal., L3 PLAN subgraph - independent worker.  L3 detail planning has its own worker (a, analyze_l3_dimension(), _build_prompt(), _build_revision_completed(), _dependency_summary(), _extract_natural_villages() (+12 more)

### Community 17 - "Community 17"
Cohesion: 0.13
Nodes (20): L4 write-back node: persist planned entities back to KG., Write L4 planned entities (PlannedParcel, PlannedZone, PlannedFacility, etc.) to, _write_l4_node(), _axis_target_to_planned_axis(), _change_to_planned_parcel(), changeset_to_planned_state(), _facility_target_to_planned_facility(), _geometry_area_ha() (+12 more)

### Community 18 - "Community 18"
Cohesion: 0.20
Nodes (19): CoverageMatrixRow, build_coverage_matrix(), _chain_status(), check_l3_l4_target_coverage(), _inc(), CoverageMatrix, ReconciliationInconsistency, ReconciliationReport (+11 more)

### Community 19 - "Community 19"
Cohesion: 0.13
Nodes (18): build_execute_agent_graph(), EXECUTE Agent - spatial execution subgraph.  Migrated from agent/gis/execute/age, Route after execution review: pass -> END, fail -> retry (max 3 rounds -> human), Build the EXECUTE Agent StateGraph.      Wave O multi-worker subgraph:         r, _route_after_execution_review(), ExecuteAgentState, BaseModel, EXECUTE Agent internal state.      Carries upstream inputs (PARSE intent + KG co (+10 more)

### Community 20 - "Community 20"
Cohesion: 0.14
Nodes (19): advance_phase_node(), l1_worker_node(), l2_worker_node(), l3_worker_node(), layer_router_node(), layer_router_noop(), Any, Send (+11 more)

### Community 21 - "Community 21"
Cohesion: 0.15
Nodes (18): publish_dimension_complete(), publish_dimension_delta(), Publish a single DIMENSION_DELTA SSE event (throttling handled by caller)., Publish DIMENSION_COMPLETE SSE event (parses structured_summary JSON)., L2 STRATEGIZE subgraph - independent worker.  L2 strategy analysis has its own w, analyze_l2_dimension(), _build_prompt(), _build_revision_completed() (+10 more)

### Community 22 - "Community 22"
Cohesion: 0.21
Nodes (17): Return the worker node name matching ``phase`` (layer1/2/3 -> l1/l2/l3_worker)., Build the Send list for ready dimensions of ``phase``.      Same-layer dependenc, _ready_dispatch(), _worker_for_phase(), get_layer_dimensions(), _phase_to_layer(), after_analysis(), after_conversation() (+9 more)

### Community 23 - "Community 23"
Cohesion: 0.16
Nodes (18): DependencyError, _display_report(), load_dependency_reports(), load_layered_dependency_reports(), publish_dimension_start(), Any, RAGRetrievalLog, Shared dimension runtime infrastructure for L1/L2/L3 analysis nodes.  Extracted (+10 more)

### Community 24 - "Community 24"
Cohesion: 0.13
Nodes (18): _allocated_geojson_from_changes(), _assign_custom_zone_features(), _build_custom_planning_layer(), _function_zone_layer(), Any, Legacy layer helpers kept for zone/allocated/custom layer construction.  These h, Build the custom_planning_zone layer via the vocabulary-driven generator (no MIP, Build the function_zone layer from reclassified ParcelChange entries. (+10 more)

### Community 25 - "Community 25"
Cohesion: 0.21
Nodes (17): _change_after_code(), _change_after_wkt(), _change_bsm(), _dedup_layout_configs(), _detect_bsm_conflicts(), merge_worker_results(), Any, ParcelChangeSet (+9 more)

### Community 26 - "Community 26"
Cohesion: 0.18
Nodes (17): _prepare_inputs_node(), Prepare execution inputs: parcel_by_bsm + constraint adjustments + ExecutionPlan, _build_parcel_by_bsm(), _footprint_geometry(), _intent_list(), _parcel_from_feature(), _parcel_geometry(), Any (+9 more)

### Community 27 - "Community 27"
Cohesion: 0.32
Nodes (17): _build_accessibility(), _build_area_conservation(), _build_check_summary(), _build_gate_decision(), _build_provenance(), _build_spatial_checks(), _build_stage_attribution(), build_validate_review_package() (+9 more)

### Community 28 - "Community 28"
Cohesion: 0.16
Nodes (14): EvidenceBundle, ExplorationRequest, ExplorationResult, EvidenceFact, EvidenceSource, Extract 【INSTRUCTION】 sections from reports as structured evidence.      Instruc, retrieve_from_instructions(), SpatialCognitionEvidence (+6 more)

### Community 29 - "Community 29"
Cohesion: 0.24
Nodes (15): _default_dlbm_for(), extract_vocabulary_deterministic(), extract_vocabulary_from_reports(), _extract_vocabulary_llm(), _is_protection(), _parse_rules(), Any, L3 报告 → session 功能区词汇表提取器（LLM 自由给色，确定性 fallback）。  Migrated from agent/gis/vocab (+7 more)

### Community 30 - "Community 30"
Cohesion: 0.20
Nodes (16): _coerce_specs(), compile_program(), compile_program_async(), CompilationPatch, GateDecision, IntentCompilationResult, PlanningProgram, SpatialReferenceSpec (+8 more)

### Community 31 - "Community 31"
Cohesion: 0.19
Nodes (15): _build_prompt(), CompilationPatchList, _finalize_patches(), generate_llm_patches(), _is_patchable_path(), BaseModel, CompilationPatch, IntentCompilationResult (+7 more)

### Community 32 - "Community 32"
Cohesion: 0.33
Nodes (15): _build_area_drift(), _build_backward_lineage(), _build_chain_coverage(), _build_coverage_summary(), _build_gate_decision(), _build_inconsistency_list(), _build_provenance(), build_reconcile_review_package() (+7 more)

### Community 33 - "Community 33"
Cohesion: 0.36
Nodes (14): _build_classification(), build_deliver_review_package(), _build_deliverables(), _build_exit_gate(), _build_gate_decision(), _build_human_items(), _build_provenance(), _build_statutory_completeness() (+6 more)

### Community 34 - "Community 34"
Cohesion: 0.25
Nodes (14): build_parse_review_package(), _collect_target_meta(), _iter_targets(), Any, ArtifactRef, GateDecision, IntentCompilationResult, SpatialReferenceSpec (+6 more)

### Community 35 - "Community 35"
Cohesion: 0.19
Nodes (8): DataPipeline, Any, Unified data pipeline: structured_summary -> ToolRegistry -> professional_data., Unified tool execution pipeline.      Flow:     1. Read tool config for the dime, Execute tools for a dimension and return aggregated results.          Args:, Read tool names from dimension config (phases.yaml)., Keep only tools that exist in the TOOL_REGISTRY., Build tool execution context from summary and state.

### Community 36 - "Community 36"
Cohesion: 0.19
Nodes (11): evaluate_parse_gate(), _is_empty_intent(), GateDecision, IntentCompilationResult, PARSE gate node - 4-route evaluator (Hybrid routing).  Pure function: IntentComp, PARSE subgraph - deterministic compile/repair/revise pipeline.  Wave F: PARSE is, IntentCompilationResult, ParseDiagnostic (+3 more)

### Community 37 - "Community 37"
Cohesion: 0.25
Nodes (13): _apply_append(), apply_patches(), _apply_remove(), _apply_update(), _is_supported_path(), Any, CompilationPatch, IntentCompilationResult (+5 more)

### Community 38 - "Community 38"
Cohesion: 0.30
Nodes (11): build_render_layers(), _feature_collection(), _function_zone_layer(), _normalize_layer(), Any, Render-layer derivation for the DELIVER stage.  Builds the ``render_result`` lay, Derive the renderable layer list from PlannedState + layout_configs.      Priori, Parse a WKT string into a GeoJSON geometry dict; None on failure. (+3 more)

### Community 39 - "Community 39"
Cohesion: 0.24
Nodes (11): build_execution_plan(), _intent_list(), Any, ExecutionPlan builder — thin layer over intent targets + SELECT output.  Wave O:, Read a list field off a typed intent or a legacy intent dict., Unwrap an IntentCompilationResult to its typed SpatialPlanningIntent., Defensively read an identifier off a typed target / dict / bare value., From intent targets + site_selection generate WorkerTask list + dependency graph (+3 more)

### Community 40 - "Community 40"
Cohesion: 0.24
Nodes (10): ChatPromptTemplate, _build_prompt(), conversation_node(), _get_llm_with_tools(), Any, Conversation node — central router (brain).  Binds advance_planning_intent / gis, Lazy-init the LLM+tools chain (cached across calls)., Build the ChatPromptTemplate with phase / config filled in. (+2 more)

### Community 41 - "Community 41"
Cohesion: 0.18
Nodes (9): _checkpoint_safe(), _checkpoint_safe_node(), _execution_error(), Any, Shared node helpers: checkpoint-safe serialization and execution error accumulat, Convert NumPy scalar containers to checkpoint-serializable primitives., EXECUTE routing and input-preparation nodes., Determine which execution sub-tasks to run based on intent.      Layout is the c (+1 more)

### Community 42 - "Community 42"
Cohesion: 0.29
Nodes (10): _content_to_review_package(), _load_program(), parse_aggregate(), Any, ArtifactRef, ReviewPackage, Top-level PARSE aggregate - orchestration + public API.  Wave F: COMPILE mode is, Resolve the PlanningProgram from state (object, or artifact via store). (+2 more)

### Community 43 - "Community 43"
Cohesion: 0.27
Nodes (10): _invoke_extraction(), layer_completion_check(), _maybe_extract_bindings(), Any, Layer Completion Check Node  Runs AFTER reducer merges parallel dimension result, Invoke the enrichment hook while keeping older test/plugin hooks valid., Check if current layer is complete after reducer merges parallel results.      T, Persist a versioned session bundle snapshot at a layer boundary.      Non-fatal: (+2 more)

### Community 44 - "Community 44"
Cohesion: 0.31
Nodes (10): _dominant_stage(), _error_counts(), evaluate_reconcile_gate(), GateDecision, ReconciliationReport, RECONCILE gate - 4-way responsibility router over a ReconciliationReport.  Mirro, Count error-severity inconsistencies per responsible_stage (skips empty)., Return (stage, count) of the unique max, or (None, max) on a tie. (+2 more)

### Community 45 - "Community 45"
Cohesion: 0.27
Nodes (9): ToolMessage, execute_tools_node(), _invoke_single(), _normalize_name(), Any, Tool execution node — dispatches tool calls via LangChain BaseTool.ainvoke.  Fil, Normalize tool name: resolve PascalCase aliases to registered snake_case., Invoke a single tool call with SSE publishing. (+1 more)

### Community 46 - "Community 46"
Cohesion: 0.31
Nodes (10): _dominant_stage(), _error_counts(), evaluate_validate_gate(), GateDecision, ValidationReport, VALIDATE gate evaluator - 5-way responsibility router over a ValidationReport., Count error-severity ValidationIssues per stage (skips empty stages)., Return (stage, count) of the unique max, or (None, max) on a tie. (+2 more)

### Community 47 - "Community 47"
Cohesion: 0.36
Nodes (9): audited_stage(), _checksum(), _gate_route(), _input_snapshot(), _jsonable(), Any, Stage-level audit wrapper for the real session planning graph.  The wrapper reco, Decorate an async graph node with started/completed/failed reports. (+1 more)

### Community 48 - "Community 48"
Cohesion: 0.36
Nodes (8): _blocking_categories(), deliver_gate_route(), evaluate_deliver_gate(), DeliveryManifest, GateDecision, DELIVER gate - 3-way router over a DeliveryManifest.  Mirrors the RECONCILE/VALI, Categorize blocking human items by their item_id prefix., Return the deterministic route: "PASS"|"RETRY_VALIDATE"|"HUMAN".

### Community 49 - "Community 49"
Cohesion: 0.28
Nodes (8): GISPipelineInput, GISPipelineOutput, GISPipelineState, BaseModel, GIS Agent state — unified Pydantic BaseModel following LangGraph best practices., Fields the API caller must provide to invoke the pipeline., Fields the pipeline returns to the frontend after completion., Complete internal state of the GIS layout pipeline.      All nodes in the StateG

### Community 50 - "Community 50"
Cohesion: 0.33
Nodes (8): _allocate_empty_zone_targets(), Any, ParcelChange, Zone worker node: deterministic zone reclassification + MIP allocation., ZoneAllocatorPort from injected ports, else the default PuLP adapter., MIP-allocate parcels for zone targets with no candidate_bsms.      The unclaimed, _resolve_zone_allocator(), _zone_target_key()

### Community 51 - "Community 51"
Cohesion: 0.29
Nodes (3): PlanningPhase, Enum, Phase machine: PlanningPhase enum + layer/phase/wave conversion helpers.  Migrat

### Community 52 - "Community 52"
Cohesion: 0.38
Nodes (6): Save a StepReport. Non-fatal on error., save_step_report(), compare_intent_to_layout(), Any, EXPLORE verification — compare L3 text targets vs L4 geometry (post-execute)., save_explore_verification()

### Community 53 - "Community 53"
Cohesion: 0.33
Nodes (6): _adjustment_get(), _apply_constraint_adjustments(), Any, Constraint adjustment helpers for EXECUTE input preparation., Apply constraint_adjustments (legacy {zone, delta_ha} shape) to zone targets., Read a field from a legacy adjustment dict or an attribute-carrying object.

### Community 54 - "Community 54"
Cohesion: 0.33
Nodes (6): _extract_spatial_findings(), EvidenceFact, EvidenceSource, Report retriever - search L1/L2/L3 AnalysisReports for spatial evidence., Search L1/L2/L3 reports for spatial findings relevant to the dimension.      Ret, retrieve_from_reports()

### Community 55 - "Community 55"
Cohesion: 0.38
Nodes (6): _format_dict_result(), generate_professional_data_section(), Any, Unified professional data formatter for all planning layers.  Replaces the dupli, Format professional_data dict into prompt-injectable text.      Args:         di, Format a dict-type tool result into a prompt section.

### Community 56 - "Community 56"
Cohesion: 0.40
Nodes (5): _axis_worker(), _axis_worker_node(), WorkerResult, Axis worker node: development-axis layer (decision-driven from intent)., Axis worker: development-axis layer (decision-driven from intent).

### Community 57 - "Community 57"
Cohesion: 0.40
Nodes (5): _facility_worker(), _facility_worker_node(), WorkerResult, Facility worker node: decision-driven facility footprint placement., Facility worker: decision-driven facility footprint placement.      Builds a Pol

### Community 58 - "Community 58"
Cohesion: 0.40
Nodes (5): _project_worker(), _project_worker_node(), WorkerResult, Project worker node: place each L3 project on the SSD-selected parcel., Project worker: place each L3 project on the SSD-selected parcel.      Consumes

### Community 59 - "Community 59"
Cohesion: 0.40
Nodes (5): WorkerResult, Road worker node: planned road network generation., Road worker: planned road network generation.      Primary path: the injected ``, _road_worker(), _road_worker_node()

### Community 60 - "Community 60"
Cohesion: 0.33
Nodes (5): EvidenceFact, SpatialCognitionEvidence, KG retriever - session KG cognition + topology facts for L2/L3., Retrieve KG three-layer cognition + topology facts.      Returns (facts, cogniti, retrieve_from_kg()

### Community 61 - "Community 61"
Cohesion: 0.40
Nodes (4): EvidenceFact, EvidenceSource, Retrieve spatial group statistics from the VillageBundle snapshot.      Returns, retrieve_from_bundle()

### Community 62 - "Community 62"
Cohesion: 0.50
Nodes (4): generate_summary(), Generate structured summary JSON string with fallback., _generate_summary(), Generate structured JSON summary for a dimension report (delegates to shared run

## Knowledge Gaps
- **8 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `create_unified_planning_graph()` connect `Community 11` to `Community 6`, `Community 40`, `Community 43`, `Community 20`, `Community 22`?**
  _High betweenness centrality (0.250) - this node is a cross-community bridge._
- **Why does `execute_node()` connect `Community 0` to `Community 17`, `Community 10`, `Community 19`, `Community 39`?**
  _High betweenness centrality (0.211) - this node is a cross-community bridge._
- **Why does `_require_context()` connect `Community 0` to `Community 6`?**
  _High betweenness centrality (0.190) - this node is a cross-community bridge._
- **Are the 22 inferred relationships involving `create_unified_planning_graph()` (e.g. with `bootstrap_context_node()` and `apply_human_review_decision()`) actually correct?**
  _`create_unified_planning_graph()` has 22 INFERRED edges - model-reasoned connections that need verification._
- **Are the 15 inferred relationships involving `analyze_dimension()` (e.g. with `analyze_dimension_node()` and `l1_worker_node()`) actually correct?**
  _`analyze_dimension()` has 15 INFERRED edges - model-reasoned connections that need verification._
- **Are the 12 inferred relationships involving `analyze_l2_dimension()` (e.g. with `l2_worker_node()` and `enrich_summary_background()`) actually correct?**
  _`analyze_l2_dimension()` has 12 INFERRED edges - model-reasoned connections that need verification._
- **Should `Community 0` be split into smaller, more focused modules?**
  _Cohesion score 0.09209039548022599 - nodes in this community are weakly interconnected._