from types import SimpleNamespace

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.contracts.workflow.parse_contracts import FacilityTarget, SpatialPlanningIntent
from app.domain.allocation.select_service import select_aggregate


def test_select_carries_feature_and_evidence_lineage_into_assignment() -> None:
    geometry = CandidateGeometry(
        target_id="facility-1",
        kind="point",
        role="anchor_geometry",
        wkt="POINT (116 23)",
        granularity="exact_feature",
        source_ref="source-feature:facility-1",
        source_refs=["source-feature:facility-1"],
        evidence_refs=["l1:fact:1", "kg:relation:1"],
        feature_bsms=["44142621100000000123"],
        source_feature_ids=["source-feature-1"],
        entity_refs=["http://example.test/facility-1"],
        relation_refs=["relation:facility-within-village"],
        l1_fact_refs=["report:location:1"],
        l1_snapshot_ref="artifact://l1/snapshot-1",
        bundle_snapshot_digest="bundle-digest-1",
    )
    grounding = GroundingResult(
        candidates=[
            CandidateSite(
                site_id="site-facility-1",
                target_ref="facility-1",
                expected_output_kind="point",
                geometry=geometry,
            )
        ]
    )
    intent = SpatialPlanningIntent(
        facilities=[FacilityTarget(target_id="facility-1", type="祠堂", action="new")]
    )
    context = SimpleNamespace(
        session_id="lineage-test",
        workspace=SimpleNamespace(polygons={"landuse_current": []}),
        constraint_index=None,
    )

    decision, _ = select_aggregate(grounding, intent, context)

    assignment = decision.target_assignments[0]
    assert assignment.feature_bsm == "44142621100000000123"
    assert assignment.source_feature_id == "source-feature-1"
    assert assignment.entity_ref == "http://example.test/facility-1"
    assert assignment.relation_refs == ["relation:facility-within-village"]
    assert assignment.evidence_refs == ["kg:relation:1", "l1:fact:1"]
    assert assignment.l1_snapshot_ref == "artifact://l1/snapshot-1"
    assert assignment.bundle_snapshot_digest == "bundle-digest-1"
    assert assignment.target_binding["feature_bsms"] == [
        "44142621100000000123"
    ]
