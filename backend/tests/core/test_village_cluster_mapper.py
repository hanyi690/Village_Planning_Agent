"""Village-cluster mapper regression tests.

Clusters are derived from real 宅基地 bundle parcels (no fabrication).  A
name is never assigned by list/size order when report evidence is unavailable.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.spatial.grounding.village_cluster_mapper import (
    build_village_clusters,
    map_villages,
)


def _parcel(bsm, lon, dlbm="1340"):
    return SimpleNamespace(
        bsm=bsm,
        name="",
        dlbm=dlbm,
        area_sqm=800.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[[lon, 23.0], [lon + 0.001, 23.0],
                             [lon + 0.001, 23.001], [lon, 23.001], [lon, 23.0]]],
        },
    )


def _parcels():
    out = []
    for i, lon in enumerate([113.00 + 0.0005 * j for j in range(4)]):
        out.append(_parcel(f"a{i}", lon))
    for i, lon in enumerate([113.05 + 0.0005 * j for j in range(6)]):
        out.append(_parcel(f"b{i}", lon))
    out.append(_parcel("c0", 113.2))
    out.append(_parcel("farm", 113.3, dlbm="1100"))
    return out


def test_build_village_clusters_uses_residential_parcels():
    clusters = build_village_clusters(_parcels())
    assert len(clusters) == 3
    assert clusters[0].parcel_count == 6
    assert clusters[1].parcel_count == 4
    assert clusters[2].parcel_count == 1
    all_bsms = [b for c in clusters for b in c.bsms]
    assert "farm" not in all_bsms


def test_missing_report_evidence_keeps_names_unresolved():
    clusters = build_village_clusters(_parcels())
    mapping = asyncio.run(map_villages(clusters, ["园寨", "田坑", "社前"], llm=None))
    assert mapping == {}


def test_untyped_flash_text_is_not_promoted_to_spatial_mapping():
    class FakeLLM:
        async def ainvoke(self, _prompt):
            return SimpleNamespace(
                content='{"田坑": {"cluster_index": 1, "evidence": "田坑位于村域西部"}}'
            )

    clusters = build_village_clusters(_parcels())
    mapping = asyncio.run(
        map_villages(
            clusters,
            ["田坑", "社前"],
            report_text="现状调查显示：田坑位于村域西部。",
            llm=FakeLLM(),
        )
    )

    assert mapping == {}
