"""P2: GROUND 全村兜底拆除 + CandidateSite 结构化不确定性。"""

from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.grounding_contracts import CandidateSite
from app.contracts.spatial.spatial_reference_contracts import (
    ResolvedSpatialRef,
    SpatialReferenceSpec,
)
from app.domain.ground.aggregate import build_candidate_site
from app.spatial.grounding.grounding import (
    ground_zone_spatial_preference,
    resolve_spatial_description,
)


class _GazetteerMiss:
    def resolve(self, name, fuzzy=False):
        return None


class _GazetteerHit:
    def resolve(self, name, fuzzy=False):
        return SimpleNamespace(bsms=["BSM-1", "BSM-2"], confidence=0.9)


def _bundle(bsms: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        polygons={
            "landuse_current": [
                SimpleNamespace(bsm=bsm, geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]})
                for bsm in bsms
            ]
        }
    )


def test_toponym_gazetteer_miss_stays_typed_unresolved() -> None:
    result = resolve_spatial_description(
        "园寨",
        _bundle(["BSM-1", "BSM-2"]),
        gazetteer=_GazetteerMiss(),
    )
    assert result.candidate_bsms == []
    assert result.unresolved_reason


def test_toponym_gazetteer_hit_binds_bsms() -> None:
    result = resolve_spatial_description(
        "园寨",
        _bundle(["BSM-1", "BSM-2"]),
        gazetteer=_GazetteerHit(),
    )
    assert result.candidate_bsms == ["BSM-1", "BSM-2"]
    assert result.query_path == "gazetteer:bsms"


def test_directional_without_place_center_stays_unresolved() -> None:
    result = resolve_spatial_description("村北", _bundle(["BSM-1"]))
    assert result.candidate_bsms == []
    assert result.unresolved_reason


def test_ground_zone_preference_does_not_fallback_to_full_pool() -> None:
    anchor = ground_zone_spatial_preference(
        "村北",
        place_mappings={},
        constraint_index=None,
        bundle=_bundle(["BSM-1", "BSM-2", "BSM-3"]),
    )
    assert anchor.candidate_bsms == []


def test_build_candidate_site_carries_explicit_grounding_confidence_and_uncertainty() -> None:
    spec = SpatialReferenceSpec(
        type="directional",
        target_id="zone-1",
        direction="N",
    )
    resolved = ResolvedSpatialRef(
        final_bsms=["BSM-1"],
        confidence=0.8,
        uncertainty_radius_m=120.0,
        uncertainty_reason="coarse_reference",
        provenance={"path": "evidence:candidates+geometry:bbox"},
    )

    site = build_candidate_site(spec, resolved, 0)

    assert isinstance(site, CandidateSite)
    assert site.identity_confidence == 0.8
    assert site.geometry_confidence == 0.8
    assert site.uncertainty is not None
    assert site.uncertainty.radius_m == 120.0
    assert site.uncertainty.reason_code == "coarse_reference"
    assert "confidence" not in site.metrics
