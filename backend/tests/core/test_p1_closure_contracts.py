from types import SimpleNamespace

import pytest

from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.l3_contracts import PlanningProgram
from app.contracts.program import PlanningClaim
from app.contracts.planning.constraint_factor import ConstraintFactor, RelationSatisfaction
from app.contracts.planning.p1_closure import (
    HumanDecisionRecord,
    build_decision_fingerprint,
    build_grounding_request,
    build_physical_project_assembly,
    build_relation_readiness,
)
from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)
from app.contracts.domain.planning_semantics import FacilityPlanningParameters
from app.workflow.stages.target_projection import _filter_unsupported_spatial_specs
from app.domain.program.target_projection.compile import compile_program_deterministic
from app.domain.allocation.refined_candidate_catalog import build_refined_candidate_catalog
from app.contracts.spatial.candidate_geometry import CandidateGeometry


def _intervention(
    intervention_id: str,
    *,
    package: str = "pkg:shared",
    role: str = "site_footprint",
    variant: str = "facility-default",
) -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id=intervention_id,
        target_id=intervention_id,
        name=intervention_id,
        planning_role="spatial_intervention",
        project_package_ref=package,
        variant_key=variant,
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="point",
        category="facility",
        materialization_role=role or None,
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
        spatial_requirements={"location_hints": ["东村"]},
        claim_refs=[f"claim:{intervention_id}"],
        source_fact_refs=[f"fact:{intervention_id}"],
        evidence_refs=[f"evidence:{intervention_id}"],
    )


def _spec(*, unresolved_reason: str = "") -> SpatialReferenceSpec:
    return SpatialReferenceSpec(
        type="topological",
        topo="nearby",
        reference=RefObject(kind="place_name", filter={"label_contains": "东村"}),
        intervention_id="i-1",
        target_id="t-1",
        spec_id="spatial-ref:t-1",
        unresolved_reason=unresolved_reason,
        retrieval_scopes=["parcels"],
        source_collection_key="current_parcels",
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="snapshot-digest:1",
        source_feature_digest="feature-digest:1",
        source_binding_ref="binding:1",
    )


def test_same_package_claims_deduplicate_but_role_and_variant_split():
    same = build_physical_project_assembly([_intervention("i-1"), _intervention("i-2")])
    assert len(same.projects) == 1
    assert set(same.projects[0].intervention_refs) == {"i-1", "i-2"}
    assert same.fingerprint == build_physical_project_assembly([
        _intervention("i-2"), _intervention("i-1")
    ]).fingerprint

    split = build_physical_project_assembly([
        _intervention("i-1"),
        _intervention("i-2", role="functional_overlay"),
        _intervention("i-3", variant="facility-expanded"),
    ])
    assert len(split.projects) == 3
    assert len({item.project_id for item in split.projects}) == 3


def test_target_projection_carries_physical_project_into_grounding_request():
    claim = PlanningClaim(
        claim_id="claim:i-1",
        dimension_key="facility",
        statement="东村卫生点",
        planning_role="spatial_intervention",
        project_package_ref="pkg:shared",
        suggested_interventions=["东村卫生点"],
        suggested_category="facility",
        suggested_output_kind="point",
        facility_parameters=FacilityPlanningParameters(facility_type="clinic"),
        location_hints=["东村"],
        evidence_refs=["evidence:i-1"],
    )
    intervention = _intervention("i-1", role="", variant="facility-default")
    program = PlanningProgram(interventions=[intervention], claims=[claim])
    result, specs, _ = compile_program_deterministic(program)
    assert result.physical_projects is not None
    assert len(result.physical_projects.projects) == 1
    assert result.pending_grounding_requests[0].physical_project_ref == result.physical_projects.projects[0].project_id
    assert result.pending_grounding_requests[0].status == "pending"


def test_grounding_request_is_stable_and_missing_authority_is_pending():
    first = build_grounding_request(
        _spec(),
        physical_project_ref="physical-project:1",
        component_claim_refs=["claim:1"],
        component_fact_refs=["fact:1"],
    )
    second = build_grounding_request(
        _spec(),
        physical_project_ref="physical-project:1",
        component_claim_refs=["claim:1"],
        component_fact_refs=["fact:1"],
    )
    assert first.status == "ready"
    assert first.request_fingerprint == second.request_fingerprint
    assert first.source_binding_fingerprint == second.source_binding_fingerprint
    assert first.model_dump(mode="json") == second.model_dump(mode="json")

    pending = build_grounding_request(
        _spec().model_copy(update={"source_snapshot_ref": "", "source_binding_ref": ""}),
    )
    assert pending.status == "pending"
    assert "source_snapshot_missing" in pending.defer_reason
    assert "source_binding_missing" in pending.defer_reason


