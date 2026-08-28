"""EXECUTE Agent state - execution layer sub-state.

Execution state follows the current EXECUTE boundary in docs/design/06_SELECT_EXECUTE_AND_CODE.md.

Constructed from the canonical planning bundle at the execute boundary.
Focused on spatial result production (layout / facility / axis / road).

Stage-local state is exchanged through
typed artifacts at subgraph boundaries.
"""

from __future__ import annotations

from typing import Annotated, Any, Dict, List, Optional

from pydantic import BaseModel, Field

from app.contracts.execute.materialization_contracts import LandDesignBrief
from app.contracts.select.approval import ApprovedExecutionInput


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
        task_id = (
            upd.get("task_id")
            if isinstance(upd, dict)
            else getattr(upd, "task_id", "")
        ) or ""
        out = [
            r
            for r in out
            if (
                r.get("worker_type")
                if isinstance(r, dict)
                else getattr(r, "worker_type", None)
            )
            != worker_type
            or (
                task_id
                and (
                    r.get("task_id")
                    if isinstance(r, dict)
                    else getattr(r, "task_id", "")
                )
                != task_id
            )
        ]
        out.append(upd)
    return out


class ExecuteAgentState(BaseModel):
    """EXECUTE Agent internal state.

    Carries upstream target projection + KG context and execution outputs
    (allocated GeoJSON, layout layers, validation result).

    Stage-local fields are built from the canonical planning bundle and typed
    artifact inputs; raw GIS is not copied into this state.
    """

    # ── Identity ──
    session_id: str = ""
    village_name: str = ""

    # ── Upstream inputs (from target projection + KG) ──
    spatial_workspace: Optional[Any] = None  # data-owned SpatialWorkspace
    operation_sequence: List[Any] = Field(default_factory=list)
    constraint_set: List[Any] = Field(default_factory=list)
    facility_anchors: Optional[List[Dict[str, Any]]] = None
    # Grounded execution candidates keyed by stable candidate id.  Workers
    # consume this immutable geometry instead of pretending every candidate
    # is an existing cadastral parcel/BSM.
    candidate_geometry_by_id: Dict[str, Any] = Field(default_factory=dict)

    # ── Approved SELECT output (scenario-bound materializer inputs) ──
    land_design_briefs: List[LandDesignBrief] = Field(default_factory=list)  # list[LandDesignBrief] — SELECT output
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
    allocation_summary: Dict[str, Any] = Field(default_factory=dict)
    layout_configs: List[Dict[str, Any]] = Field(default_factory=list)
    action_results: List[Any] = Field(default_factory=list)
    execution_result: Optional[Any] = None
    execution_errors: List[Dict[str, Any]] = Field(default_factory=list)
    # P0: 结构化未解析目标（禁止静默丢弃候选失败）
    unresolved_targets: List[Dict[str, Any]] = Field(default_factory=list)

    # ── Wave O: multi-worker subgraph ──
    parcel_by_bsm: Dict[str, Any] = Field(default_factory=dict)  # bsm -> parcel (prepared once)
    execution_plan: Optional[Any] = None  # ExecutionPlan — built upstream (post-L3 select)
    approved_execution_input: Optional[ApprovedExecutionInput] = None
    approved_input_fingerprint: str = ""
    ports: Optional[Any] = None  # PlanningPorts — injected zone_allocator/road_planner
    worker_results: Annotated[List[Any], _upsert_worker_results] = Field(default_factory=list)  # list[WorkerResult]
    task_schedule: Optional[Any] = None
    execution_trace: List[Dict[str, Any]] = Field(default_factory=list)
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

    # ── VALIDATE repair directives (REBUILD_GEOMETRY / REQUIRE_SOURCE_EVIDENCE) ──
    repair_directives: Dict[str, Any] = Field(default_factory=dict)
    required_source_evidence_target_ids: List[str] = Field(default_factory=list)

    # ── Sub-task routing ──
    tasks_to_run: List[str] = Field(default_factory=list)

    # ── Messages (LangGraph accumulated) ──
    messages: List[Any] = Field(default_factory=list)


__all__ = ["ExecuteAgentState"]
