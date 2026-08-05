"""EXECUTE Agent state - execution layer sub-state.

Migrated from agent/gis/execute/state.py per docs/architecture/agent-graph.md §5.

Constructed from GISPipelineState at the execute boundary.
Focused on spatial result production (layout / facility / axis / road).

Peer to ParseAgentState (parse/state.py) - both are sub-states of the
top-level GISPipelineState, exchanged via state mapping at subgraph boundaries.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, Field


def _upsert_worker_results(current: List[Any], updates: List[Any]) -> List[Any]:
    """LangGraph reducer: upsert WorkerResult entries by worker_type.

    Re-running a worker (execution retry) replaces only its own entry while
    preserving the other workers' results, so the fan-out/fan-in merge stays
    correct across retry rounds.
    """
    out = list(current or [])
    for upd in updates or []:
        worker_type = (
            upd.get("worker_type")
            if isinstance(upd, dict)
            else getattr(upd, "worker_type", None)
        )
        out = [
            r
            for r in out
            if (
                r.get("worker_type")
                if isinstance(r, dict)
                else getattr(r, "worker_type", None)
            )
            != worker_type
        ]
        out.append(upd)
    return out


class ExecuteAgentState(BaseModel):
    """EXECUTE Agent internal state.

    Carries upstream inputs (PARSE intent + KG context) and execution outputs
    (allocated GeoJSON, layout layers, validation result).

    Field types intentionally mirror GISPipelineState so the top-level pipeline
    can construct this via ExecuteAgentState(**pipeline_state_subset).
    """

    # ── Identity ──
    session_id: str = ""
    village_name: str = ""

    # ── Upstream inputs (from PARSE + KG) ──
    gis_data: Dict[str, Any] = Field(default_factory=dict)
    gis_bundle: Optional[Any] = None  # GISDataBundle — typed data container
    intent: Any = None  # SpatialPlanningIntent (typed) or dict (legacy)
    operation_sequence: List[Any] = Field(default_factory=list)
    constraint_set: List[Any] = Field(default_factory=list)
    facility_anchors: Optional[List[Dict[str, Any]]] = None

    # ── SELECT output (site selection + land design briefs) ──
    site_selection: Optional[Any] = None  # SiteSelectionDecision (typed) — SELECT subgraph output
    land_design_briefs: List[Any] = Field(default_factory=list)  # list[LandDesignBrief] — SELECT output
    parcel_changes: List[Any] = Field(default_factory=list)  # list[ParcelChange] — accumulated by Land Design Worker nodes
    parcel_changeset: Optional[Any] = None  # ParcelChangeSet — final aggregated changeset

    # ── KG context (read-only view from KGManager) ──
    kg_turtle: str = ""
    kg_constraints: List[Dict[str, Any]] = Field(default_factory=list)
    kg_adjacency_map: Dict[str, List[str]] = Field(default_factory=dict)
    kg_session_ref: str = ""
    kg_three_lines: List[Dict[str, Any]] = Field(default_factory=list)
    kg_protected_parcels_detail: List[Dict[str, Any]] = Field(default_factory=list)
    kg_vne_summary: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Execution outputs ──
    allocated_geojson: Dict[str, Any] = Field(default_factory=dict)
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    execution_errors: List[Dict[str, Any]] = Field(default_factory=list)
    # P0: 结构化未解析目标（禁止静默丢弃候选失败）
    unresolved_targets: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Wave O: multi-worker subgraph ──
    parcel_by_bsm: Dict[str, Any] = Field(default_factory=dict)  # bsm -> parcel (prepared once)
    execution_plan: Optional[Any] = None  # ExecutionPlan — compiled by prepare_inputs
    ports: Optional[Any] = None  # PlanningPorts — injected zone_allocator/road_planner
    worker_results: Annotated[List[Any], _upsert_worker_results] = Field(default_factory=list)  # list[WorkerResult]
    worker_conflict_diagnostics: List[Dict[str, Any]] = Field(default_factory=list)  # BSM conflicts from merge
    planned_state: Optional[Any] = None  # PlannedState — produced by planned_state_builder
    execution_review_report: Dict[str, Any] = Field(default_factory=dict)  # execution_review diagnostics
    geometry_materialize_report: Dict[str, Any] = Field(default_factory=dict)  # geometry confirmation

    # ── Validation (Worker-Evaluator loop) ──
    validation_result: Dict[str, Any] = Field(default_factory=dict)
    validation_report: Optional[Any] = None  # ValidationReport — typed VALIDATE output
    reconciliation_report: Optional[Any] = None  # ReconciliationReport — typed RECONCILE output (Wave M wires)
    delivery_manifest: Optional[Any] = None  # DeliveryManifest — DELIVER output (Wave M wires)
    validation_round: int = 0
    constraint_adjustments: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Sub-task routing ──
    tasks_to_run: List[str] = Field(default_factory=list)

    # ── Messages (LangGraph accumulated) ──
    messages: List[Any] = Field(default_factory=list)


__all__ = ["ExecuteAgentState"]
