"""End-to-end deterministic acceptance test for the village-planning chain.

Drives the full PARSE -> GROUND -> SELECT -> EXECUTE -> VALIDATE
pipeline on a synthetic 8-parcel village using a pre-written L3 report and a
fake spatial resolver. No LLM, no DB, no network: every stage is
deterministic and the whole chain is executed synchronously in one test.

Verified quirks (read from source before writing this test):
  - The L3_PLANNING profile extracts *typed* interventions from the
    ``【INSTRUCTION】`` markdown table (``| 类型 | 名称 | 位置 | 描述 | 规模 |``)
    via ``_interventions_from_instruction``; the prose ``## 项目`` chapters are
    only used for locators/diagnostics. We therefore keep the chapters for
    readability and put the real typed rows in the INSTRUCTION table.
  - The legacy intent builder in ``compile_node._build_legacy_intent`` maps
    ``category == "zone"`` interventions onto ``project_targets`` (only
    ``restoration``/``protection`` become ``zone_targets``), so
    ``intent.zone_targets`` stays empty.
  - ``design_project_footprint`` decides a split via ``geom.area / 10000``,
    which only yields real hectares for metre-unit coordinates. Degree-unit
    coordinates would give ~1e-7 "ha" and never split, so the parcels here use
    metre-unit geometry (still plain GeoJSON polygons).
  - Valid gbt21010 DLBM codes (from ``DLBM_TO_DLMC``) are used, e.g. ``0702``
    农村宅基地, ``1201`` 空闲地, ``0101`` 水田, ``0301`` 乔木林地, ``0601``
    工业用地.

No production source is modified by this test.
"""

from app.agent.execute.land_design_worker import design_all
from app.agent.ground.aggregate import ground_aggregate
from app.agent.l3_plan.aggregate import merge_program_fragments
from app.agent.parse.aggregate import compile_program
from app.agent.select.adapter import (
    filter_parcels_for_target,
    grounding_to_candidate_parcels,
)
from app.agent.select.aggregate import select_aggregate
from app.agent.validate.aggregate import validate_aggregate
from app.modules.context.planning_context import PlanningContext
from app.modules.parsing.compiler.core import compile_dimension_report
from app.modules.ports.planning_ports import PlanningPorts
from app.modules.schema.contracts.parse_contracts import ProjectTarget
from app.modules.schema.contracts.parsing_contracts import CompilationProfile
from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
from app.modules.schema.contracts.spatial_reference_contracts import CandidateSet
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentLandUseParcel

# ── L3 dimension report (Chinese markdown) ─────────────────────────────

L3_REPORT = """## 项目
- 村北农产品加工产业园（产业项目）：占地5公顷，位于村北。
- 村南村民文化广场（公共服务项目）：占地0.5公顷，位于村南。

## 功能分区
- 村北产业区、村南居住区。

## 道路
- 新建村北-村南主干道。

## 设施
- 新增村卫生室（服务半径800米）。

【INSTRUCTION】
| 类型 | 名称 | 位置 | 描述 | 规模 |
| --- | --- | --- | --- | --- |
| 项目 | 村北农产品加工产业园 | 村北 | 农产品加工 | 5公顷 |
| 项目 | 村南村民文化广场 | 村南 | 村民文化活动 | 0.5公顷 |
| 功能分区 | 村北产业区 | 村北 | 产业功能区 | 20公顷 |
| 功能分区 | 村南居住区 | 村南 | 居住功能区 | 15公顷 |
| 道路 | 村北-村南主干道 | 村北-村南 | 联系南北 | 8米 |
| 设施 | 村卫生室 | 村东 | 卫生服务 | 0.3公顷 |
"""

NORTH = ("P001", "P002", "P003")
SOUTH = ("P004", "P005", "P006")
MID = ("P007", "P008")


