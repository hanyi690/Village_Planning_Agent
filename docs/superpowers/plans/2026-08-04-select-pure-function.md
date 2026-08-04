# SELECT Decision Logic (Pure Function Module) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the SELECT decision logic (hard filter → scale filter → deterministic score → optional LLM rank → cluster-anchored placement → PlacementDecision) as a standalone pure-function module, not yet wired to the main graph (wiring happens after parallel dev's 1a-1g land).

**Architecture:** A new `app/modules/spatial_ops/selection.py` exposes granular pure functions plus one orchestrator `select_parcel()`. It extracts the selection loop currently embedded in `execute/agent.py:_execute_project_node` (lines 160-223) and the anchoring logic in `_generation/facility_placer.py`, without modifying those files. An injectable `ranker` callable provides the optional LLM final-selection hook (whitelisted to the candidate pool — it never emits coordinates).

**Tech Stack:** Python 3.11+, shapely (already a dependency), pytest (plain `def test_...` functions per `test_execute_constraints.py`), GeoJSON parcel features.

## Global Constraints

- Python indentation: 4 spaces (per AGENTS.md); double quotes; LF line endings.
- No Chinese comments/emoji inside code; keep comments minimal and English.
- **Add-only**: create `selection.py` + `tests/unit/test_parcel_selection.py`. Do NOT modify any file owned by parallel dev's tasks 1a-1g (`grounding.py`, `bundle_binder.py`, `parse/agent.py:808`, `session_kg.py`, `completion/node.py`, `graph.py:60`, `layout_pipeline.py:131/208`, `spatial_ops/resolver.py`).
- Parcel area: GeoJSON is WGS84 (degrees). Convert deg² → ha with factor `110.9 * 101.0 * 100.0` (1°lat≈110.9km, 1°lon≈101km @~24.8°N).
- `"kg:layer2"` constraint tag and KG layer naming are OUT of scope (Phase 2, includes URI rename).
- Run from `backend/`: `python -m pytest tests/unit/test_parcel_selection.py -v`. Full regression (613 baseline) deferred to wiring milestone.
- Commits must use **explicit paths only** (`git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py`). NEVER `git add -A` — the working tree has unrelated parallel-dev changes.

## File Structure

