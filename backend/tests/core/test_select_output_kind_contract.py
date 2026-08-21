"""SELECT must preserve target output semantics for EXECUTE dispatch."""

from types import SimpleNamespace

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.contracts.workflow.parse_contracts import FacilityTarget, SpatialPlanningIntent
from app.domain.allocation.select_service import build_site_selection_decision, select_aggregate
from app.domain.ground.aggregate import ground_aggregate
from app.domain.materialization.plan_builder import build_execution_plan
from app.spatial.allocation.selection import PlacementDecision


def test_selected_facility_keeps_point_output_kind():
    decision = build_site_selection_decision(
        [
            PlacementDecision(
                target_id="facility-1",
                selected_bsm="bsm-1",
                status="placed",
            )
        ],
        run_id="run-1",
        session_id="session-1",
        expected_output_kinds={"facility-1": "point"},
    )

    assert decision.target_assignments[0].expected_output_kind == "point"


def test_select_preserves_exact_facility_point_without_parcel_fallback():
    geometry = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="anchor_geometry",
        wkt="POINT (116 23)",
        granularity="exact_feature",
        source_ref="source-feature:facility-1",
        source_refs=["source-feature:facility-1"],
        evidence_refs=["evidence:facility-1"],
    )
    grounding = GroundingResult(
        candidates=[CandidateSite(
            site_id="site-facility-1",
            target_ref="facility-1",
            expected_output_kind="point",
            geometry=geometry,
        )]
    )
    intent = SpatialPlanningIntent(facilities=[FacilityTarget(
        target_id="facility-1",
        type="卫生室",
        action="new",
    )])
    context = SimpleNamespace(
        session_id="select-point",
        workspace=SimpleNamespace(polygons={"landuse_current": []}),
        constraint_index=None,
    )

    decision, _ = select_aggregate(grounding, intent, context)

    assignment = decision.target_assignments[0]
    assert assignment.status == "placed"
    assert assignment.selected_bsm == ""
    assert assignment.anchor_point == (116.0, 23.0)
    assert assignment.target_binding["candidate_id"] == geometry.candidate_id
    assert assignment.target_binding["source_ref"] == "source-feature:facility-1"


def test_simulated_llm_evidence_closes_ground_select_execute(monkeypatch):
    """LLM chooses an evidence candidate; source geometry remains evidence-owned."""

    class _SimulatedLLM:
        def choose(self, mention, candidates):
            return candidates[0]

    llm = _SimulatedLLM()
    evidence = {
        "祠堂": ResolvedSpatialRef(
            final_bsms=[],
            reference_geometry_wkt="POINT (116 23)",
            confidence=0.95,
            provenance={"path": "simulated_evidence", "source_ref": "poi:hall-1"},
        )
    }

    class _SimulatedResolver:
        def __init__(self, context):
            self.context = context

        def _spec_mention(self, spec):
            return str(spec.reference.filter.get("label_contains") or "")

        def resolve_spec(self, spec, mention_enhancements=None):
            mention = self._spec_mention(spec)
            selected = llm.choose(mention, [mention])
            return evidence[selected]

    monkeypatch.setattr(
        "app.domain.ground.aggregate.SpatialResolver",
        _SimulatedResolver,
    )
    context = SimpleNamespace(
        session_id="simulated-flow",
        workspace=SimpleNamespace(polygons={"landuse_current": []}),
        constraint_index=None,
        grounded_anchors=[],
    )
    grounding = ground_aggregate(
        [SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(
                kind="place_name",
                filter={"label_contains": "祠堂"},
            ),
            target_id="facility-1",
        )],
        context,
    )

    intent = SpatialPlanningIntent(facilities=[FacilityTarget(
        target_id="facility-1",
        type="卫生室",
        action="new",
    )])
    decision, briefs = select_aggregate(grounding, intent, context)
    plan = build_execution_plan(
        intent,
        decision,
        briefs,
        run_id="simulated-flow",
        context_version="1",
    )

    assignment = decision.target_assignments[0]
    assert assignment.status == "placed"
    assert assignment.anchor_point == (116.0, 23.0)
    assert assignment.selected_bsm == ""
    assert plan.worker_tasks
    assert plan.worker_tasks[0].target_id == "facility-1"
