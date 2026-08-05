"""Post-L3 chain state — carries typed artifact references across the chain.

Wave M1: this is the LangGraph state schema for the new post-L3 chain
(PARSE -> GROUND -> SELECT -> EXECUTE -> VALIDATE -> RECONCILE -> DELIVER).
It carries typed artifact references (not raw dicts) between the chain nodes,
plus the shared PlanningContext. Mirrors the ExecuteAgentState convention
(Pydantic BaseModel used directly as a StateGraph state schema).

The upstream L1/L2/L3 aggregate outputs and reports stay on the main AgentState
(accessed via PlanningContext.reports / report_summary_index); this chain state
only carries what the post-L3 nodes consume and produce.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class PostL3ChainState(BaseModel):
    """State flowing through the post-L3 subgraph chain."""

    # ── Identity ──
    session_id: str = ""
    village_name: str = ""
    run_id: str = ""

    # ── Shared PlanningContext (not serialized; rebuilt via context factory) ──
    context: Any = None
    context_version: str = ""

    # ── L3 input (from PlanningContext.reports / L3 aggregate) ──
    planning_program: Any = None  # PlanningProgram (typed)
    l3_program_ref: Dict[str, Any] = Field(default_factory=dict)

    # ── PARSE output ──
    intent: Any = None  # IntentCompilationResult (typed)
    specs: List[Any] = Field(default_factory=list)  # list[SpatialReferenceSpec]
    parse_gate: Any = None  # GateDecision (typed)

    # ── GROUND output ──
    grounding_result: Any = None  # GroundingResult (typed)
    ground_gate: Any = None  # GateDecision (typed)

    # ── SELECT output ──
    site_selection: Any = None  # SiteSelectionDecision (typed)
    land_design_briefs: List[Any] = Field(default_factory=list)  # list[LandDesignBrief]
    select_gate: Any = None  # GateDecision (typed)

    # ── EXECUTE output ──
    planned_state: Any = None  # PlannedState (typed)
    parcel_changeset: Any = None  # ParcelChangeSet (typed)
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    execution_errors: List[Dict[str, Any]] = Field(default_factory=list)
    execute_gate: Any = None

    # ── Artifact refs (FilesystemArtifactStore, Wave O) ──
    grounding_result_ref: Dict[str, Any] = Field(default_factory=dict)
    site_selection_ref: Dict[str, Any] = Field(default_factory=dict)
    parcel_changeset_ref: Dict[str, Any] = Field(default_factory=dict)
    planned_state_ref: Dict[str, Any] = Field(default_factory=dict)
    validation_report_ref: Dict[str, Any] = Field(default_factory=dict)
    reconciliation_report_ref: Dict[str, Any] = Field(default_factory=dict)

    # ── VALIDATE output ──
    validation_report: Any = None  # ValidationReport (typed)
    validate_gate: Any = None  # GateDecision (typed)

    # ── RECONCILE output ──
    reconciliation_report: Any = None  # ReconciliationReport (typed)
    reconcile_gate: Any = None  # GateDecision (typed)

    # ── DELIVER output ──
    delivery_manifest: Any = None  # DeliveryManifest (typed)
    deliver_gate: Any = None  # GateDecision (typed)
    export_result: Optional[Dict[str, Any]] = None
    render_result: List[Dict[str, Any]] = Field(default_factory=list)
    render_artifact: Dict[str, Any] = Field(default_factory=dict)

    # ── Accumulated upstream gates (consumed by DELIVER for pending items) ──
    upstream_gates: List[Any] = Field(default_factory=list)

    # ── Wave M2: retry loop state ──
    retry_counts: Dict[str, int] = Field(default_factory=dict)
    max_retries: int = 3
    error_feedback: Dict[str, str] = Field(default_factory=dict)
    explore_cache: Dict[str, Any] = Field(default_factory=dict)
    human_review_items: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Wave N P5: HITL resume state ──
    human_review_decisions: Any = None  # resume 后回填的审查决策
    status: str = ""  # 可选状态标记（needs_human_review 等）

    # ── Messages ──
    messages: List[Any] = Field(default_factory=list)


__all__ = ["PostL3ChainState"]