- **Create** `backend/app/modules/spatial_ops/selection.py` — pure SELECT logic. Grows across Tasks 1-8 (append, never overwrite prior tasks' code).
- **Create** `backend/tests/unit/test_parcel_selection.py` — tests, appended per task.
- No other files touched.

---

### Task 1: Area + scale parsing helpers

**Files:**
- Create: `backend/app/modules/spatial_ops/selection.py`
- Test: `backend/tests/unit/test_parcel_selection.py`

**Interfaces:**
- Produces: `compute_area_ha(geometry: dict) -> float`, `parse_scale_ha(scale_text: str) -> Optional[float]`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.modules.spatial_ops.selection'`

- [ ] **Step 3: Write minimal implementation**

```python
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

_DEG2_HA = 110.9 * 101.0 * 100.0
_SCALE_HA_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(公顷|万平方米|亩|㎡|平方米)")
_CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def compute_area_ha(geometry: Dict[str, Any]) -> float:
    if not geometry:
        return 0.0
    from shapely.geometry import shape

    try:
        geom = shape(geometry)
    except Exception:
        return 0.0
    if geom.is_empty:
        return 0.0
    return geom.area * _DEG2_HA


def parse_scale_ha(scale_text: str) -> Optional[float]:
    text = (scale_text or "").strip()
    if not text:
        return None
    m = _SCALE_HA_RE.search(text)
    if not m:
        cn = re.search(r"占地\s*([一二三四五六七八九十]+)\s*亩", text)
        if not cn:
            return None
        num = _CN_NUM.get(cn.group(1))
        return num / 15.0 if num is not None else None
    value = float(m.group(1))
    unit = m.group(2)
    if unit == "公顷":
        return value
    if unit == "万平方米":
        return value
    if unit == "亩":
        return value / 15.0
    return value / 10000.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add area and scale parsing helpers"
```

---

### Task 2: SelectionTarget, CandidateParcel, large-block detection

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `parse_scale_ha` (Task 1)
- Produces: `@dataclass SelectionTarget`, `@dataclass CandidateParcel`, `is_large_block_target(target: SelectionTarget) -> bool`

- [ ] **Step 1: Write the failing test**

```python
from app.modules.spatial_ops.selection import SelectionTarget, is_large_block_target


def test_is_large_block_target():
    assert is_large_block_target(SelectionTarget(target_id="z1", category="zone")) is True
    assert is_large_block_target(SelectionTarget(target_id="p1", name="南药种植基地")) is True
    assert is_large_block_target(SelectionTarget(target_id="p2", scale_text="占地3亩")) is True
    assert is_large_block_target(SelectionTarget(target_id="p3", scale_text="0.15公顷")) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py::test_is_large_block_target -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
_LARGE_BLOCK_KEYWORDS = ("基地", "产业园", "种植园", "养殖场", "示范区", "加工坊", "整理")
_NON_CONSTRUCTION_DLMC = {"商品林", "生态林", "水域", "耕地"}


@dataclass
class SelectionTarget:
    target_id: str
    name: str = ""
    category: str = "project"  # project / facility / zone
    scale_text: str = ""


@dataclass
class CandidateParcel:
    bsm: str
    geometry: Dict[str, Any]
    dlmc: str = ""
    dlbm: str = ""
    area_ha: float = 0.0
    cluster: str = ""
    distance_m: Optional[float] = None


def is_large_block_target(target: SelectionTarget) -> bool:
    if target.category == "zone":
        return True
    scale_ha = parse_scale_ha(target.scale_text)
    if scale_ha is not None and scale_ha >= 2.0:
        return True
    text = f"{target.name} {target.scale_text}"
    return any(kw in text for kw in _LARGE_BLOCK_KEYWORDS)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py::test_is_large_block_target -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add target/parcel models and large-block detection"
```

---

### Task 3: Hard filters (constraint / hazard / occupied)

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `CandidateParcel` (Task 2)
- Produces: `@dataclass Rejection`, `apply_hard_filters(candidates, *, constraint_index=None, hazards=None, occupied=None) -> (list[CandidateParcel], list[Rejection])`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k hard_filter -v`
Expected: FAIL with `ImportError` (Rejection / apply_hard_filters undefined)

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
_PROHIBITED_CONSTRAINTS = {
    "farmland_protection", "ecological_redline", "historical_protection",
    "cultivated_land_target", "hazard_control_line", "flood_control_line",
}
_HAZARD_MIN_DIST = 0.001
_OCCUPIED_MIN_DIST = 0.00025


@dataclass
class Rejection:
    bsm: str
    reason: str
    detail: List[str] = field(default_factory=list)


def apply_hard_filters(
    candidates: List[CandidateParcel],
    *,
    constraint_index: Any = None,
    hazards: Optional[List[Any]] = None,
    occupied: Optional[List[Tuple[float, float]]] = None,
) -> Tuple[List[CandidateParcel], List[Rejection]]:
    from shapely.geometry import Point, shape

    survivors: List[CandidateParcel] = []
    rejected: List[Rejection] = []
    for cand in candidates:
        try:
            geom = shape(cand.geometry)
        except Exception:
            rejected.append(Rejection(cand.bsm, "invalid_geometry"))
            continue
        if geom.is_empty:
            rejected.append(Rejection(cand.bsm, "empty_geometry"))
            continue
        detail: List[str] = []
        if constraint_index is not None:
            overlaps = constraint_index.geometry_in_constraint(cand.geometry) or []
            blocked = sorted({
                ov.constraint_type for ov in overlaps
                if ov.constraint_type in _PROHIBITED_CONSTRAINTS
            })
            if blocked:
                detail.append(f"constraint:{','.join(blocked)}")
        if not detail:
            point = geom.representative_point()
            for hazard in hazards or []:
                if point.distance(hazard) < _HAZARD_MIN_DIST:
                    detail.append("hazard_proximity")
                    break
            if not detail:
                for other in occupied or []:
                    if point.distance(Point(other)) < _OCCUPIED_MIN_DIST:
                        detail.append("occupied_proximity")
                        break
        if detail:
            rejected.append(Rejection(cand.bsm, "hard_filter", detail))
        else:
            survivors.append(cand)
    return survivors, rejected
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k hard_filter -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add hard filters for constraints, hazards, occupancy"
```

---

### Task 4: Scale filter (point targets vs non-construction land)

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `CandidateParcel`, `_NON_CONSTRUCTION_DLMC` (Task 2)
- Produces: `apply_scale_filter(candidates, *, allow_large_block=False, max_area_ha=2.0) -> list[CandidateParcel]`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k scale_filter -v`
Expected: FAIL with `ImportError` (apply_scale_filter undefined)

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
def apply_scale_filter(
    candidates: List[CandidateParcel],
    *,
    allow_large_block: bool = False,
    max_area_ha: float = 2.0,
) -> List[CandidateParcel]:
    if allow_large_block:
        return list(candidates)
    return [
        c for c in candidates
        if not (c.area_ha > max_area_ha and c.dlmc in _NON_CONSTRUCTION_DLMC)
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k scale_filter -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add scale filter excluding large non-construction land"
```

---

### Task 5: Deterministic suitability scoring

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `CandidateParcel` (Task 2)
- Produces: `@dataclass ScoredCandidate`, `score_candidates(candidates, *, cluster_centroid=None, target_ha=None) -> list[ScoredCandidate]` (sorted desc)

- [ ] **Step 1: Write the failing test**

```python
from app.modules.spatial_ops.selection import CandidateParcel, score_candidates


def _parcel(bsm: str, dlmc: str, area_ha: float, distance_m: float) -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry={}, dlmc=dlmc, area_ha=area_ha, distance_m=distance_m)


def test_score_prefers_closer():
    scored = score_candidates(
        [_parcel("far", "空闲宅基地", 0.1, 2000), _parcel("near", "空闲宅基地", 0.1, 100)],
        cluster_centroid=(0.0, 0.0),
    )
    assert scored[0].bsm == "near"


def test_score_prefers_construction():
    scored = score_candidates(
        [_parcel("farm", "耕地", 0.1, 100), _parcel("bldg", "村庄建设用地", 0.1, 100)],
        cluster_centroid=(0.0, 0.0),
    )
    assert scored[0].bsm == "bldg"


def test_score_area_fit_penalizes_oversized():
    scored = score_candidates(
        [_parcel("big", "空闲宅基地", 100.0, 100), _parcel("fit", "空闲宅基地", 0.15, 100)],
        cluster_centroid=(0.0, 0.0), target_ha=0.15,
    )
    assert scored[0].bsm == "fit"


def test_score_sorted_desc():
    scored = score_candidates(
        [_parcel("a", "空闲宅基地", 0.1, 50), _parcel("b", "空闲宅基地", 0.1, 300), _parcel("c", "空闲宅基地", 0.1, 900)],
        cluster_centroid=(0.0, 0.0),
    )
    scores = [s.score for s in scored]
    assert scores == sorted(scores, reverse=True)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k score -v`
Expected: FAIL with `ImportError` (ScoredCandidate / score_candidates undefined)

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
@dataclass
class ScoredCandidate:
    bsm: str
    score: float
    distance_m: Optional[float]
    reasons: List[str] = field(default_factory=list)


def _is_construction_dlmc(dlmc: str) -> bool:
    return any(kw in (dlmc or "") for kw in ("建设", "居住", "宅基", "空闲"))


def score_candidates(
    candidates: List[CandidateParcel],
    *,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    target_ha: Optional[float] = None,
) -> List[ScoredCandidate]:
    scored: List[ScoredCandidate] = []
    for c in candidates:
        proximity = 0.5
        if cluster_centroid is not None and c.distance_m is not None:
            proximity = 1.0 / (1.0 + c.distance_m / 500.0)
        construction = 1.0 if _is_construction_dlmc(c.dlmc) else 0.3
        area_fit = 0.5
        if target_ha is not None and c.area_ha > 0:
            ratio = c.area_ha / target_ha
            area_fit = max(0.0, 1.0 - abs(math.log2(ratio)))
        score = 0.5 * proximity + 0.3 * construction + 0.2 * area_fit
        scored.append(ScoredCandidate(bsm=c.bsm, score=score, distance_m=c.distance_m))
    scored.sort(key=lambda s: s.score, reverse=True)
    return scored
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k score -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add deterministic suitability scoring"
```

---

### Task 6: Cluster-anchored placement point

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `compute_area_ha` (Task 1)
- Produces: `place_anchor_point(geometry, cluster_centroid=None, small_area_ha=0.2) -> Optional[tuple[float, float]]`

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k anchor -v`
Expected: FAIL with `ImportError` (place_anchor_point undefined)

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
def place_anchor_point(
    geometry: Dict[str, Any],
    cluster_centroid: Optional[Tuple[float, float]] = None,
    small_area_ha: float = 0.2,
) -> Optional[Tuple[float, float]]:
    from shapely.geometry import Point, shape

    try:
        geom = shape(geometry)
    except Exception:
        return None
    if geom.is_empty:
        return None
    rep = geom.representative_point()
    if cluster_centroid is None:
        return (rep.x, rep.y)
    if compute_area_ha(geometry) > small_area_ha and geom.geom_type in ("Polygon", "MultiPolygon"):
        exterior = geom.exterior if geom.geom_type == "Polygon" else geom.convex_hull.exterior
        target = Point(cluster_centroid)
        nearest = exterior.interpolate(exterior.project(target))
        return (nearest.x, nearest.y)
    return (rep.x, rep.y)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k anchor -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): anchor large parcels to cluster boundary"
