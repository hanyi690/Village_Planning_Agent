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
    "DataResourceCatalogSnapshot": "data_catalog",
    "SessionDataSnapshot": "data_snapshot",
    "DataStageSnapshot": "data_stage",
    "SourceSemanticMappingSnapshot": "schema_mapping_snapshot",
    "SessionWorldModelSnapshot": "world_model_snapshot",
    "CognitionStageSnapshot": "kg_stage",
    "EvidenceStageSnapshot": "evidence_snapshot",
    "GroundingResult": "grounding_result",
    "GroundedPlanningProblem": "scoped_grounding_problem",
    "DemandPortfolio": "demand_portfolio",
    "SuitabilitySurface": "suitability_surface",
    "PortfolioDecision": "portfolio_decision",
    "ParcelChangeSet": "parcel_changeset",
    "SpatialChangeSet": "spatial_changeset",
    "PlannedEntitySet": "planned_entity_set",
    "PlannedRepresentationSet": "planned_representation_set",
    "ExecutionTrace": "execution_trace",
    "PlannedState": "planned_state",
    "ValidationReport": "validation_report",
    "FinalManifest": "final_manifest",
    "DeliveryManifest": "delivery_manifest",
    "PlanningProgram": "planning_program",
    "IntentCompilationResult": "target_projection",
    "ExecutionPlan": "execution_plan",
    "PlanningScenario": "planning_scenario",
    "ScenarioSet": "scenario_set",
    "ApprovedExecutionInput": "approved_execution_input",
    "ValidationCertificate": "validation_certificate",
    "FinalScenarioValidation": "final_relation_validation",
    "ExecutionResult": "execution_result",
    "ExecutionStaging": "execution_staging",
    "RenderLayers": "render_layers",
    "DeliverySpatialSnapshot": "delivery_spatial_snapshot",
    "DeferralLedger": "deferral_ledger",
    "LayoutConfigs": "layout_configs",
    "ExecutionDiagnostics": "execution_diagnostics",
    "RepairDirectiveCompilation": "repair_directives",
    "RepairImpactPlan": "repair_impact",
    "ExportResult": "export_result",
    "RenderArtifacts": "render_artifacts",
    "EvidenceObservationSnapshot": "l1_observations",
    "GroundedEntityBindingSnapshot": "l1_bindings",
    "L1ObservationSnapshot": "l1_observation_snapshot",
    "L1BindingSnapshot": "l1_binding_snapshot",
    "L1FinalProduct": "l1_final_product",
    "L1ProductManifest": "l1_product_manifest",
    "DataAdmissionReceipt": "data_admission_receipt",
    "DataAdmissionGap": "data_admission_gap",
    "SourceSemanticClassificationSnapshot": "source_semantic_classification",
    "SolverSubproblemPlan": "solver_subproblem_plan",
    "SolverReadiness": "solver_readiness",
    "PlanningTaskGraph": "planning_task_graph",
}


# One authoritative output must be explicitly bound into every cognition
# gate.  Downstream consumers compare this digest with the exact ref in the
# resumed checkpoint, so a gate from artifact A cannot authorize artifact B.
STAGE_AUTHORITY_OUTPUT_KEYS: dict[str, tuple[str, ...]] = {
    "data": ("data_stage",),
    "kg": ("kg_stage",),
    "evidence": (
        "evidence_snapshot",
        "evidence_external_observations",
        "evidence_gap_ledger",
    ),
    "l1": ("l1_snapshot",),
    "l2": ("l2_strategy",),
    "l3": ("planning_program",),
    "target_projection": ("target_projection",),
    "l1_final": ("l1_product_manifest", "l1_final_product"),
}


def persist_stage_artifact(
    state: dict[str, Any],
    stage: str,
    schema_id: str,
    payload: Any,
    *,
    artifact_key: str | None = None,
) -> dict[str, Any]:
    """Persist one stage result through the sole CAS boundary."""

    from app.infrastructure.artifacts.runtime import ArtifactReplayError, store_artifact

    key = artifact_key or _KEY_BY_TYPE.get(schema_id, schema_id.lower())
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
    from app.infrastructure.artifacts.runtime import (
        ARTIFACT_SCHEMA_VERSION,
        context_ref_for,
    )
    from app.infrastructure.paths import run_tmp_root
    from pathlib import Path
    from app.contracts.workflow.workflow_contracts import GateDecision

    decision = gate if isinstance(gate, GateDecision) else GateDecision.model_validate(gate)
    run_id = str(state.get("run_id") or state.get("session_id") or "")
    branch_id = str(state.get("branch_id") or "main")
    if not run_id:
        raise ValueError("gate artifact requires run_id")
    required_outputs = STAGE_AUTHORITY_OUTPUT_KEYS.get(stage, ())
    supplied_outputs = dict(output_refs or {})
    # Required outputs define the minimum stage authority.  A composite stage
    # may bind additional transition artifacts (for example L1 snapshot +
    # identity-grounding projection + child World Model) into the same gate.
    # Keep those explicit supplied refs in the immutable parent closure rather
    # than silently dropping them.
    normalized_outputs = {
        str(key): value
        for key, value in supplied_outputs.items()
        if value
    }
    missing_outputs = [key for key in required_outputs if not normalized_outputs.get(key)]
    if missing_outputs:
        raise ValueError(
            f"{stage} gate requires explicit authoritative output refs: "
            + ", ".join(missing_outputs)
        )
    parent_digests: dict[str, str] = {}
    for key, value in normalized_outputs.items():
        if not value:
            continue
        descriptor = value if isinstance(value, ArtifactRef) else ArtifactRef.model_validate(value)
        parent_digests[str(key)] = descriptor.digest
    # Gate blobs must live beside the stage artifacts referenced by the same
    # checkpoint.  A resumed worker may have a run-specific artifact root;
    # using the process-global temp root here makes an otherwise valid gate
    # impossible to reload after restart.
    repository = ContentAddressedArtifactRepository(
        Path(str(state.get("artifact_root") or run_tmp_root())).resolve()
    )
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
            "context_ref": context_ref_for(state),
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
    "STAGE_AUTHORITY_OUTPUT_KEYS",
]
