"""Unit tests for the GROUND aggregate (ground_aggregate)."""

from app.agent.ground.aggregate import ground_aggregate
from app.modules.schema.contracts.grounding_contracts import GroundingResult
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec


def _spec(spec_type, **kwargs):
    return SpatialReferenceSpec(type=spec_type, **kwargs)


class TestGroundAggregate:
    def test_empty_specs(self, make_context):
        ctx = make_context()
        result = ground_aggregate([], ctx)

        assert isinstance(result, GroundingResult)
        assert result.candidates == []
        assert result.unresolved == []
        assert result.spatial_query_evidence == []

    def test_resolved_spec_produces_candidate(self, make_context):
        ctx = make_context()
        result = ground_aggregate([_spec("attributive")], ctx)

        assert len(result.candidates) == 1
        candidate = result.candidates[0]
        assert "P001" in candidate.source_parcels
        assert candidate.metrics["spec_type"] == "attributive"
        assert candidate.available_area_ha == 0.0
        assert candidate.hard_constraint_result is None

        assert len(result.spatial_query_evidence) == 1
        evidence = result.spatial_query_evidence[0]
        assert evidence.query_type == "resolve_spec:attributive"
        assert evidence.result_count >= 1

    def test_unresolved_spec_adds_stage_issue(self, make_context):
        ctx = make_context()
        result = ground_aggregate([_spec("composed")], ctx)

        assert result.candidates == []
        assert len(result.unresolved) == 1
        assert "unresolved" in result.unresolved[0].message

    def test_mixed_specs(self, make_context):
        ctx = make_context()
        result = ground_aggregate(
            [_spec("attributive"), _spec("directional"), _spec("composed")],
            ctx,
        )

        assert len(result.candidates) == 2
        assert len(result.unresolved) == 1
        assert len(result.spatial_query_evidence) == 3

    def test_provenance_present(self, make_context):
        ctx = make_context()
        result = ground_aggregate([_spec("attributive")], ctx)

        assert result.provenance is not None
        assert result.provenance.run_id == ctx.session_id
        assert result.provenance.module == "ground"
        assert result.provenance.source == "ground_aggregate"
        assert result.provenance.trace

    def test_deterministic(self, make_context):
        ctx = make_context()
        specs = [_spec("attributive"), _spec("directional"), _spec("composed")]

        first = ground_aggregate(specs, ctx)
        second = ground_aggregate(specs, ctx)

        assert [c.site_id for c in first.candidates] == [c.site_id for c in second.candidates]
        assert [c.source_parcels for c in first.candidates] == [
            c.source_parcels for c in second.candidates
        ]
