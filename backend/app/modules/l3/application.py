"""Public L3 PLAN facade.

L3 owns claim meaning and program assembly.  Retrieval, context construction,
and structured-output execution are supplied by shared runtimes; this facade
only validates the upstream artifact boundary and reloads the committed
PlanningProgram before returning it to the workflow.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.l1.l1_contracts import L1ObservationSnapshot
from app.contracts.l2.l2_contracts import L2Strategy
from app.contracts.l3.l3_contracts import PlanningProgram
from app.modules.l1.finalization import load_ready_l1_product_manifest


class L3RunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1)
    session_id: str = Field(min_length=1)
    context_version: str = Field(min_length=1)
    l1_snapshot_ref: ArtifactRef
    l2_strategy_ref: ArtifactRef
    l1_product_manifest_ref: ArtifactRef

    @classmethod
    def from_state(cls, state: Mapping[str, Any]) -> "L3RunRequest":
        refs = state.get("artifact_refs") or {}
        if not refs.get("l1_snapshot"):
            raise RuntimeError("L3 requires the canonical l1_snapshot artifact ref")
        if not refs.get("l2_strategy"):
            raise RuntimeError("L3 requires the canonical l2_strategy artifact ref")
        if not refs.get("l1_product_manifest"):
            raise RuntimeError(
                "L3 requires the canonical L1ProductManifest artifact ref"
            )
        return cls(
            run_id=str(state.get("run_id") or state.get("session_id") or ""),
            session_id=str(state.get("session_id") or ""),
            context_version=str(state.get("context_version") or ""),
            l1_snapshot_ref=ArtifactRef.model_validate(refs["l1_snapshot"]),
            l2_strategy_ref=ArtifactRef.model_validate(refs["l2_strategy"]),
            l1_product_manifest_ref=ArtifactRef.model_validate(
                refs["l1_product_manifest"]
            ),
        )


class L3RunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", arbitrary_types_allowed=True)

    request: L3RunRequest
    program: PlanningProgram
    artifact_ref: ArtifactRef
    gate_ref: ArtifactRef
    review_id: str = ""
    state_patch: dict[str, Any] = Field(default_factory=dict)

    def to_state_patch(self) -> dict[str, Any]:
        patch = dict(self.state_patch)
        patch["artifact_refs"] = {
            **dict(patch.get("artifact_refs") or {}),
            "planning_program": self.artifact_ref.model_dump(mode="json"),
            "l3_gate": self.gate_ref.model_dump(mode="json"),
        }
        patch["l3_review_id"] = self.review_id
        return patch


class L3Application:
    """Run the production L3 aggregate and reload its immutable artifact."""

    @staticmethod
    def _load(state: Mapping[str, Any], key: str, model: type[BaseModel]) -> Any:
        from app.infrastructure.artifacts.runtime import load_artifact

        value = load_artifact(dict(state), key, model)
        if value is None:
            raise RuntimeError(f"L3 cannot proceed without a reloaded {key} artifact")
        return value

    def load_l1(self, state: Mapping[str, Any]) -> L1ObservationSnapshot:
        return self._load(state, "l1_snapshot", L1ObservationSnapshot)

    def load_l2(self, state: Mapping[str, Any]) -> L2Strategy:
        return self._load(state, "l2_strategy", L2Strategy)

    @staticmethod
    def require_l2_pass(state: Mapping[str, Any]) -> None:
        """Fail closed when the upstream L2 gate is not a persisted PASS."""

        from app.workflow.state import load_root_gate

        gate = load_root_gate(dict(state), "l2")
        if gate.passed:
            return
        pending = list(gate.pending_requests or [])
        request_ids = ", ".join(
            str(item.request_id)
            for item in pending[:8]
            if str(getattr(item, "request_id", "") or "").strip()
        )
        suffix = f" pending={request_ids}" if request_ids else ""
        raise RuntimeError(
            "L3 requires a persisted L2 PASS gate; "
            f"current route={gate.feedback_route or 'BLOCK'}.{suffix}"
        )

    def load(self, state: Mapping[str, Any]) -> PlanningProgram:
        return self._load(state, "planning_program", PlanningProgram)

    @staticmethod
    def _validate_program_boundary(
        program: PlanningProgram,
        l2: L2Strategy,
    ) -> None:
        """Validate the reloaded L3 artifact, not the in-memory aggregate."""

        forbidden = {
            "entity_ref",
            "geometry_ref",
            "geometry",
            "geometry_wkt",
            "candidate_id",
            "candidate_ids",
            "bsm",
            "bsms",
            "scenario",
            "scenario_id",
            "approval",
            "approval_id",
            "affected_parcel_refs",
            "source_feature_refs",
            "area_range_ha",
            "service_population",
            "road_parameters",
            "linear_parameters",
            "facility_parameters",
            "axis_parameters",
            "polygon_parameters",
            "site_area_parameters",
        }

        def present(value: Any) -> bool:
            return value not in (None, "", [], {}, ())

        def visit(value: Any, path: str = "planning_program") -> None:
            if isinstance(value, dict):
                if (
                    str(value.get("object_ref_kind") or "") == "entity"
                    and present(value.get("object_ref"))
                ):
                    raise RuntimeError(
                        f"L3 artifact contains a concrete entity binding at {path}.object_ref"
                    )
                for key, child in value.items():
                    if str(key).casefold() in forbidden and present(child):
                        raise RuntimeError(
                            f"L3 artifact contains forbidden field {path}.{key}"
                        )
                    visit(child, f"{path}.{key}")
            elif isinstance(value, list):
                for index, child in enumerate(value):
                    visit(child, f"{path}[{index}]")

        visit(program.model_dump(mode="json"))
        target_refs = {item.target_ref for item in program.target_rows}
        intervention_refs = {
            item.target_id or item.intervention_id
            for item in program.interventions
        }
        if target_refs != intervention_refs:
            raise RuntimeError("L3 target rows do not close over admitted interventions")
        if {item.target_ref for item in program.spatial_requirement_rows} != target_refs:
            raise RuntimeError("L3 spatial requirement rows do not close over targets")
        request_by_ref = {
            item.request_ref: item for item in program.candidate_request_rows
        }
        if set(request_by_ref) != {
            item.candidate_request_ref for item in program.target_rows
        }:
            raise RuntimeError("L3 candidate request refs do not close over targets")
        allowed_l2_refs = {
            str(value).strip()
            for value in [
                *[item.objective_id for item in l2.objectives],
                *[item.metric_id for item in l2.metrics],
                *[item.strategy_id for item in l2.strategy_rules],
                *[item.priority_id for item in l2.priority_decisions],
                *[item.structure_id for item in l2.spatial_structure_intents],
                *[item.conflict_id for item in l2.conflict_hypotheses],
            ]
            if str(value).strip()
        }
        for target in program.target_rows:
            if not target.l2_refs or not set(target.l2_refs).issubset(allowed_l2_refs):
                raise RuntimeError(
                    f"L3 target {target.target_ref} has stale or missing L2 refs"
                )

    async def run(self, state: Mapping[str, Any]) -> L3RunResult:
        request = L3RunRequest.from_state(state)
        manifest = load_ready_l1_product_manifest(state)
        if manifest.l1_snapshot_ref != request.l1_snapshot_ref:
            raise RuntimeError(
                "L3 L1ProductManifest does not close over the requested l1_snapshot"
            )
        from app.workflow.stages.support import require_upstream_gates

        require_upstream_gates(
            dict(state),
            ("data", "kg", "evidence", "l1", "l2"),
        )
        l1 = self.load_l1(state)
        l2 = self.load_l2(state)
        from app.infrastructure.artifacts.runtime import validate_artifact_context

        validate_artifact_context(dict(state), "l1_snapshot", request.l1_snapshot_ref)
        validate_artifact_context(dict(state), "l2_strategy", request.l2_strategy_ref)
        if l1.context_version != request.context_version:
            raise RuntimeError("L3 input L1ObservationSnapshot context version mismatch")
        if l2.context_version != request.context_version:
            raise RuntimeError("L3 input L2Strategy context version mismatch")

        from .aggregation import l3_aggregate

        patch = dict(await l3_aggregate(dict(state)))
        refs = {
            **dict(state.get("artifact_refs") or {}),
            **dict(patch.get("artifact_refs") or {}),
        }
        replay_state = {**dict(state), **patch, "artifact_refs": refs}
        program = self.load(replay_state)
        validate_artifact_context(
            replay_state,
            "planning_program",
            refs.get("planning_program"),
        )
        self._validate_program_boundary(program, l2)
        return L3RunResult(
            request=request,
            program=program,
            artifact_ref=ArtifactRef.model_validate(refs["planning_program"]),
            gate_ref=ArtifactRef.model_validate(refs["l3_gate"]),
            review_id=str(patch.get("l3_review_id") or ""),
            state_patch=patch,
        )


async def run_l3(state: Mapping[str, Any]) -> L3RunResult:
    return await L3Application().run(state)


async def analyze_l3_dimension(state: Mapping[str, Any]) -> dict[str, Any]:
    load_ready_l1_product_manifest(state)
    from app.workflow.stages.support import require_upstream_gates

    require_upstream_gates(
        dict(state),
        ("data", "kg", "evidence", "l1", "l2"),
    )
    from .reasoning import analyze_l3_dimension as run_dimension

    result = await run_dimension(dict(state))
    from app.infrastructure.artifacts.dimension_runtime import (
        ensure_dimension_product_patch,
    )

    return ensure_dimension_product_patch(state, result, layer=3)


__all__ = [
    "L3Application",
    "L3RunRequest",
    "L3RunResult",
    "analyze_l3_dimension",
    "run_l3",
]
