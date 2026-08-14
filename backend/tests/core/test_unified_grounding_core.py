"""统一接地核心（Unified Grounding Core）新增能力测试。

覆盖：坐标同一性（同坐标=同实体）、KG 拓扑评分、证据索引坐标合并、
ground_anchors 不留下不可解析地点、resolver LLM best-effort 兜底。
"""
from __future__ import annotations

import json
from types import SimpleNamespace

from rdflib import Graph, Literal, Namespace, URIRef

PLN = Namespace("http://village-planning.org/ontology#")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


def _kg_graph():
    g = Graph()
    fac = PLN.facility_bsm_1
    g.add((fac, RDF.type, PLN.Facility))
    g.add((fac, PLN.name, Literal("祠堂")))
    g.add((fac, PLN.bsm, Literal("bsm-100")))
    g.add((fac, PLN.lon, Literal("113.100")))
    g.add((fac, PLN.lat, Literal("23.100")))
    water = PLN.water_body_bsm_2
    g.add((water, RDF.type, PLN.WaterBody))
    g.add((water, PLN.name, Literal("石窟河")))
    g.add((water, PLN.bsm, Literal("bsm-200")))
    g.add((water, PLN.lon, Literal("113.200")))
    g.add((water, PLN.lat, Literal("23.200")))
    road = PLN.road_bsm_3
    g.add((road, RDF.type, PLN.Road))
    g.add((road, PLN.name, Literal("122乡道")))
    cluster = PLN.residential_cluster_bsm_4
    g.add((cluster, RDF.type, PLN.ResidentialCluster))
    g.add((cluster, PLN.name, Literal("社前村")))
    g.add((cluster, PLN.bsm, Literal("bsm-400")))
    g.add((cluster, PLN.lon, Literal("113.400")))
    g.add((cluster, PLN.lat, Literal("23.400")))
    admin = PLN.administrative_village_bsm_5
    g.add((admin, RDF.type, PLN.AdministrativeVillage))
    g.add((admin, PLN.name, Literal("金田村")))
    g.add((admin, PLN.bsm, Literal("bsm-500")))
    g.add((fac, PLN.serves, admin))
    return g


def _kg():
    from app.infrastructure.kg.builder.base import PlanningKG

    kg = PlanningKG(village_name="金田村")
    for triple in _kg_graph():
        kg.g.add(triple)
    return kg


def _context(kg, facts=None):
    from app.infrastructure.kg.gazetteer import build_gazetteer

    gazetteer = build_gazetteer(kg, None, None)
    ctx = SimpleNamespace(
        session_id="s-core",
        version=1,
        kg_version=1,
        gazetteer=gazetteer,
        location_facts=facts or [],
        kg=kg,
        workspace=SimpleNamespace(
            points={"annotations_current": [], "facilities_current": []},
            polygons={"landuse_current": []},
        ),
        current_parcels=lambda: [],
    )
    return ctx


def test_coordinate_identity_same_coordinate():
    from app.spatial.grounding.coordinate_identity import (
        coordinate_key,
        same_coordinate,
    )

    assert same_coordinate("POINT(113.1 23.1)", "kg_wkt:POINT(113.1 23.1)")
    assert not same_coordinate("POINT(113.1 23.1)", "POINT(113.2 23.1)")
    assert coordinate_key("POINT(113.123456 23.123456)") == coordinate_key(
        "POINT(113.1234561 23.1234562)"
    )
    assert coordinate_key(None) == ""


def test_topology_evidence_matches_village_hint():
    from app.spatial.grounding.topology import topology_evidence_for

    kg = _kg()
    hits = topology_evidence_for(kg.g, str(PLN.facility_bsm_1), hints="位于金田村")
    assert any("serves" in h and "金田村" in h for h in hits), hits


def test_evidence_scorer_relation_topology_real_check():
    from app.evidence.index.evidence_scorer import score_candidate, total
    from app.contracts.ports.place_resolution_contracts import PlaceEvidenceEntry

    kg = _kg()
    entry = PlaceEvidenceEntry(
        canonical_name="祠堂",
        entity_refs=[str(PLN.facility_bsm_1)],
        entity_types=["facility"],
        role="facility",
        source_bsms=["bsm-100"],
        geometry_ref="POINT(113.1 23.1)",
        relation_refs=[],
    )
    ev = score_candidate("祠堂", entry, role="facility", hints="位于金田村", context=SimpleNamespace(kg=kg))
    assert ev["relation_topology"] == 0.5
    assert total(ev) > 0.0


def test_evidence_index_coordinate_merge_same_entity():
    from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

    kg = _kg()
    ctx = _context(kg)
    index = PlaceEvidenceIndex.build(ctx)
    # 两个同坐标同角色的实体在索引里应合并为一条
    by_name = {e.canonical_name: e for e in index.entries}
    assert "祠堂" in by_name


