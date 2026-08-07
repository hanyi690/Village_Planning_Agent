"""Integration: SpatialResolver.resolve_spec uses the evidence index.

Verifies that, when a ``PlanningContext`` carries a built ``PlaceEvidenceIndex``,
a spec referencing a known village resolves through the evidence path to the
expected bundle BSMs. Also pins the degraded path: no evidence index and no
spatial_query port -> empty result, no crash.
"""

from __future__ import annotations

from app.modules.context.planning_context import PlanningContext
from app.modules.kg.gazetteer import Gazetteer, GazetteerEntry
from app.modules.ports.planning_ports import PlanningPorts
from app.modules.schema.contracts.spatial_reference_contracts import (
    CandidateSet,
    RefObject,
    SpatialReferenceSpec,
)
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentLandUseParcel
from app.modules.spatial_ops.evidence import PlaceEvidenceIndex
from app.modules.spatial_ops.grounding.resolver import SpatialResolver


def _polygon():
    return {
        "type": "Polygon",
        "coordinates": [
            [[116.04, 24.81], [116.05, 24.81], [116.05, 24.82], [116.04, 24.82], [116.04, 24.81]]
        ],
    }


def _parcel(bsm):
    return CurrentLandUseParcel(bsm=bsm, dlbm="1100", geometry=_polygon())


def _bundle(bsms):
    bundle = VillageBundle(village_name="test")
    bundle.polygons.set("landuse_current", [_parcel(b) for b in bsms])
    return bundle


def _gazetteer(entries):
    inner = [GazetteerEntry(name=n, bsms=list(bsms)) for n, bsms in entries]
    return Gazetteer(entries=inner)


def _context(bundle, gazetteer=None, evidence_index=None, ports=None):
    return PlanningContext(
        session_id="sess-integration",
        village_name="test",
        bundle=bundle,
        gazetteer=gazetteer,
        evidence_index=evidence_index,
        ports=ports or PlanningPorts(),
    )


def _spec(label):
    return SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="village", filter={"label_contains": label}),
    )


class _FakeSpatialQueryPort:
    def __init__(self, bsms):
        self._bsms = bsms

    def resolve_candidates(self, run_id, spec):
        return CandidateSet(bsms=list(self._bsms))


class TestResolveSpecUsesEvidenceIndex:
    def test_known_village_resolves_to_expected_bsms(self):
        bundle = _bundle(["P001", "P002", "P003"])
        gaz = _gazetteer([("肩丰", ["P001", "P002"])])
        context = _context(bundle, gazetteer=gaz)
        context.evidence_index = PlaceEvidenceIndex.build(context)

        resolver = SpatialResolver(context)
        result = resolver.resolve_spec(_spec("肩丰"))

        assert set(result.final_bsms) == {"P001", "P002"}
        assert result.confidence > 0.0

    def test_evidence_bsms_filtered_to_bundle(self):
        bundle = _bundle(["P001"])
        gaz = _gazetteer([("肩丰", ["P001", "EXT_OUT_OF_BUNDLE"])])
        context = _context(bundle, gazetteer=gaz)
        context.evidence_index = PlaceEvidenceIndex.build(context)

        resolver = SpatialResolver(context)
        result = resolver.resolve_spec(_spec("肩丰"))

        assert result.final_bsms == ["P001"]
        assert "EXT_OUT_OF_BUNDLE" not in result.final_bsms


class TestResolveSpecDegradedPath:
    def test_no_evidence_index_and_no_port_returns_empty(self):
        context = _context(_bundle(["P001"]))
        resolver = SpatialResolver(context)

        result = resolver.resolve_spec(_spec("肩丰"))

        assert result.final_bsms == []

    def test_port_fallback_when_no_evidence_index(self):
        bundle = _bundle(["P001"])
        port = _FakeSpatialQueryPort(["P001"])
        context = _context(bundle, ports=PlanningPorts(spatial_query=port))
        resolver = SpatialResolver(context)

        result = resolver.resolve_spec(_spec("肩丰"))

        assert result.final_bsms == ["P001"]