```

---

### Task 7: Ranking (deterministic default + whitelisted optional LLM)

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `score_candidates` (Task 5)
- Produces: `Ranker = Callable[[List[CandidateParcel], Dict[str, Any]], List[str]]`, `rank_candidates(candidates, *, cluster_centroid=None, target_ha=None, ranker=None, context=None) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
from app.modules.spatial_ops.selection import CandidateParcel, rank_candidates


def _parcel(bsm: str, distance_m: float) -> CandidateParcel:
    return CandidateParcel(bsm=bsm, geometry={}, dlmc="空闲宅基地", area_ha=0.1, distance_m=distance_m)


def test_rank_default_deterministic():
    ordered = rank_candidates(
        [_parcel("a", 900), _parcel("b", 100), _parcel("c", 300)], cluster_centroid=(0.0, 0.0)
    )
    assert ordered == ["b", "c", "a"]


def test_rank_llm_reorders():
    def fake_ranker(candidates, ctx):
        return ["a", "c", "b"]

    ordered = rank_candidates(
        [_parcel("a", 100), _parcel("b", 200), _parcel("c", 300)],
        cluster_centroid=(0.0, 0.0), ranker=fake_ranker,
    )
    assert ordered == ["a", "c", "b"]


def test_rank_llm_whitelisted_to_pool():
    def fake_ranker(candidates, ctx):
        return ["not-in-pool", "b"]

    ordered = rank_candidates(
        [_parcel("a", 100), _parcel("b", 200)], cluster_centroid=(0.0, 0.0), ranker=fake_ranker,
    )
    assert ordered[0] == "b"
    assert "not-in-pool" not in ordered
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k rank -v`
Expected: FAIL with `ImportError` (rank_candidates undefined)

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
Ranker = Callable[[List[CandidateParcel], Dict[str, Any]], List[str]]


def rank_candidates(
    candidates: List[CandidateParcel],
    *,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    target_ha: Optional[float] = None,
    ranker: Optional[Ranker] = None,
    context: Optional[Dict[str, Any]] = None,
) -> List[str]:
    pool = {c.bsm for c in candidates}
    if ranker is None:
        scored = score_candidates(candidates, cluster_centroid=cluster_centroid, target_ha=target_ha)
        return [s.bsm for s in scored]
    ctx = dict(context or {})
    ctx.setdefault("cluster_centroid", cluster_centroid)
    ctx.setdefault("target_ha", target_ha)
    ordered = [b for b in (ranker(candidates, ctx) or []) if b in pool]
    for c in candidates:
        if c.bsm not in ordered:
            ordered.append(c.bsm)
    return ordered
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k rank -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add ranking with whitelisted optional LLM ranker"
```