def test_unsupported_named_village_is_parked_before_formal_grounding():
    context = SimpleNamespace(gazetteer=SimpleNamespace(entries=[]))
    formal, diagnostics = _filter_unsupported_spatial_specs([_spec()], context)
    assert formal == []
    assert diagnostics[0]["code"] == "UNSUPPORTED_SPATIAL_REFERENCE"
    pending = build_grounding_request(
        _spec().model_copy(update={"unresolved_reason": "unsupported_source"}),
        defer_reason="unsupported_spatial_reference",
    )
    assert pending.status == "pending"
    assert pending.request_fingerprint


def test_hard_relation_readiness_requires_evaluator_input_snapshot_and_evidence():
    factor = ConstraintFactor(
        factor_id="factor:r-1",
        kind="near",
        subject_ref="t-1",
        object_ref="t-2",
        hard=True,
        evaluator_key="near",
        required_refs=["source_snapshot"],
        input_status="missing",
        source_snapshot_refs=[],
    )
    blocked = build_relation_readiness(
        factor,
        RelationSatisfaction(
            relation_id="r-1",
            subject_ref="t-1",
            object_ref="t-2",
            status="satisfied",
        ),
        evaluator_available=False,
    )
    assert blocked.status == "blocked"
    assert "evaluator_missing" in blocked.reasons
    assert "source_snapshot_missing" in blocked.reasons
    assert "evaluation_evidence_missing" in blocked.reasons

    soft = build_relation_readiness(
        factor.model_copy(update={"hard": False}),
        evaluator_available=False,
    )
    assert soft.status == "advisory"


def test_human_decision_fingerprint_rejects_stale_snapshot_constraint_or_evaluator():
    current = build_decision_fingerprint(
        target_ref="t-1",
        physical_project_ref="physical-project:1",
        grounding_request_fingerprint="request:1",
        source_snapshot_ref="snapshot:1",
        constraint_fingerprint="constraint:1",
        evaluator_key="near",
        evaluator_version="v1",
    )
    record = HumanDecisionRecord(
        decision_fingerprint=current,
        action="approve",
        decided_by="planner",
    )
    record.assert_current(current)
    for changed in (
        current.model_copy(update={"source_snapshot_ref": "snapshot:2", "fingerprint": ""}),
        current.model_copy(update={"constraint_fingerprint": "constraint:2", "fingerprint": ""}),
        current.model_copy(update={"evaluator_version": "v2", "fingerprint": ""}),
    ):
        with pytest.raises(ValueError, match="stale"):
            record.assert_current(changed)


def test_select_refinement_preserves_project_and_component_refs():
    source = CandidateGeometry(
        candidate_id="ground:candidate",
        target_id="t-1",
        physical_project_ref="physical-project:shared",
        component_claim_refs=["claim:a"],
        component_fact_refs=["fact:a"],
        kind="polygon",
        role="execution_geometry",
        spatial_domain_kind="parcel_extent",
        source_bsms=["bsm:1"],
        source_ref="feature:1",
        schema_status="valid",
        wkt="POLYGON ((0 0, 2 0, 2 2, 0 0))",
    )
    problem = SimpleNamespace(
        candidate_geometries=[source],
        target_domains=[SimpleNamespace(target_id="t-1", expected_output_kind="polygon", target_kind="parcel")],
    )
    refined = build_refined_candidate_catalog(
        problem,
        SimpleNamespace(candidates=[SimpleNamespace(
            target_id="t-1",
            source_parcels=["bsm:1"],
            available_geometry_wkt="POLYGON ((0 0, 1 0, 1 1, 0 0))",
            hard_feasible=True,
            score=0.8,
        )]),
    )
    item = next(value for value in refined.values() if value.candidate_id != source.candidate_id)
    assert item.physical_project_ref == source.physical_project_ref
    assert item.component_claim_refs == source.component_claim_refs
    assert item.component_fact_refs == source.component_fact_refs


def test_stale_typed_human_decision_returns_new_pending_review():
    import asyncio
    from app.workflow.root_graph import apply_human_review_decision

    current = build_decision_fingerprint(target_ref="t-1", source_snapshot_ref="snapshot:2")
    old = build_decision_fingerprint(target_ref="t-1", source_snapshot_ref="snapshot:1")
    record = HumanDecisionRecord(
        decision_fingerprint=old,
        action="approve",
        decided_by="planner",
    )
    result = asyncio.run(apply_human_review_decision({
        "paused_stage": "select",
        "human_review_items": [{
            "request_type": "scenario_approval_required",
            "context": {"decision_fingerprint": current.model_dump(mode="json")},
        }],
        "human_review_decisions": {
            "action": "approve",
            "decision_record": record.model_dump(mode="json"),
        },
    }))
    assert result["human_approval_diagnostic"]["code"] == "HUMAN_DECISION_STALE"
    assert result["human_review_decisions"] == {}
    assert result["human_review_resume_consumed"] is False
    assert result["human_interrupt"]["reason"] == "stale_human_decision"
