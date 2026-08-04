"""Shared fixtures for the GROUND subgraph unit tests."""

import pytest

from app.modules.context.planning_context import PlanningContext
from app.modules.ports.planning_ports import PlanningPorts
from app.modules.schema.contracts.spatial_reference_contracts import CandidateSet
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentLandUseParcel


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


class FakeSpatialQuery:
    def resolve_candidates(self, run_id, spec):
        if getattr(spec, "type", None) == "attributive":
            return CandidateSet(bsms=["P001", "P002"])
        if getattr(spec, "type", None) == "directional":
            return CandidateSet(bsms=["P001"])
        return CandidateSet(bsms=[])


@pytest.fixture
def make_context():
    def _make_context(**overrides):
        fields = dict(
            session_id="sess-ground-test",
            village_name="test",
            bundle=_make_bundle(),
            ports=PlanningPorts(spatial_query=FakeSpatialQuery()),
        )
        fields.update(overrides)
        return PlanningContext(**fields)

    return _make_context
