"""resolve_intent_anchors road-target regression tests.

Road targets get candidate parcels from named connect tokens and directional
anchors (村北/村南) from the village centre, so the road worker / Stage 2.6
has endpoints and does not stall at the confirmation gate.
"""
from __future__ import annotations

from app.contracts.artifacts.provenance import SemanticMetadata
from app.contracts.workflow.parse_contracts import RoadTarget
from app.spatial.grounding.resolver import resolve_intent_anchors


class _Entry:
    bsms = ["bsm-village-1"]


class _Gazetteer:
    def resolve(self, name, fuzzy=False):
        if name in {"园寨", "园寨村", "园寨自然村", "园寨组"}:
            return _Entry()
        return None


def _road(connects, location_hint=""):
    return RoadTarget(
        target_id="road-1",
        road_level="村道",
        width_m=4.0,
        connects=list(connects),
        semantic=SemanticMetadata(spatial_hint=location_hint),
    )


def test_road_named_connects_fill_candidate_bsms():
    road = _road(["园寨", "村南"], "园寨至村南段")
    intent = type("Intent", (), {
        "zone_targets": [], "facilities": [], "development_axes": [],
        "site_area_targets": [], "road_targets": [road],
    })()
    resolved = resolve_intent_anchors(
        intent,
        gazetteer=_Gazetteer(),
        village_anchors=[{"name": "金田村", "lon": 113.5, "lat": 23.5}],
    )
    assert resolved >= 1
    assert "bsm-village-1" in (road.candidate_bsms or [])


def test_road_directional_connects_fill_anchors():
    road = _road(["村北", "村南"])
    intent = type("Intent", (), {
        "zone_targets": [], "facilities": [], "development_axes": [],
        "site_area_targets": [], "road_targets": [road],
    })()
    resolved = resolve_intent_anchors(
        intent,
        gazetteer=None,
        village_anchors=[{"name": "金田村", "lon": 113.5, "lat": 23.5}],
    )
    assert resolved >= 2
    assert road.start_anchor is not None
    assert road.end_anchor is not None
    assert road.start_anchor[1] > 23.5
    assert road.end_anchor[1] < 23.5
