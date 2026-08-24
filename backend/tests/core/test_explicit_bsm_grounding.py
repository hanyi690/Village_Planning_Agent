from types import SimpleNamespace

from shapely.geometry import Polygon

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec
from app.domain.program.claim_adapter import interventions_from_claims
from app.domain.program.demo_narrow_slice import (
    build_demo_narrow_slice_claim,
    build_demo_narrow_slice_claims,
)
from app.spatial.grounding.resolver import SpatialResolver


def _context(parcels):
    return SimpleNamespace(
        workspace=SimpleNamespace(),
        kg=SimpleNamespace(),
        current_parcels=lambda: parcels,
    )


def _parcel(bsm: str, x: float, y: float):
    return {
        "bsm": bsm,
        "geometry": Polygon([(x, y), (x + 0.001, y), (x + 0.001, y + 0.001), (x, y + 0.001)]).__geo_interface__,
    }


def test_demo_claim_maps_explicit_source_parcel_to_bsm_spec():
    claim = build_demo_narrow_slice_claim(
        "[SPATIAL_DEMO_NARROW_SLICE source_parcel_bsm=441426211000049280;site_type=防灾疏散场地;footprint_area_m2=600]"
    )
    assert claim is not None
    interventions = interventions_from_claims([claim])
    assert len(interventions) == 1
    assert interventions[0].spatial_requirements["shared_resource_refs"] == [
        "441426211000049280"
    ]
    spec = map_intervention_to_spec(interventions[0])
    assert spec is not None
    assert spec.reference is not None
    assert spec.reference.kind == "bsm"
    assert spec.reference.filter == {"bsm": "441426211000049280"}


def test_demo_claim_requires_a_closed_typed_marker():
    claim = build_demo_narrow_slice_claim(
        "[SPATIAL_DEMO_NARROW_SLICE source_parcel_bsm=441426211000049280"
    )
    assert claim is None


def test_demo_claims_preserve_repeated_typed_multi_target_markers():
    claims = build_demo_narrow_slice_claims(
        " ".join([
            "[SPATIAL_DEMO_NARROW_SLICE source_parcel_bsm=441426211000049280;site_type=防灾疏散场地;footprint_area_m2=240]",
            "[SPATIAL_DEMO_NARROW_SLICE source_parcel_bsm=441426211000049280;site_type=公共服务场地;footprint_area_m2=180]",
        ])
    )
    assert len(claims) == 2
    assert {claim.quantity for claim in claims} == {240.0, 180.0}
    assert len({claim.claim_id for claim in claims}) == 2
    assert all(claim.location_hints == ["BSM=441426211000049280"] for claim in claims)


def test_bsm_in_location_hint_is_stronger_than_place_name():
    claim = build_demo_narrow_slice_claim(
        "[SPATIAL_DEMO_NARROW_SLICE source_parcel_bsm=441426211000049280]"
    )
    assert claim is not None
    claim = claim.model_copy(update={"affected_parcel_refs": [], "location_hints": ["园寨村", "BSM=441426211000049280"]})
    intervention = interventions_from_claims([claim])[0]
    spec = map_intervention_to_spec(intervention)
    assert spec is not None
    assert spec.reference is not None
    assert spec.reference.kind == "bsm"


def test_direct_bsm_resolution_keeps_one_exact_geometry():
    bsm = "441426211000049280"
    result = SpatialResolver(_context([_parcel(bsm, 116.0, 24.8)])).resolve_spec(
        SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(kind="bsm", filter={"bsm": bsm}),
        )
    )
    assert result.final_bsms == [bsm]
    assert len(result.reference_geometries) == 1
    assert result.spatial_domain_kind == "exact_feature"
    assert result.uncertainty_reason == ""


def test_duplicate_bsm_geometry_is_not_silently_executable():
    bsm = "441426211000055614"
    result = SpatialResolver(
        _context([_parcel(bsm, 116.0, 24.8), _parcel(bsm, 116.01, 24.81)])
    ).resolve_spec(
        SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(kind="bsm", filter={"bsm": bsm}),
        )
    )
    assert len(result.reference_geometries) == 2
    assert result.uncertainty_reason == "duplicate_bsm_geometry_identity"
    candidate = CandidateGeometry(
        target_id="target",
        kind="polygon",
        role="execution_geometry",
        spatial_domain_kind="exact_feature",
        wkt=result.reference_geometries[0].wkt,
        uncertainty_reason=result.uncertainty_reason,
        availability_status="fully_available",
    )
    assert candidate.is_executable is False