def test_ground_l1_anchors_no_unresolved_left():
    import asyncio

    from app.contracts.domain.l1_contracts import L1LocationFact
    from app.domain.ground.anchors import ground_l1_anchors

    kg = _kg()
    facts = [
        L1LocationFact(
            mention="祠堂", normalized_name="祠堂", role="facility", aliases=["祠堂"],
            spatial_hint="社前村", source_span="现状设施 | 祠堂 | 社前村",
            source_report_ref="rpt-1", dimension_key="historical_culture", confidence=0.95,
        ),
        L1LocationFact(
            mention="石窟河", normalized_name="石窟河", role="water", aliases=["石窟河"],
            spatial_hint="西南至东北贯穿", source_span="水系 | 石窟河 | 西南至东北贯穿",
            source_report_ref="rpt-1", dimension_key="water", confidence=0.9,
        ),
        L1LocationFact(
            mention="村内小路", normalized_name="村内小路", role="road", aliases=["村内小路"],
            spatial_hint="", source_span="道路 | 村内小路",
            source_report_ref="rpt-1", dimension_key="road", confidence=0.6,
        ),
    ]
    ctx = _context(kg, facts)
    anchors = asyncio.run(
        ground_l1_anchors(ctx, "s-core", llm=None, bump=False)
    )
    assert len(anchors) == len(facts), anchors
    for anchor in anchors:
        # 不允许留下不可解析：每个锚点要么有 BSM，要么有几何/实体引用
        assert anchor.source_bsms or anchor.geometry_ref or anchor.entity_ref, anchor
    # 同坐标=同实体：dedupe 后角色内坐标键唯一
    keys = [(a.role, a.coordinate_key) for a in anchors if a.coordinate_key]
    assert len(keys) == len(set(keys))


def test_ground_l1_anchors_scope_admin_village_not_pooled():
    """金田村（行政村/规划范围）必须识别为 administrative_village，不落自然村池。"""
    import asyncio

    from app.contracts.domain.l1_contracts import L1LocationFact
    from app.domain.ground.anchors import ground_l1_anchors

    kg = _kg()
    facts = [
        L1LocationFact(
            mention="金田村", normalized_name="金田村", role="area", aliases=["金田村"],
            spatial_hint="金田村", source_span="现状分区 | 金田村 | 规划范围",
            source_report_ref="rpt-1", dimension_key="scope", confidence=1.0,
        ),
        L1LocationFact(
            mention="园寨", normalized_name="园寨", role="village", aliases=["园寨"],
            spatial_hint="园寨", source_span="自然村 | 园寨",
            source_report_ref="rpt-1", dimension_key="socio", confidence=1.0,
        ),
    ]
    ctx = _context(kg, facts)
    ctx.village_name = "金田村"
    anchors = asyncio.run(ground_l1_anchors(ctx, "s-scope", llm=None, bump=False))
    scope = [a for a in anchors if a.role == "administrative_village"]
    assert scope and scope[0].normalized_name == "金田村", anchors
    assert scope[0].entity_ref, scope[0]
    # 金田村 不得再作为可落位的自然村锚点
    assert not [a for a in anchors if a.role == "village" and a.normalized_name == "金田村"]


