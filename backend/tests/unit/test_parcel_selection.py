import pytest

from app.modules.spatial_ops.selection import compute_area_ha, parse_scale_ha


def test_compute_area_ha_square():
    geometry = {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]}
    ha = compute_area_ha(geometry)
    assert 1_000_000 < ha < 1_300_000


def test_compute_area_ha_invalid():
    assert compute_area_ha(None) == 0.0
    assert compute_area_ha({"type": "Polygon", "coordinates": []}) == 0.0


def test_parse_scale_ha():
    assert parse_scale_ha("0.15公顷") == 0.15
    assert parse_scale_ha("占地3亩") == 0.2
    assert parse_scale_ha("1500㎡") == 0.15
    assert parse_scale_ha("约2万平方米") == 2.0
    assert parse_scale_ha("占地十亩") == pytest.approx(10 / 15.0)
    assert parse_scale_ha("") is None
    assert parse_scale_ha("无规模信息") is None


from app.modules.spatial_ops.selection import SelectionTarget, is_large_block_target


def test_is_large_block_target():
    assert is_large_block_target(SelectionTarget(target_id="z1", category="zone")) is True
    assert is_large_block_target(SelectionTarget(target_id="p1", name="南药种植基地")) is True
    assert is_large_block_target(SelectionTarget(target_id="p2", scale_text="占地3亩")) is False
    assert is_large_block_target(SelectionTarget(target_id="p3", scale_text="0.15公顷")) is False


from shapely.geometry import Point
from app.modules.spatial_ops.selection import CandidateParcel, apply_hard_filters


class _FakeConstraintIndex:
    def __init__(self, block: bool = False, ctype: str = "farmland_protection"):
        self._block = block
        self._ctype = ctype

    def geometry_in_constraint(self, geometry):
        if self._block:
            from app.modules.spatial_ops.bridge import ConstraintOverlap
            return [ConstraintOverlap(bsm="", constraint_type=self._ctype)]
        return []


def _parcel(bsm: str, x: float, y: float) -> CandidateParcel:
    return CandidateParcel(
        bsm=bsm,
        geometry={"type": "Polygon", "coordinates": [[[x, y], [x + 0.001, y], [x + 0.001, y + 0.001], [x, y + 0.001], [x, y]]]},
        dlmc="空闲宅基地",
        area_ha=0.1,
    )


def test_hard_filter_constraint_overlap_rejected():
    survivors, rejected = apply_hard_filters(
        [_parcel("A", 0, 0)], constraint_index=_FakeConstraintIndex(block=True)
    )
    assert survivors == []
    assert rejected[0].bsm == "A"
    assert "constraint" in rejected[0].detail[0]


def test_hard_filter_clean_survives():
    survivors, rejected = apply_hard_filters([_parcel("A", 0, 0)])
    assert [s.bsm for s in survivors] == ["A"]
    assert rejected == []


def test_hard_filter_hazard_rejected():
    hazard = Point(0.0001, 0.0001)
    survivors, rejected = apply_hard_filters([_parcel("A", 0, 0)], hazards=[hazard])
    assert survivors == []
    assert rejected[0].detail == ["hazard_proximity"]


def test_hard_filter_occupied_rejected():
    survivors, rejected = apply_hard_filters([_parcel("A", 0, 0)], occupied=[(0.00005, 0.00005)])
    assert survivors == []
    assert rejected[0].detail == ["occupied_proximity"]


from app.modules.spatial_ops.selection import CandidateParcel, apply_scale_filter


def _big(name: str, bsm: str = "B") -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry={}, dlmc=name, area_ha=50.0)


def _small(name: str, bsm: str = "S") -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry={}, dlmc=name, area_ha=0.1)


def test_scale_filter_excludes_big_non_construction():
    out = apply_scale_filter([_big("商品林"), _small("空闲宅基地")])
    assert [c.bsm for c in out] == ["S"]


def test_scale_filter_allows_small_non_construction():
    out = apply_scale_filter([_small("水域"), _small("空闲宅基地")])
    assert len(out) == 2


def test_scale_filter_large_block_bypasses():
    out = apply_scale_filter([_big("商品林")], allow_large_block=True)
    assert len(out) == 1


from app.modules.spatial_ops.selection import CandidateParcel, score_candidates


