"""Shared stage boundary for immutable artifacts and typed completions."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.contracts.artifacts import ArtifactRef
from app.workflow.state import WorkflowState


class StageCommand(BaseModel):
    """Explicit inputs passed from the workflow checkpoint to one stage."""

    run_id: str
    branch_id: str
    context_ref: dict[str, Any]
    input_refs: dict[str, ArtifactRef] = Field(default_factory=dict)
    attempt: int = 1


class StageCompletion(BaseModel):
    """The only result shape a workflow stage may return to the graph."""

    stage: str
    output_refs: dict[str, ArtifactRef] = Field(default_factory=dict)
    gate_ref: ArtifactRef
    event_refs: list[str] = Field(default_factory=list)


_KEY_BY_TYPE = {
    "GroundingResult": "grounding_result",
    "DemandPortfolio": "demand_portfolio",
    "SuitabilitySurface": "suitability_surface",
    "PortfolioDecision": "portfolio_decision",
    "SiteSelectionDecision": "site_selection",
    "ParcelChangeSet": "parcel_changeset",
    "PlannedState": "planned_state",
    "ValidationReport": "validation_report",
    "ReconciliationReport": "reconciliation_report",
    "DeliveryManifest": "delivery_manifest",
    "PlanningProgram": "planning_program",
    "IntentCompilationResult": "target_projection",
    "ExecutionPlan": "execution_plan",
    "ExecutionResult": "execution_result",
    "RenderLayers": "render_layers",
    "DeliverySpatialSnapshot": "delivery_spatial_snapshot",
    "DeferralLedger": "deferral_ledger",
    "LayoutConfigs": "layout_configs",
    "ExecutionDiagnostics": "execution_diagnostics",
    "RepairDirectiveCompilation": "repair_directives",
    "RepairImpactPlan": "repair_impact",
    "GlobalZoneAllocationResult": "global_zone_allocation",
    "ExportResult": "export_result",
    "RenderArtifacts": "render_artifacts",
}


def persist_stage_artifact(
    state: dict[str, Any],
    stage: str,
    schema_id: str,
    payload: Any,
) -> dict[str, Any]:
    """Persist one stage result through the sole CAS boundary."""

    from app.infrastructure.artifacts.runtime import ArtifactReplayError, store_artifact

    key = _KEY_BY_TYPE.get(schema_id, schema_id.lower())
    retry = state.get("retry") or state.get("retry_counts") or {}
    attempt = int(retry.get(stage, 0)) + 1
    try:
        return store_artifact(
            state,
            key,
            stage,
            schema_id,
            payload,
            attempt=attempt,
        )
    except ArtifactReplayError:
        raise
    except Exception as exc:
        raise ArtifactReplayError(
            f"failed to persist {schema_id} artifact in {stage}: {exc}"
        ) from exc


def persist_gate_decision(
    state: dict[str, Any],
    stage: str,
    gate: Any,
    *,
    output_refs: dict[str, Any] | None = None,
) -> ArtifactRef:
    """Persist a gate as an immutable CAS artifact and return its descriptor.

    Gate decisions are not named stage outputs, so they are stored as an
    immutable blob and carried by the root ``gate_ref``.  The descriptor is
    deliberately independent of filesystem paths and can be replayed from a
    checkpoint after process restart.
    """

    from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
    from app.infrastructure.artifacts.runtime import ARTIFACT_SCHEMA_VERSION
    from app.infrastructure.paths import run_tmp_root
    from app.contracts.workflow.workflow_contracts import GateDecision

    decision = gate if isinstance(gate, GateDecision) else GateDecision.model_validate(gate)
    run_id = str(state.get("run_id") or state.get("session_id") or "")
    branch_id = str(state.get("branch_id") or "main")
    if not run_id:
        raise ValueError("gate artifact requires run_id")
    refs = {
        **dict(state.get("artifact_refs") or {}),
        **dict(output_refs or {}),
    }
    parent_digests: dict[str, str] = {}
    for key, value in refs.items():
        if not value:
            continue
        descriptor = value if isinstance(value, ArtifactRef) else ArtifactRef.model_validate(value)
        parent_digests[str(key)] = descriptor.digest
    repository = ContentAddressedArtifactRepository(run_tmp_root())
    return repository.put_json(
        decision.model_dump(mode="json"),
        schema_id="GateDecision",
        schema_version=ARTIFACT_SCHEMA_VERSION,
        producer_stage=stage,
        run_id=run_id,
        branch_id=branch_id,
        parent_digests=parent_digests,
        provenance={
            "artifact_key": f"{stage}_gate",
            "context_ref": dict(state.get("context_ref") or {}),
            "context_fingerprint": str(state.get("context_fingerprint") or ""),
        },
    )


def command_from_state(state: dict[str, Any], stage: str) -> StageCommand:
    """Build a typed command from explicit checkpoint references."""

    refs = {
        key: ArtifactRef.model_validate(value)
        for key, value in (state.get("artifact_refs") or {}).items()
        if value
    }
    return StageCommand(
        run_id=str(state.get("run_id") or state.get("session_id") or ""),
        branch_id=str(state.get("branch_id") or "main"),
        context_ref=dict(state.get("context_ref") or {}),
        input_refs=refs,
        attempt=int((state.get("retry") or state.get("retry_counts") or {}).get(stage, 0)) + 1,
    )


__all__ = [
    "StageCommand",
    "StageCompletion",
    "command_from_state",
    "persist_gate_decision",
    "persist_stage_artifact",
]