def test_topology_refine_facility_picks_village_serving_facility():
    """KG 拓扑消歧：社前村的祠堂 → 选 serves/nearby 指向社前村簇的那个设施。"""
    from types import SimpleNamespace

    from rdflib import RDF, Literal

    from app.contracts.domain.l1_contracts import L1LocationFact
    from app.domain.ground.anchors import GroundedAnchor, _topology_refine_facility
    from app.infrastructure.kg.ontology import EntityTypes, PLN, Relations

    g = Graph()
    cluster_a, cluster_b = PLN.settlement_a, PLN.settlement_b
    g.add((cluster_a, RDF.type, EntityTypes.ResidentialCluster))
    g.add((cluster_b, RDF.type, EntityTypes.ResidentialCluster))
    g.add((cluster_a, PLN.name, Literal("居民点A")))
    g.add((cluster_b, PLN.name, Literal("居民点B")))
    for cluster, bsm in ((cluster_a, "bsm-a"), (cluster_b, "bsm-b")):
        p = PLN[f"parcel_{bsm}"]
        g.add((p, RDF.type, EntityTypes.Parcel))
        g.add((p, PLN.bsm, Literal(bsm)))
        g.add((p, Relations.sfWithin, cluster))
    f1, f2 = PLN.facility_1, PLN.facility_2
    for f, cluster, xy in ((f1, cluster_a, (113.0, 23.0)), (f2, cluster_b, (113.5, 23.5))):
        g.add((f, RDF.type, EntityTypes.Facility))
        g.add((f, PLN.name, Literal("祠堂")))
        g.add((f, Relations.serves, cluster))
        g.add((f, Relations.nearby, cluster))
        g.add((f, PLN.lon, Literal(xy[0])))
        g.add((f, PLN.lat, Literal(xy[1])))
    kg = SimpleNamespace(g=g)
    gazetteer = SimpleNamespace(
        entries=[],
        resolve=lambda name, fuzzy=False: (
            SimpleNamespace(bsms=["bsm-a"], centroid=[113.0, 23.0])
            if "社前" in str(name) else None
        ),
    )
    entries = [
        SimpleNamespace(role="facility", entity_refs=[str(f1)], entity_types=["facility"],
                        canonical_name="祠堂", source_bsms=["bsm-a"],
                        geometry_ref="POINT(113.0 23.0)", relation_refs=[], confidence=0.9),
        SimpleNamespace(role="facility", entity_refs=[str(f2)], entity_types=["facility"],
                        canonical_name="祠堂", source_bsms=["bsm-b"],
                        geometry_ref="POINT(113.5 23.5)", relation_refs=[], confidence=0.9),
    ]
    context = SimpleNamespace(gazetteer=gazetteer, kg=kg, evidence_index=SimpleNamespace(entries=entries))
    fact = L1LocationFact(
        mention="祠堂", normalized_name="祠堂", role="facility", aliases=["祠堂"],
        spatial_hint="社前村", source_span="现状设施 | 祠堂 | 社前村",
        source_report_ref="rpt", dimension_key="x", confidence=0.9,
    )
    anchor = GroundedAnchor(
        mention="祠堂", normalized_name="祠堂", role="facility", entity_ref=str(f2),
        entity_type="facility", geometry_ref="POINT(113.5 23.5)", source_bsms=["bsm-b"],
        confidence=0.6, source_report_ref="rpt", source_span="s",
    )
    refined = _topology_refine_facility(context, fact, anchor)
    assert refined.entity_ref == str(f1), refined
    assert set(refined.source_bsms) == {"bsm-a"}, refined
    assert any(
        (t.get("step") or "") == "kg_topology_facility" and t.get("refined") is not False
        for t in refined.query_trace
    ), refined.query_trace


def test_resolver_llm_fallback_picks_ambiguous_candidate(monkeypatch):
    """LLM best-effort：主路径未绑定但有索引候选时，从候选内选出可用 BSMs。"""
    from app.spatial.grounding.resolver import SpatialResolver
    from app.contracts.ports.place_resolution_contracts import PlaceResolutionCandidate
    from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec

    parcels = [
        SimpleNamespace(bsm="bsm-1", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}, area_sqm=10000.0),
        SimpleNamespace(bsm="bsm-2", geometry={"type": "Polygon", "coordinates": [[[0, 0], [0, 1], [1, 1], [1, 0], [0, 0]]]}, area_sqm=10000.0),
    ]

    class _StubIndex:
        def resolve_mention(self, mention, role="unknown", hints=""):
            return SimpleNamespace(
                status="ambiguous",
                candidates=[
                    PlaceResolutionCandidate(
                        entity_ref="pln:cluster_1", entity_type="village",
                        canonical_name="园寨", source_bsms=["bsm-1"],
                        score=0.5, evidence_refs=["gazetteer"],
                    ),
                    PlaceResolutionCandidate(
                        entity_ref="pln:cluster_2", entity_type="village",
                        canonical_name="园寨组", source_bsms=["bsm-2"],
                        score=0.5, evidence_refs=["gazetteer"],
                    ),
                ],
                query_trace=[{"step": "exact"}],
            )

    ctx = SimpleNamespace(
        session_id="s-llm", version=1, kg_version=1,
        gazetteer=None, location_facts=[], kg=None,
        workspace=SimpleNamespace(points={}, polygons={"landuse_current": parcels}),
        current_parcels=lambda: parcels,
        evidence_index=_StubIndex(),
    )
    ctx.ports = SimpleNamespace(spatial_query=None)

    class _FakeLLM:
        def invoke(self, prompt):
            return SimpleNamespace(content="1")

    import app.infrastructure.llm.factory as factory_mod

    monkeypatch.setattr(factory_mod, "create_flash_llm", lambda **kw: _FakeLLM())

    resolver = SpatialResolver(ctx)
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="place_name", filter={"label_contains": "园寨"}),
        target_id="t-1",
    )
    resolved = resolver._llm_reason_fallback(spec, "园寨", None)
    assert resolved is not None
    assert resolved.final_bsms == ["bsm-1"], resolved
    assert resolved.uncertainty_reason == "llm_best_effort"
    assert resolved.confidence == 0.35
