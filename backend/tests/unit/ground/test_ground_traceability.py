"""Unit tests for PARSE -> GROUND traceability id propagation."""

from app.agent.ground.aggregate import build_candidate_site, ground_aggregate
from app.modules.schema.contracts.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)


def _spec(spec_type, **kwargs):
    return SpatialReferenceSpec(type=spec_type, **kwargs)


class TestGroundTraceability:
    def test_candidate_site_carries_target_ref(self):
        spec = SpatialReferenceSpec(
            type="attributive", intervention_id="proj-1", project_ref="p1"
        )
        resolved = ResolvedSpatialRef(
            final_bsms=["P001"], reference_geometry_wkt="POINT(0 0)", confidence=0.9
        )

        candidate = build_candidate_site(spec, resolved, 0)

        assert candidate.target_ref == "proj-1"
        assert candidate.project_ref == "p1"
        assert candidate.site_id == "site_1_P001"
        assert candidate.source_parcels == ["P001"]

    def test_ground_aggregate_specs_carry_ids(self, make_context):
        ctx = make_context()
        result = ground_aggregate(
            [_spec("attributive", intervention_id="proj-1", project_ref="p1")], ctx
        )

        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert candidate.target_ref == "proj-1"
        assert candidate.project_ref == "p1"

        assert len(result.spatial_query_evidence) == 1
        evidence = result.spatial_query_evidence[0]
        assert evidence.query_params["intervention_id"] == "proj-1"
        assert evidence.query_params["project_ref"] == "p1"
        assert evidence.query_params["type"] == "attributive"

    def test_missing_ids_default_none(self, make_context):
        ctx = make_context()
        result = ground_aggregate([_spec("attributive")], ctx)

        assert len(result.candidates) == 1
        assert result.candidates[0].target_ref is None
        assert result.candidates[0].project_ref is None

        evidence = result.spatial_query_evidence[0]
        assert evidence.query_params["intervention_id"] is None
        assert evidence.query_params["project_ref"] is None
