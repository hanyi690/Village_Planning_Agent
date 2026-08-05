"""ZONING stage tests: L3 category map, aggregate assignment, chain wiring, node."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.agent.bootstrap.post_l3_chain import build_post_l3_chain
from app.agent.bootstrap.post_l3_state import PostL3ChainState
from app.agent.zoning.aggregate import (
    ZoneAssignment,
    zoning_aggregate,
    zoning_node,
)
from app.modules.parsing.compiler.core import compile_dimension_report
from app.modules.schema.contracts.parcel_change_contracts import (
    ParcelChange,
    ParcelChangeSet,
)
from app.modules.schema.contracts.parse_contracts import (
    SpatialPlanningIntent,
    ZoneTarget,
)
from app.modules.schema.contracts.parsing_contracts import CompilationProfile


def _parcel(bsm, area_sqm=3000):
    return SimpleNamespace(
        bsm=bsm,
        geometry={
            "type": "Polygon",
            "coordinates": [
                [[116.0, 24.8], [116.1, 24.8], [116.1, 24.9], [116.0, 24.9], [116.0, 24.8]]
            ],
        },
        dlbm="0301",
        area_sqm=area_sqm,
    )


def _bundle(*parcels):
    return SimpleNamespace(
        polygons=SimpleNamespace(get=lambda key: list(parcels) if key == "landuse_current" else []),
    )


def _context(bundle=None, constraint_index=None):
    return SimpleNamespace(
        bundle=bundle,
        constraint_index=constraint_index,
        village_anchors=None,
        kg_session_ref="",
        session_id="s1",
    )


def _blocking_constraint_index():
    overlap = SimpleNamespace(constraint_type="ecological_redline")
    return SimpleNamespace(geometry_in_constraint=lambda geometry: [overlap])


def test_l3_map_functional_zone_to_zone():
    report = (
        "## 功能分区规划\n"
        "【INSTRUCTION】\n"
        "| 类型 | 名称 | 位置 | 描述 | 规模 |\n"
        "|---|---|---|---|---|\n"
        "| 功能分区 | 田园生活区 | 村中部 | 生态宜居 | - |\n"
        "| 道路 | 村庄主干道 | 村南 | 对外连接 | 8米 |\n"
    )
    frag = compile_dimension_report(
        CompilationProfile.L3_PLANNING,
        dimension_key="functional_zones",
        content=report,
        instruction=report,
    )
    by_name = {iv.name: iv.category for iv in frag.interventions}
    assert by_name.get("田园生活区") == "zone"
    assert by_name.get("村庄主干道") == "road"


def test_zoning_fills_zone_without_candidate_bsms():
    intent = SpatialPlanningIntent(
        zone_targets=[
            ZoneTarget(
                land_use="生态保护区",
                zone_id="z1",
                area_ha=0.5,
                candidate_bsms=[],
            )
        ]
    )
    occupied_change = ParcelChange(
        bsm="P003",
        action="create",
        derived_from_bsms=["P003"],
        after_geometry_wkt="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )
    changeset = ParcelChangeSet(changes=[occupied_change])
    context = _context(bundle=_bundle(_parcel("P001"), _parcel("P002"), _parcel("P003")))

    assignments, new_changes = zoning_aggregate(intent, changeset, context)

    zone = intent.zone_targets[0]
    assert sorted(zone.candidate_bsms) == ["P001", "P002"]
    assert len(new_changes) == 2
    assert all(c.action == "reclassify" for c in new_changes)
    assert {c.bsm for c in new_changes} == {"P001", "P002"}
    zone_assignments = [
        a for a in assignments if a.source == "zone_target" and a.zone_id == "z1"
    ]
    assert len(zone_assignments) == 2
    assert {a.bsm for a in zone_assignments} == {"P001", "P002"}
    assert all(a.zone == "生态保护区" for a in zone_assignments)


def test_zoning_preserves_remaining_no_constraint_index():
    intent = SpatialPlanningIntent(zone_targets=[])
    changeset = ParcelChangeSet(changes=[])
    context = _context(bundle=_bundle(_parcel("P001")), constraint_index=None)

    assignments, new_changes = zoning_aggregate(intent, changeset, context)

    assert new_changes == []
    assert len(assignments) == 1
    assert assignments[0].bsm == "P001"
    assert assignments[0].source == "unassigned"
    assert assignments[0].zone == "待定/其他"


def test_zoning_preserves_remaining_blocked_by_constraint():
    intent = SpatialPlanningIntent(zone_targets=[])
    changeset = ParcelChangeSet(changes=[])
    context = _context(
        bundle=_bundle(_parcel("P001")),
        constraint_index=_blocking_constraint_index(),
    )

    assignments, _ = zoning_aggregate(intent, changeset, context)

    assert len(assignments) == 1
    assert assignments[0].bsm == "P001"
    assert assignments[0].source == "preserve"
    assert assignments[0].zone == "生态保护/保留"


def test_post_l3_chain_has_zoning():
    graph = build_post_l3_chain()
    nodes = graph.get_graph().nodes
    assert "zoning" in nodes
    assert "execute" in nodes
    assert "validate" in nodes


@pytest.mark.asyncio
async def test_zoning_node_returns_assignments():
    state = PostL3ChainState()
    out = await zoning_node(state)
    assert "zone_assignments" in out
    assert isinstance(out["zone_assignments"], list)


@pytest.mark.asyncio
async def test_zoning_node_rebuilds_changeset_and_layer():
    intent = SpatialPlanningIntent(
        zone_targets=[
            ZoneTarget(
                land_use="生态保护区",
                zone_id="z1",
                area_ha=0.5,
                candidate_bsms=[],
            )
        ]
    )
    occupied_change = ParcelChange(
        bsm="P003",
        action="create",
        derived_from_bsms=["P003"],
        after_geometry_wkt="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )
    changeset = ParcelChangeSet(changes=[occupied_change])
    state = PostL3ChainState(
        intent=intent,
        parcel_changeset=changeset,
        layout_configs=[],
        context=_context(bundle=_bundle(_parcel("P001"), _parcel("P002"), _parcel("P003"))),
    )

    out = await zoning_node(state)

    assert len(out["zone_assignments"]) == 2
    assert out["parcel_changeset"] is not changeset
    assert len(out["parcel_changeset"].changes) == 3
    zone_layer = next(
        c for c in out["layout_configs"] if c["layerType"] == "planning_zones"
    )
    assert len(zone_layer["data"]["features"]) == 2


@pytest.mark.asyncio
async def test_zoning_node_none_changeset_does_not_raise():
    intent = SpatialPlanningIntent(zone_targets=[])
    state = PostL3ChainState(intent=intent, parcel_changeset=None)
    out = await zoning_node(state)
    assert "zone_assignments" in out
    assert "parcel_changeset" not in out


def test_zone_assignment_defaults():
    a = ZoneAssignment(bsm="P1", zone="待定/其他")
    assert a.source == "zone_target"
    assert a.zone_id == ""
    assert a.land_use_code == ""