def _scored_parcel(bsm: str, dlmc: str, area_ha: float, distance_m: float) -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry={}, dlmc=dlmc, area_ha=area_ha, distance_m=distance_m)


def test_score_prefers_closer():
    scored = score_candidates(
        [_scored_parcel("far", "空闲宅基地", 0.1, 2000), _scored_parcel("near", "空闲宅基地", 0.1, 100)],
        cluster_centroid=(0.0, 0.0),
    )
    assert scored[0].bsm == "near"


def test_score_prefers_construction():
    scored = score_candidates(
        [_scored_parcel("farm", "耕地", 0.1, 100), _scored_parcel("bldg", "村庄建设用地", 0.1, 100)],
        cluster_centroid=(0.0, 0.0),
    )
    assert scored[0].bsm == "bldg"


def test_score_area_fit_penalizes_oversized():
    scored = score_candidates(
        [_scored_parcel("big", "空闲宅基地", 100.0, 100), _scored_parcel("fit", "空闲宅基地", 0.15, 100)],
        cluster_centroid=(0.0, 0.0), target_ha=0.15,
    )
    assert scored[0].bsm == "fit"


def test_score_sorted_desc():
    scored = score_candidates(
        [_scored_parcel("a", "空闲宅基地", 0.1, 50), _scored_parcel("b", "空闲宅基地", 0.1, 300), _scored_parcel("c", "空闲宅基地", 0.1, 900)],
        cluster_centroid=(0.0, 0.0),
    )
    scores = [s.score for s in scored]
    assert scores == sorted(scores, reverse=True)


from shapely.geometry import Point, shape
from app.modules.spatial_ops.selection import place_anchor_point


def _big_geom(cx: float = 0.0, cy: float = 0.0):
    return {"type": "Polygon", "coordinates": [[[cx, cy], [cx + 0.1, cy], [cx + 0.1, cy + 0.1], [cx, cy + 0.1], [cx, cy]]]}


def _small_geom(cx: float = 0.0, cy: float = 0.0):
    return {"type": "Polygon", "coordinates": [[[cx, cy], [cx + 0.001, cy], [cx + 0.001, cy + 0.001], [cx, cy + 0.001], [cx, cy]]]}


def test_small_parcel_uses_representative_point():
    pt = place_anchor_point(_small_geom(5.0, 5.0), cluster_centroid=(0.0, 0.0))
    assert pt is not None
    assert shape(_small_geom(5.0, 5.0)).contains(Point(pt))


def test_large_parcel_hugs_cluster():
    cluster = (0.0, 0.0)
    pt = place_anchor_point(_big_geom(10.0, 10.0), cluster_centroid=cluster)
    dist_no_anchor = Point(place_anchor_point(_big_geom(10.0, 10.0))).distance(Point(cluster))
    dist_anchored = Point(pt).distance(Point(cluster))
    assert dist_anchored < dist_no_anchor


def test_no_cluster_uses_representative_point():
    pt = place_anchor_point(_big_geom(5.0, 5.0))
    assert pt is not None
    assert shape(_big_geom(5.0, 5.0)).contains(Point(pt))


def test_invalid_geometry_returns_none():
    assert place_anchor_point(None) is None

from app.modules.spatial_ops.selection import CandidateParcel, rank_candidates


def _rank_parcel(bsm: str, distance_m: float) -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry={}, dlmc="空闲宅基地", area_ha=0.1, distance_m=distance_m)


def test_rank_default_deterministic():
    ordered = rank_candidates(
        [_rank_parcel("a", 900), _rank_parcel("b", 100), _rank_parcel("c", 300)], cluster_centroid=(0.0, 0.0)
    )
    assert ordered == ["b", "c", "a"]


def test_rank_llm_reorders():
    def fake_ranker(candidates, ctx):
        return ["a", "c", "b"]

    ordered = rank_candidates(
        [_rank_parcel("a", 100), _rank_parcel("b", 200), _rank_parcel("c", 300)],
        cluster_centroid=(0.0, 0.0), ranker=fake_ranker,
    )
    assert ordered == ["a", "c", "b"]


def test_rank_llm_whitelisted_to_pool():
    def fake_ranker(candidates, ctx):
        return ["not-in-pool", "b"]

    ordered = rank_candidates(
        [_rank_parcel("a", 100), _rank_parcel("b", 200)], cluster_centroid=(0.0, 0.0), ranker=fake_ranker,
    )
    assert ordered[0] == "b"
    assert "not-in-pool" not in ordered