---

### Task 8: Orchestrator select_parcel → PlacementDecision

**Files:**
- Modify: `backend/app/modules/spatial_ops/selection.py` (append)
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `SelectionTarget`, `CandidateParcel`, `Rejection`, `apply_hard_filters` (T3), `apply_scale_filter` (T4), `is_large_block_target`/`parse_scale_ha` (T1/T2), `rank_candidates` (T7), `place_anchor_point` (T6)
- Produces: `@dataclass PlacementDecision`, `select_parcel(target, *, candidates, constraint_index=None, hazards=None, occupied=None, cluster_centroid=None, ranker=None) -> PlacementDecision`

- [ ] **Step 1: Write the failing test**

```python
from shapely.geometry import Point
from app.modules.spatial_ops.selection import (
    CandidateParcel, PlacementDecision, SelectionTarget, select_parcel,
)


def _parcel(bsm: str, dlmc: str, area_ha: float, x: float, y: float, size: float = 0.001) -> CandidateParcel:
    return CandidateParcel(
        bsm=bsm,
        geometry={"type": "Polygon", "coordinates": [[[x, y], [x + size, y], [x + size, y + size], [x, y + size], [x, y]]]},
        dlmc=dlmc, area_ha=area_ha,
    )


def test_select_places_top_candidate():
    target = SelectionTarget(target_id="p1", name="文化广场", scale_text="0.15公顷")
    d = select_parcel(
        target,
        candidates=[_parcel("a", "空闲宅基地", 0.1, 0, 0), _parcel("b", "空闲宅基地", 0.1, 5, 5)],
        cluster_centroid=(0.0, 0.0),
    )
    assert d.status == "placed"
    assert d.selected_bsm == "a"
    assert d.anchor_point is not None


def test_select_unplaced_when_all_blocked():
    target = SelectionTarget(target_id="p1", scale_text="0.15公顷")
    d = select_parcel(
        target,
        candidates=[_parcel("a", "空闲宅基地", 0.1, 0, 0)],
        constraint_index=_FakeConstraintIndex(block=True),
    )
    assert d.status == "unplaced"
    assert d.rejected


def test_select_point_target_avoids_big_forest():
    target = SelectionTarget(target_id="p1", scale_text="0.15公顷")
    d = select_parcel(
        target,
        candidates=[
            _parcel("forest", "商品林", 100.0, 0, 0, size=0.1),
            _parcel("bldg", "村庄建设用地", 0.1, 10, 10),
        ],
        cluster_centroid=(0.0, 0.0),
    )
    assert d.selected_bsm == "bldg"


def test_select_large_block_target_allows_big_parcel():
    target = SelectionTarget(target_id="p1", name="南药种植基地", scale_text="100公顷")
    d = select_parcel(
        target,
        candidates=[_parcel("forest", "商品林", 100.0, 0, 0, size=0.1)],
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
        candidates=[_parcel("a", "空闲宅基地", 0.1, 0, 0), _parcel("b", "空闲宅基地", 0.1, 5, 5)],
        cluster_centroid=(0.0, 0.0), ranker=fake_ranker,
    )
    assert d.selected_bsm == "b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k select_ -v`
