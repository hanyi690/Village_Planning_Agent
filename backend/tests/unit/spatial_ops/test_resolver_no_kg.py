"""Wave G - spatial_ops must not import from app.modules.kg.

These tests pin the dependency-inversion behavior: spatial_ops resolves
spatial references through injected ports / kg_query_fn and injected
gazetteers, never via a lazy ``from app.modules.kg...`` import.
"""

from unittest.mock import MagicMock

import pytest

from app.modules.context.planning_context import PlanningContext
from app.modules.ports.planning_ports import PlanningPorts
from app.modules.schema.contracts.parse_contracts import (
    SpatialPlanningIntent,
    SpatialPreference,
    ZoneTarget,
)
from app.modules.schema.contracts.spatial_reference_contracts import (
    CandidateSet,
    SpatialReferenceSpec,
)
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentLandUseParcel
from app.modules.spatial_ops.grounding.bundle_binder import DeterministicBundleBinder
from app.modules.spatial_ops.grounding.resolver import SpatialResolver, resolve_intent_anchors


def _polygon(coords):
    return {"type": "Polygon", "coordinates": [coords]}


def _make_bundle(bsms=("P001", "P002")):
    bundle = VillageBundle(village_name="test")
    parcels = [
        CurrentLandUseParcel(
            bsm=bsm,
            dlbm="1100",
            geometry=_polygon(
                [
                    [116.04, 24.81],
                    [116.05, 24.81],
                    [116.05, 24.82],
                    [116.04, 24.82],
                    [116.04, 24.81],
                ]
            ),
        )
        for bsm in bsms
    ]
    bundle.polygons.set("landuse_current", parcels)
    return bundle


class FakeSpatialQueryPort:
    def __init__(self, candidates):
        self._candidates = candidates

    def resolve_candidates(self, run_id, spec):
        return self._candidates


def _context(**overrides):
    fields = dict(
        session_id="sess-wave-g",
        village_name="test",
        bundle=_make_bundle(),
        ports=PlanningPorts(),
    )
    fields.update(overrides)
    return PlanningContext(**fields)


class TestResolveSpecViaInjectedPort:
    def test_port_resolve_candidates_filtered_to_bundle(self):
        port = FakeSpatialQueryPort(CandidateSet(bsms=["P001", "P002"]))
        context = _context(ports=PlanningPorts(spatial_query=port))
        resolver = SpatialResolver(context)
        spec = SpatialReferenceSpec(type="attributive")

        result = resolver.resolve_spec(spec)

        assert "P001" in result.final_bsms
        assert "P002" in result.final_bsms

    def test_port_out_of_bundle_bsms_dropped(self):
        port = FakeSpatialQueryPort(CandidateSet(bsms=["P001", "EXT"]))
        context = _context(ports=PlanningPorts(spatial_query=port))
        resolver = SpatialResolver(context)
        spec = SpatialReferenceSpec(type="attributive")

        result = resolver.resolve_spec(spec)

        assert "P001" in result.final_bsms
        assert "EXT" not in result.final_bsms


class TestResolveSpecFallback:
    def test_kg_query_fn_fallback_when_no_port(self):
        def kg_query_fn(template_name, **params):
            return {"bsms": ["P001"]}

        context = _context(kg_query_fn=kg_query_fn)
        resolver = SpatialResolver(context)
        spec = SpatialReferenceSpec(type="attributive")

        result = resolver.resolve_spec(spec)

        assert "P001" in result.final_bsms

    def test_no_port_no_query_returns_empty_without_crash(self):
        context = _context()
        resolver = SpatialResolver(context)
        spec = SpatialReferenceSpec(type="attributive")

        result = resolver.resolve_spec(spec)

        assert result.final_bsms == []


class TestResolveIntentAnchorsNoKgImport:
    def test_gazetteer_none_returns_zero(self):
        intent = SpatialPlanningIntent(village_name="somevillage")

        count = resolve_intent_anchors(
            intent,
            gazetteer=None,
            village_anchors=[],
            village_name="somevillage",
        )

        assert count == 0

    def test_injected_gazetteer_resolves_zone_token(self):
        intent = SpatialPlanningIntent(
            village_name="somevillage",
            zone_targets=[
                ZoneTarget(
                    land_use="居住用地",
                    spatial_preference=SpatialPreference(reference="园寨"),
                )
            ],
        )
        gazetteer = MagicMock()
        entry = MagicMock()
        entry.bsms = ["P001", "P002"]
        gazetteer.resolve.return_value = entry

        count = resolve_intent_anchors(
            intent,
            gazetteer=gazetteer,
            village_anchors=[],
            village_name="somevillage",
        )

        assert count >= 1
        assert "P001" in intent.zone_targets[0].candidate_bsms


class TestBundleBinderNoKgImport:
    def test_gazetteer_none_skips_semantic_path(self):
        bundle = VillageBundle(village_name="test")
        binder = DeterministicBundleBinder(bundle)
        instructions = {
            "instructions": [
                {
                    "instruction_id": "i1",
                    "entity_mentions": ["园寨"],
                    "evidence_text": "园寨附近布局",
                }
            ]
        }

        result = binder.bind(instructions, gazetteer=None)

        feature = result["features"][0]
        assert feature["properties"]["binding_status"] == "unresolved"