def _rect(x0, y0, x1, y1):
    return {
        "type": "Polygon",
        "coordinates": [
            [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
        ],
    }


def _make_bundle():
    """8 parcels across a metre-unit village bbox (3 north / 3 south / 2 mid).

    P001 is a 25 ha construction parcel so the 5 ha industrial project is
    forced to split it (create footprint + preserve remainder).
    """
    parcels = [
        CurrentLandUseParcel(bsm="P001", dlbm="0702", area_sqm=250000.0, geometry=_rect(0, 2500, 500, 3000)),
        CurrentLandUseParcel(bsm="P002", dlbm="0101", area_sqm=100000.0, geometry=_rect(500, 2500, 1000, 2700)),
        CurrentLandUseParcel(bsm="P003", dlbm="0301", area_sqm=100000.0, geometry=_rect(500, 2700, 1000, 2900)),
        CurrentLandUseParcel(bsm="P004", dlbm="1201", area_sqm=12000.0, geometry=_rect(0, 400, 100, 520)),
        CurrentLandUseParcel(bsm="P005", dlbm="0101", area_sqm=60000.0, geometry=_rect(300, 400, 600, 600)),
        CurrentLandUseParcel(bsm="P006", dlbm="0301", area_sqm=60000.0, geometry=_rect(600, 400, 900, 600)),
        CurrentLandUseParcel(bsm="P007", dlbm="0601", area_sqm=80000.0, geometry=_rect(100, 1300, 500, 1500)),
        CurrentLandUseParcel(bsm="P008", dlbm="0101", area_sqm=80000.0, geometry=_rect(500, 1300, 900, 1500)),
    ]
    bundle = VillageBundle(village_name="test")
    bundle.polygons.set("landuse_current", parcels)
    return bundle


class FakeSpatialQuery:
    """Resolves directional specs to different parcel pools per direction.

    N -> northern parcels, S -> southern parcels, E -> mid parcels. This is
    what guarantees the industrial (north) and plaza (south) projects get
    disjoint candidate pools downstream.
    """

    def __init__(self, north, south, east):
        self._north = list(north)
        self._south = list(south)
        self._east = list(east)

    def resolve_candidates(self, run_id, spec):
        if getattr(spec, "type", None) != "directional":
            return CandidateSet(bsms=[])
        direction = getattr(spec, "direction", None)
        if direction == "N":
            return CandidateSet(bsms=self._north)
        if direction == "S":
            return CandidateSet(bsms=self._south)
        if direction == "E":
            return CandidateSet(bsms=self._east)
        return CandidateSet(bsms=[])


def _make_context(bundle):
    return PlanningContext(
        session_id="e2e",
        village_name="test",
        bundle=bundle,
        ports=PlanningPorts(
            spatial_query=FakeSpatialQuery(north=NORTH, south=SOUTH, east=MID)
        ),
    )


def _make_parcel_by_bsm(bundle):
    return {p.bsm: p for p in (bundle.polygons.get("landuse_current") or [])}


def _project_by_name(project_targets, name):
    for target in project_targets:
        if target.name == name:
            return target
    raise AssertionError(f"project target not found: {name}")


def _selected_bsm_by_project(decision):
    """Map project_id -> chosen bsm from the SiteSelectionDecision ranking."""
    result = {}
    for ranked in decision.full_ranking:
        if ranked.project_ref:
            result[ranked.project_ref] = ranked.candidate_id
    return result


def _compile_and_parse():
    """Run COMPILE + PARSE, returning (program, intent, specs, gate)."""
    frag = compile_dimension_report(
        CompilationProfile.L3_PLANNING,
        dimension_key="d1",
        content=L3_REPORT,
        instruction=L3_REPORT,
        summary="",
        report_id="rpt-e2e",
        run_id="e2e",
    )
    assert frag is not None, "L3 compile must produce a fragment"
    program = merge_program_fragments([frag], run_id="e2e")
    intent_result, specs, gate = compile_program(program, run_id="e2e")
    return program, intent_result.typed_intent, specs, gate


def test_planning_chain_e2e():
    bundle = _make_bundle()
    context = _make_context(bundle)

    # ── COMPILE + PARSE ────────────────────────────────────────────────
    program, intent, specs, gate = _compile_and_parse()
    assert len(program.interventions) >= 2, "L3 program should carry interventions"
    assert gate.passed, f"deterministic PARSE gate should pass: {gate}"
    assert len(specs) >= 2, "PARSE should emit >= 2 spatial reference specs"
    assert all(getattr(s, "intervention_id", None) for s in specs), (
        "every spec must carry its source intervention_id"
    )

    industrial = _project_by_name(intent.project_targets, "村北农产品加工产业园")
    plaza = _project_by_name(intent.project_targets, "村南村民文化广场")

    # ── GROUND ─────────────────────────────────────────────────────────
    grounding = ground_aggregate(specs, context)
    assert grounding.candidates, "GROUND should resolve candidate sites"
    spec_ids = {s.intervention_id for s in specs}
    for site in grounding.candidates:
        assert site.target_ref is not None, "candidate site must be traced to a spec"
        assert site.target_ref in spec_ids, "target_ref must reference a spec id"

    # ── SELECT ─────────────────────────────────────────────────────────
    decision, briefs = select_aggregate(grounding, intent, context)
    assert isinstance(decision, SiteSelectionDecision)
    assert decision.decision_factors["placed_count"] >= 2, ">= 2 projects placed"

    all_candidates = grounding_to_candidate_parcels(grounding, bundle)
    industrial_pool = {p.bsm for p in filter_parcels_for_target(all_candidates, industrial.project_id)}
    plaza_pool = {p.bsm for p in filter_parcels_for_target(all_candidates, plaza.project_id)}
    assert industrial_pool != plaza_pool, "project candidate pools must differ"
    assert industrial_pool == set(NORTH), "industrial pool must be the northern parcels"
    assert plaza_pool == set(SOUTH), "plaza pool must be the southern parcels"

    selected_by_project = _selected_bsm_by_project(decision)
    industrial_bsm = selected_by_project[industrial.project_id]
    plaza_bsm = selected_by_project[plaza.project_id]
    assert industrial_bsm in industrial_pool, "industrial must land in its own pool"
    assert industrial_bsm in NORTH, "industrial must land in the north"
    assert plaza_bsm in plaza_pool, "plaza must land in its own pool"
    assert plaza_bsm in SOUTH, "plaza must land in the south"

    # ── EXECUTE ────────────────────────────────────────────────────────
    parcel_by_bsm = _make_parcel_by_bsm(bundle)
    changeset = design_all(intent, decision, briefs, parcel_by_bsm)
    assert changeset.changes, "EXECUTE should produce parcel changes"

    creates = [c for c in changeset.changes if c.action == "create"]
    assert creates, "at least one create change (split footprint) expected"
    assert any(abs(c.new_area_ha - 5.0) / 5.0 <= 0.10 for c in creates), (
        "industrial split footprint should be within 10% of the 5 ha target"
    )

    for change in changeset.changes:
        assert change.project_ref, f"change {change.bsm} missing project_ref"
        assert change.after_geometry_wkt, f"change {change.bsm} missing after_geometry_wkt"

    industrial_creates = [c for c in creates if c.project_ref == industrial.project_id]
    industrial_preserves = [
        c
        for c in changeset.changes
        if c.action == "preserve" and c.project_ref == industrial.project_id
    ]
    assert industrial_creates, "industrial split must produce a create change"
    assert industrial_preserves, "industrial split must leave a preserve remainder"

    # ── EXECUTE layout verification ────────────────────────────────────
    # Wave O removed the standalone ZONING node; EXECUTE is now the sole
    # producer of the parcel/layout layer. Verify the changeset is non-empty
    # and fully traceable (there is no separate zoning layer).
    assert changeset.changes, "EXECUTE layout must be non-empty"
    assert all(c.project_ref for c in changeset.changes), (
        "every EXECUTE change must trace to a project"
    )

    # ── VALIDATE ───────────────────────────────────────────────────────
    report = validate_aggregate(
        None,
        changeset,
        [],
        intent,
        context.constraint_index,
        run_id="e2e",
    )
    assert any(c.check_id == "traceability" for c in report.checks), (
        "VALIDATE report must contain the traceability check"
    )

    # ── Final acceptance: non-empty traceable project layer ───────────
    traced = [c for c in changeset.changes if c.project_ref]
    assert traced, "project layer must be non-empty"
    assert all(c.project_ref for c in traced), "every project change must be traceable"