Expected: FAIL with `ImportError` (PlacementDecision / select_parcel undefined)

- [ ] **Step 3: Write minimal implementation** (append to `selection.py`)

```python
@dataclass
class PlacementDecision:
    target_id: str
    selected_bsm: str = ""
    anchor_point: Optional[Tuple[float, float]] = None
    reason: str = ""
    status: str = "unplaced"  # placed / unplaced / deferred
    rejected: List[Rejection] = field(default_factory=list)


def select_parcel(
    target: SelectionTarget,
    *,
    candidates: List[CandidateParcel],
    constraint_index: Any = None,
    hazards: Optional[List[Any]] = None,
    occupied: Optional[List[Tuple[float, float]]] = None,
    cluster_centroid: Optional[Tuple[float, float]] = None,
    ranker: Optional[Ranker] = None,
) -> PlacementDecision:
    target_ha = parse_scale_ha(target.scale_text)
    survivors, rejected = apply_hard_filters(
        candidates, constraint_index=constraint_index, hazards=hazards, occupied=occupied
    )
    survivors = apply_scale_filter(survivors, allow_large_block=is_large_block_target(target))
    order = rank_candidates(
        survivors, cluster_centroid=cluster_centroid, target_ha=target_ha, ranker=ranker,
    )
    by_bsm = {c.bsm: c for c in survivors}
    for bsm in order:
        cand = by_bsm[bsm]
        point = place_anchor_point(cand.geometry, cluster_centroid)
        if point is None:
            rejected.append(Rejection(bsm, "no_anchor_point"))
            continue
        return PlacementDecision(
            target_id=target.target_id,
            selected_bsm=bsm,
            anchor_point=point,
            reason=f"rank_top:{bsm}",
            status="placed",
            rejected=rejected,
        )
    return PlacementDecision(target_id=target.target_id, status="unplaced", rejected=rejected)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/unit/test_parcel_selection.py -k select_ -v`