from app.modules.spatial_ops.selection import (
    CandidateParcel, PlacementDecision, SelectionTarget, select_parcel,
)


def _pt_parcel(bsm: str, dlmc: str, area_ha: float, x: float, y: float, size: float = 0.001) -> CandidateParcel:
    return CandidateParcel(
        bsm=bsm,
        geometry={"type": "Polygon", "coordinates": [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]},
        dlmc=dlmc, area_ha=area_ha,
    )


def test_select_places_top_candidate():
    target = SelectionTarget(target_id="p1", name="文化广场", scale_text="0.15公顷")
    d = select_parcel(
        target,
        candidates=[_pt_parcel("a", "空闲宅基地", 0.1, 0, 0), _pt_parcel("b", "空闲宅基地", 0.1, 5, 5)],
        cluster_centroid=(0.0, 0.0),
    )
    assert d.status == "placed"
    assert d.selected_bsm == "a"
    assert d.anchor_point is not None


def test_select_unplaced_when_all_blocked():
    target = SelectionTarget(target_id="p1", scale_text="0.15公顷")
    d = select_parcel(
        target,
        candidates=[_pt_parcel("a", "空闲宅基地", 0.1, 0, 0)],
        constraint_index=_FakeConstraintIndex(block=True),
    )
    assert d.status == "unplaced"
    assert d.rejected


def test_select_point_target_avoids_big_forest():
    target = SelectionTarget(target_id="p1", scale_text="0.15公顷")
    d = select_parcel(
        target,
        candidates=[
            _pt_parcel("forest", "商品林", 100.0, 0, 0, size=0.1),
            _pt_parcel("bldg", "村庄建设用地", 0.1, 10, 10),
        ],
        cluster_centroid=(0.0, 0.0),
    )
    assert d.selected_bsm == "bldg"


def test_select_large_block_target_allows_big_parcel():
    target = SelectionTarget(target_id="p1", name="南药种植基地", scale_text="100公顷")
    d = select_parcel(
        target,
        candidates=[_pt_parcel("forest", "商品林", 100.0, 0, 0, size=0.1)],
        cluster_centroid=(10.0, 10.0),
    )
    assert d.status == "placed"
    assert d.selected_bsm == "forest"


def test_select_honors_llm_ranker_top1():
    target = SelectionTarget(target_id="p1", scale_text="0.15公顷")

    def fake_ranker(candidates, ctx):
        return ["b", "a"]

    d = select_parcel(
        target,
        candidates=[_pt_parcel("a", "空闲宅基地", 0.1, 0, 0), _pt_parcel("b", "空闲宅基地", 0.1, 5, 5)],
        cluster_centroid=(0.0, 0.0), ranker=fake_ranker,
    )
    assert d.selected_bsm == "b"

import json
import pathlib

import pytest
from app.modules.spatial_ops.selection import (
    CandidateParcel, SelectionTarget, compute_area_ha, select_parcel,
)

_REAL = pathlib.Path(__file__).resolve().parents[3] / "data" / "gis" / "jintian" / "current" / "landuse.geojson"


def _real_candidates():
    fc = json.loads(_REAL.read_text(encoding="utf-8"))
    out = []
    for f in fc.get("features", []):
        props = f.get("properties") or {}
        bsm = str(props.get("BSM") or props.get("bsm") or "")
        geom = f.get("geometry")
        if not bsm or not geom:
            continue
        out.append(CandidateParcel(
            bsm=bsm, geometry=geom,
            dlmc=str(props.get("DLMC") or props.get("dlmc") or ""),
            area_ha=compute_area_ha(geom),
        ))
    return out


@pytest.mark.skipif(not _REAL.exists(), reason="jintian landuse data missing")
def test_select_on_real_jintian_parcels():
    candidates = _real_candidates()
    assert len(candidates) > 100
    target = SelectionTarget(target_id="p1", name="村民文化广场", scale_text="0.15公顷")
    decision = select_parcel(target, candidates=candidates, cluster_centroid=(116.040759, 24.816435))
    assert decision.status == "placed"
    chosen = next(c for c in candidates if c.bsm == decision.selected_bsm)
    assert chosen.area_ha <= 2.0 or chosen.dlmc not in {"商品林", "生态林", "水域", "耕地"}
    assert decision.anchor_point is not None