Expected: PASS (5 tests). Note: `_FakeConstraintIndex` is defined in Task 3 of this same test file — use it directly (same module scope), no import needed.

- [ ] **Step 5: Commit**

```bash
git add backend/app/modules/spatial_ops/selection.py backend/tests/unit/test_parcel_selection.py
git commit -m "feat(select): add select_parcel orchestrator returning PlacementDecision"
```

---

### Task 9: Real-data smoke test (jintian parcels)

**Files:**
- Modify: `backend/tests/unit/test_parcel_selection.py` (append)

**Interfaces:**
- Consumes: `select_parcel`, `SelectionTarget`, `CandidateParcel`, `compute_area_ha` (all prior tasks)

- [ ] **Step 1: Write the failing test**

```python
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
```

- [ ] **Step 2: Run test to verify it fails (or skips)**

Run: `python -m pytest tests/unit/test_parcel_selection.py::test_select_on_real_jintian_parcels -v`
Expected: either PASS (data present) or SKIP (data missing). If data path is wrong, fix `_REAL` (confirm path exists: `python -c "import pathlib; print(pathlib.Path(r'F:/project/Village_Planning_Agent/data/gis/jintian/current/landuse.geojson').exists())"`) then re-run.

- [ ] **Step 3: Run full module test suite**

Run: `python -m pytest tests/unit/test_parcel_selection.py -v`
Expected: all tests PASS (or the real-data one SKIP).

- [ ] **Step 4: Verify no cross-module regression for the two files**

Run: `python -m pytest tests/unit/test_execute_constraints.py tests/unit/test_parse_instruction.py -q`
Expected: PASS (these are the closest SELECT-adjacent tests; SELECT is additive so nothing should break).

- [ ] **Step 5: Commit**

```bash
git add backend/tests/unit/test_parcel_selection.py
git commit -m "test(select): add real-data smoke test for jintian parcels"
```

---

## Self-Review

**Spec coverage:** hard filter ✓ (T3); scale filter point-excludes >2ha non-construction ✓ (T4); large-block targets allowed ✓ (T2+T4); cluster-anchored placement (small `representative_point`, large `nearest_points` to cluster) ✓ (T6); deterministic score ✓ (T5); optional LLM rank, top-1 final, whitelist-only, no coordinates ✓ (T7+T8); unplaced → status `unplaced` (blocked gate is DELIVER's job, out of scope) ✓ (T8); limited-call (deterministic default, ranker injectable) ✓ (T7); real-data validation ✓ (T9).

**Placeholder scan:** none — every step has concrete code and expected test output.

**Type consistency:** `SelectionTarget`/`CandidateParcel`/`Rejection`/`ScoredCandidate`/`PlacementDecision` and all function names are identical across the tasks that define and consume them. `_NON_CONSTRUCTION_DLMC` defined T2, used T4/T9. `Ranker` defined T7, used T8. `parse_scale_ha` T1, used T2/T8.
