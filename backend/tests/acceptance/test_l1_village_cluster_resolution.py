"""LLM-decided many-to-one village -> cluster resolution against the real fixture.

Proves the goal: with only the current-state report + KG/bundle (no hardcoded
village lists), report-named natural villages resolve to a spatial extent
(BSM set) through an LLM-decided multi-cluster assignment, aggregated into the
gazetteer and surfaced by the PlaceEvidenceIndex.
"""
from __future__ import annotations

import asyncio
import json
import uuid
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from tests.fixtures.db import make_session_with_uploads  # noqa: E402

FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"

_LAYER_TYPES = {
    "admin_boundary_line.geojson": "admin_boundary_line",
    "annotation.geojson": "annotation",
    "boundary.geojson": "boundary",
    "construction_zone.geojson": "construction_zone",
    "ecological_protection.geojson": "ecological_protection",
    "farmland_protection.geojson": "farmland_protection",
    "geological_hazard_points.geojson": "geological_hazard_points",
    "historical_protection.geojson": "historical_protection",
    "landuse.geojson": "landuse_current",
    "road.geojson": "road",
}


def _uploads() -> list[dict]:
    ups = [{
        "file_category": "village_data",
        "filename": "current_report.md",
        "original_filename": "current_report.md",
        "content_type": "text/markdown",
        "file_type": "md",
        "parsed_text": (FIXTURE / "current_report.md").read_text(encoding="utf-8"),
    }]
    for path in sorted((FIXTURE / "gis").glob("*.geojson")):
        ups.append({
            "file_category": "gis_data",
            "filename": path.name,
            "original_filename": path.name,
            "content_type": "application/geo+json",
            "file_type": "geojson",
            "file_size": path.stat().st_size,
            "gis_data": json.loads(path.read_text(encoding="utf-8")),
            "gis_data_type": _LAYER_TYPES[path.name],
        })
    return ups


def _report_village_names(report_text: str) -> list[str]:
    """Extract the natural-village enumeration straight from the report."""
    m = re.search(r"自然村，分别为：([^。\n]+)", report_text or "")
    if not m:
        return []
    names = []
    for tok in re.split(r"[、,，\s]+", m.group(1)):
        tok = tok.strip()
        if tok:
            names.append(tok)
    return list(dict.fromkeys(names))


class _EvidenceLLM:
    """Typed Flash stand-in: assigns villages to clusters with report evidence."""

    def __init__(self, assignments: dict):
        self.assignments = assignments

    def with_structured_output(self, schema, **_kwargs):
        assignments = self.assignments

        class _Runner:
            async def ainvoke(self, _prompt):
                return schema(entries=[
                    {
                        "name": name,
                        "candidate_indexes": list(item.get("cluster_indexes") or item.get("candidate_indexes") or []),
                        "evidence": item.get("evidence", ""),
                    }
                    for name, item in assignments.items()
                ])

        return _Runner()


@pytest.mark.asyncio
async def test_report_named_villages_resolve_via_many_to_one_llm_mapping(
    sqlite_db, pipeline_reset
):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-village-cluster-many"
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            build_village_clusters,
        )
        from app.contracts.domain.l1_contracts import L1LocationFact
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])

        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")
        village_names = _report_village_names(report)
        assert len(village_names) >= 10, village_names

        clusters = build_village_clusters(parcels)
        assert len(clusters) >= 3, f"fixture produced {len(clusters)} clusters"

        # LLM uses verbatim report snippets; one village spans 2 clusters.
        llm = _EvidenceLLM({
            "园寨": {
                "cluster_indexes": [clusters[0].index, clusters[1].index],
                "evidence": "主要集中于金田村中部的园寨",
            },
            "社前": {
                "cluster_indexes": [clusters[-1].index],
                "evidence": "马头段、社前以及园寨",
            },
        })
        entries = await assign_villages_to_clusters(
            gazetteer, parcels, village_names, report,
            llm=llm,
        )
        assert {e.name for e in entries} == {"园寨村", "社前村"}
        for e in entries:
            gazetteer.upsert(e)

        many = next(e for e in entries if e.name == "园寨村")
        expected_union = list(dict.fromkeys(clusters[0].bsms + clusters[1].bsms))
        assert many.bsms == expected_union
        assert len(many.bsms) >= len(clusters[0].bsms)
        assert many.source == "village_cluster_map"
        assert many.entity_uri == "pln:natural_village:园寨"

        facts = [
            L1LocationFact(
                mention=n, normalized_name=n, role="village", aliases=[n],
                spatial_hint=n, source_report_ref="current_report.md",
                dimension_key="socio_economic", confidence=1.0,
            )
            for n in village_names
        ]
        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
        )
        context.current_parcels = lambda: parcels
        index = PlaceEvidenceIndex.build(context)
        for e in entries:
            res = index.resolve_mention(e.name, role="village")
            assert res.status == "resolved", (e.name, res.status)
            assert res.candidates[0].source_bsms, e.name
        # The base mention (园寨 without suffix) also resolves.
        base = index.resolve_mention("园寨", role="village")
        assert base.status == "resolved"
        assert base.candidates[0].source_bsms
    finally:
        await teardown()

@pytest.mark.asyncio
async def test_village_anchored_facility_resolves_via_llm_mapping(sqlite_db, pipeline_reset):
    """A facility reported at a named village inherits the village BSM set.

    With only report + KG (no hardcoded names): the LLM decides 园寨 belongs
    to a residential cluster, the gazetteer entry aggregates its BSMs, and the
    facility fact ``供水点 @ 园寨`` resolves through that village anchor.
    """
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-village-anchor"
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            build_village_clusters,
        )
        from app.contracts.domain.l1_contracts import L1LocationFact
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")
        village_names = _report_village_names(report)

        clusters = build_village_clusters(parcels)
        llm = _EvidenceLLM({
            "园寨": {
                "cluster_indexes": [clusters[0].index],
                "evidence": "主要集中于金田村中部的园寨",
            },
        })
        entries = await assign_villages_to_clusters(
            gazetteer, parcels, village_names, report, llm=llm
        )
        for e in entries:
            gazetteer.upsert(e)
        yz = next(e for e in entries if e.name == "园寨村")

        facts = [
            L1LocationFact(
                mention="供水点", normalized_name="供水点", role="facility",
                aliases=["供水点"], spatial_hint="园寨",
                source_span="现状设施 | 供水点 | 园寨 | 5处供水点",
                source_report_ref="current_report.md",
                dimension_key="infrastructure", confidence=0.95,
            ),
            L1LocationFact(
                mention="园寨", normalized_name="园寨", role="village",
                aliases=["园寨"], spatial_hint="园寨",
                source_span="现状设施 | 供水点 | 园寨 | 5处供水点",
                source_report_ref="current_report.md",
                dimension_key="infrastructure", confidence=0.95,
            ),
        ]
        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
        )
        context.current_parcels = lambda: parcels
        index = PlaceEvidenceIndex.build(context)

        res = index.resolve_mention("供水点", role="facility")
        assert res.status == "resolved", res.status
        cand = res.candidates[0]
        assert cand.source_bsms, cand
        assert any("village_anchor" in p for p in cand.evidence_refs), cand.evidence_refs
        assert set(cand.anchor_bsms) == set(yz.bsms)
        assert cand.feature_bsm or cand.geometry_ref
    finally:
        await teardown()

@pytest.mark.asyncio
async def test_existing_facility_points_resolve_via_expanded_names(sqlite_db, pipeline_reset):
    """Existing 现状设施点 (single-char labels) carry near-parcel BSMs.

    A fact using the expanded KG facility name (祠 -> 祠堂) must reach those
    BSMs - i.e. the resolution must utilise the already-uploaded facilities,
    not leave their extent stranded on the raw label.
    """
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-facility-points"
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        ctx = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=[],
        )
        ctx.current_parcels = lambda: parcels
        index = PlaceEvidenceIndex.build(ctx)

        for name in ["祠堂", "广场", "供水设施", "卫生站", "公交站", "停车场"]:
            res = index.resolve_mention(name, role="facility")
            if len({candidate.geometry_ref for candidate in res.candidates if candidate.geometry_ref}) > 1:
                assert res.status == "ambiguous", (name, res.status)
                assert len(res.candidates) > 1
                continue
            assert res.status == "resolved", (name, res.status)
            cand = res.candidates[0]
            assert cand.source_bsms or cand.feature_bsm or cand.related_parcel_bsms, (name, cand)
            assert any(source in cand.evidence_refs for source in ("poi", "kg")), (name, cand.evidence_refs)
    finally:
        await teardown()

@pytest.mark.asyncio
async def test_report_water_names_resolve_via_landuse_water_bodies(sqlite_db, pipeline_reset):
    """Report water names (金田河/石窟河) resolve through landuse-derived water
    bodies: deterministic clustering of 水域 parcels + LLM evidence assignment,
    aggregated into gazetteer entries with union BSMs."""
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-water-bodies"
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.village_cluster_mapper import (
            _WATER_MARKERS,
            assign_water_bodies,
            build_landuse_bodies,
        )
        from app.contracts.domain.l1_contracts import L1LocationFact
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        bodies = build_landuse_bodies(parcels, _WATER_MARKERS)
        assert len(bodies) >= 3, f"fixture derived {len(bodies)} water bodies"

        llm = _EvidenceLLM({
            "金田河": {
                "cluster_indexes": [bodies[0].index, bodies[5].index],
                "evidence": "金田河由西南至东北贯穿金田村",
            },
            "石窟河": {
                "cluster_indexes": [bodies[1].index],
                "evidence": "主要沿石窟河布置",
            },
        })
        entries = await assign_water_bodies(
            gazetteer, parcels, ["金田河", "石窟河", "公王下河", "水边湖"],
            report, llm=llm,
        )
        assert {e.name for e in entries} == {"金田河", "石窟河"}
        for e in entries:
            gazetteer.upsert(e)
        jt = next(e for e in entries if e.name == "金田河")
        assert jt.source == "water_cluster_map"
        assert jt.entity_uri == "pln:water_body:金田河"
        assert jt.bsms

        facts = [
            L1LocationFact(
                mention=n, normalized_name=n, role="water", aliases=[n],
                spatial_hint=n, source_report_ref="current_report.md",
                dimension_key="natural_environment", confidence=1.0,
            )
            for n in ["金田河", "石窟河", "公王下河", "水边湖"]
        ]
        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
        )
        context.current_parcels = lambda: parcels
        index = PlaceEvidenceIndex.build(context)
        for n in ["金田河", "石窟河"]:
            res = index.resolve_mention(n, role="water")
            assert res.status == "resolved", (n, res.status)
            assert res.candidates[0].source_bsms, n
        # Evidence-less water names stay fail-closed (no spatial extent).
        bare = index.resolve_mention("公王下河", role="water")
        assert not bare.candidates[0].source_bsms
    finally:
        await teardown()

@pytest.mark.asyncio
async def test_village_anchored_landmark_and_facility_resolve(sqlite_db, pipeline_reset):
    """Report entities anchored to a named village (南粤古驿道@炉池,
    祠堂@社前) resolve to the village's LLM-assigned BSM set via the
    village-anchor binding."""
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-village-anchor-2"
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            build_village_clusters,
        )
        from app.contracts.domain.l1_contracts import L1LocationFact
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        parcels = list(bundle.polygons.get("landuse_current") or [])
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        clusters = build_village_clusters(parcels)
        llm = _EvidenceLLM({
            "炉池": {"cluster_indexes": [clusters[0].index], "evidence": "在金田村下属的炉池村"},
            "社前": {"cluster_indexes": [clusters[1].index], "evidence": "在金田村下属的社前村"},
        })
        entries = await assign_villages_to_clusters(
            gazetteer, parcels, ["炉池", "社前"], report, llm=llm
        )
        for e in entries:
            gazetteer.upsert(e)
        luci = next(e for e in entries if e.name == "炉池村")

        facts = [
            L1LocationFact(
                mention="南粤古驿道", normalized_name="南粤古驿道", role="landmark",
                aliases=["南粤古驿道"], spatial_hint="炉池村",
                source_span="地物 | 南粤古驿道 | 炉池村 | 古驿道遗存",
                source_report_ref="r", dimension_key="historical_culture", confidence=0.95,
            ),
            L1LocationFact(
                mention="祠堂", normalized_name="祠堂", role="facility",
                aliases=["祠堂"], spatial_hint="社前村",
                source_span="现状设施 | 祠堂 | 社前村 | 三座祠堂",
                source_report_ref="r", dimension_key="historical_culture", confidence=0.95,
            ),
        ]
        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle, location_facts=facts,
        )
        context.current_parcels = lambda: parcels
        index = PlaceEvidenceIndex.build(context)

        res = index.resolve_mention("南粤古驿道", role="landmark")
        assert res.status == "resolved"
        assert res.candidates[0].source_bsms == luci.bsms
        assert any("village_anchor" in p for p in res.candidates[0].evidence_refs)

        res2 = index.resolve_mention("祠堂", role="facility")
        assert res2.status == "resolved"
        assert res2.candidates[0].source_bsms
        scoped = index.query_facility_bsms("社前村", "祠堂")
        assert scoped.status == "resolved"
        assert scoped.candidates[0].feature_bsm or scoped.candidates[0].geometry_ref
    finally:
        await teardown()

@pytest.mark.asyncio
async def test_complete_ground_report_flow(sqlite_db, pipeline_reset):
    """The complete GROUND flow over typed L1 facts: Phase 1 inventory ->
    Phase 2 collective village partition (ALL report-named villages covered)
    + per-role assignment; audited through the rebuilt evidence index."""
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-ground-report-%s" % uuid.uuid4().hex[:8]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.report_grounder import ground_report
        from app.contracts.domain.l1_contracts import L1LocationFact

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        villages = ["园寨","田坑","社前","分水","清明","塘笃","长塘","炉池","肩丰","营仔","新山","黄竹"]
        facts = [L1LocationFact(mention=v, normalized_name=v, role="village", aliases=[v],
                                spatial_hint="", source_span="socio|%s|" % v,
                                source_report_ref="r", dimension_key="d", confidence=1.0) for v in villages]
        for n in ["金田河", "石窟河"]:
            facts.append(L1LocationFact(mention=n, normalized_name=n, role="water", aliases=[n],
                                        spatial_hint="", source_span="nat|%s|" % n,
                                        source_report_ref="r", dimension_key="d", confidence=1.0))
        facts.append(L1LocationFact(mention="祠堂", normalized_name="祠堂", role="facility", aliases=["祠堂"],
                                    spatial_hint="社前村", source_span="现状设施|祠堂|社前村|",
                                    source_report_ref="r", dimension_key="d", confidence=1.0))

        class PartitionLLM:
            @staticmethod
            def _payload(prompt):
                p = str(prompt)
                if "聚落分配到" in p:
                    return {
                        "园寨": {"candidate_indexes": [0, 1], "evidence": "主要集中于金田村中部的园寨"},
                        "田坑": {"candidate_indexes": [2], "evidence": "分别为：园寨、田坑、社前"},
                        "社前": {"candidate_indexes": [3], "evidence": "马头段、社前以及园寨"},
                        "分水": {"candidate_indexes": [4], "evidence": "园寨、田坑、社前、分水"},
                        "清明": {"candidate_indexes": [5], "evidence": "社前、分水、清明、塘笃"},
                        "塘笃": {"candidate_indexes": [6], "evidence": "分水、清明、塘笃、长塘"},
                        "长塘": {"candidate_indexes": [7], "evidence": "清明、塘笃、长塘、炉池"},
                        "炉池": {"candidate_indexes": [8], "evidence": "塘笃、长塘、炉池、肩丰"},
                        "肩丰": {"candidate_indexes": [9], "evidence": "长塘、炉池、肩丰、营仔"},
                        "营仔": {"candidate_indexes": [10], "evidence": "炉池、肩丰、营仔、新山"},
                        "新山": {"candidate_indexes": [11], "evidence": "肩丰、营仔、新山、黄竹"},
                        "黄竹": {"candidate_indexes": [12, 13, 14, 15], "evidence": "肩丰、营仔、新山、黄竹"},
                    }
                if "水体" in p:
                    return {
                        "金田河": {"candidate_indexes": [0, 5], "evidence": "金田河由西南至东北贯穿金田村"},
                        "石窟河": {"candidate_indexes": [1], "evidence": "主要沿石窟河布置"},
                    }
                return {}

            def with_structured_output(self, schema, **_kwargs):
                owner = self

                class _Runner:
                    async def ainvoke(self, messages):
                        prompt = (
                            messages[-1]["content"]
                            if isinstance(messages, list)
                            else messages
                        )
                        payload = owner._payload(prompt)
                        if "entries" in schema.model_fields:
                            payload = {
                                "entries": [
                                    {"name": name, **item}
                                    for name, item in payload.items()
                                ]
                            }
                        return schema.model_validate(payload)

                return _Runner()

        parcels = list(bundle.polygons.get("landuse_current") or [])
        context = SimpleNamespace(session_id=sid, version=1, kg_version=1,
                                  gazetteer=gazetteer, kg=kg, workspace=bundle,
                                  location_facts=facts)
        context.current_parcels = lambda: parcels
        result = await ground_report(context, facts, report, llm=PartitionLLM(), session_id=sid)

        # A typed response that only lists report names is not enough to
        # allocate residential bodies. Without EvidenceGraph spatial anchors,
        # the mapper must leave the names reviewable instead of nearest-filling
        # every cluster.
        assert result.unresolved, result.summary()
        assert result.grounded < len(result.entities), result.summary()
        assert all(
            not entity.bsms and not entity.geometry_ref
            for entity in result.entities
            if entity.status == "unresolved"
        )
    finally:
        await teardown()


def _parcel(bsm, lon, dlbm="1340"):
    return SimpleNamespace(
        bsm=bsm, name="", dlbm=dlbm, area_sqm=800.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[[lon, 23.0], [lon + 0.001, 23.0],
                             [lon + 0.001, 23.001], [lon, 23.001], [lon, 23.0]]],
        },
    )


def _synthetic_parcels():
    out = []
    for i, lon in enumerate([113.00 + 0.0005 * j for j in range(4)]):
        out.append(_parcel(f"a{i}", lon))
    for i, lon in enumerate([113.05 + 0.0005 * j for j in range(6)]):
        out.append(_parcel(f"b{i}", lon))
    out.append(_parcel("c0", 113.2))
    return out


def test_cluster_conflict_resolution_keeps_strongest_evidence():
    """GER-LLM-style global consistency: a cluster belongs to at most one
    village; the village with the longest report evidence wins the conflict."""
    from app.spatial.grounding.village_cluster_mapper import (
        build_village_clusters,
        map_villages,
    )

    clusters = build_village_clusters(_synthetic_parcels())

    class FakeLLM:
        def with_structured_output(self, schema, **_kwargs):
            class _Runner:
                async def ainvoke(self, _messages):
                    return schema.model_validate({
                        "entries": [
                            {
                                "name": "园寨",
                                "candidate_indexes": [0],
                                "evidence": "园寨位于村域中部",
                            },
                            {
                                "name": "田坑",
                                "candidate_indexes": [0, 2],
                                "evidence": "田坑",
                            },
                        ]
                    })

            return _Runner()

    mapping = asyncio.run(map_villages(
        clusters,
        ["园寨", "田坑"],
        report_text="园寨位于村域中部，田坑位于南部。",
        llm=FakeLLM(),
    ))
    assert mapping["园寨"]["cluster_indexes"] == [0]
    assert mapping["园寨"]["bsms"] == clusters[0].bsms
    # 田坑 lost cluster 0 to 园寨 (longer evidence), keeps only cluster 2.
    assert mapping["田坑"]["cluster_indexes"] == [2]
    assert mapping["田坑"]["bsms"] == clusters[2].bsms


def test_l1_observation_relation_enriches_location_facts():
    """The optimized L1 observation contract extracts 走向/流向/所在村 into
    location + relation, and the compiler carries them into source_span and
    spatial_hint so GROUND can village-anchor the entities."""
    from app.data.ingestion.compiler.profiles.l1_observation import (
        compile_l1_observation,
    )

    obs = [
        {"entity_type": "道路", "name": "Y122乡道", "location": "村北",
         "relation": "东西走向，通往泗水镇中心", "description": "乡道", "scale": ""},
        {"entity_type": "水系", "name": "金田河", "location": "",
         "relation": "西南至东北贯穿金田村，汇入石窟河", "description": "河流", "scale": ""},
        {"entity_type": "现状设施", "name": "供水点", "location": "园寨",
         "relation": "位于园寨中部", "description": "5处供水点", "scale": "5处"},
    ]
    frag = compile_l1_observation(
        dimension_key="traffic",
        content="",
        instruction=json.dumps(obs, ensure_ascii=False),
        report_id="rpt-rel",
    )
    road = next(f for f in frag.location_facts if f.normalized_name == "Y122乡道")
    water = next(f for f in frag.location_facts if f.normalized_name == "金田河")
    fac = next(f for f in frag.location_facts if f.normalized_name == "供水点")
    assert "东西走向" in road.source_span
    assert "汇入石窟河" in water.source_span
    assert "金田村" in water.spatial_hint
    assert "园寨" in fac.source_span
    assert fac.spatial_hint == "园寨"


@pytest.mark.asyncio
async def test_deterministic_village_partition_covers_all(sqlite_db, pipeline_reset):
    """The deterministic path never nearest-fills report-named villages."""
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-det-part-%s" % uuid.uuid4().hex[:8]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.report_grounder import (
            extract_spatial_inventory,
            deterministic_village_partition,
        )
        from app.spatial.grounding.village_cluster_mapper import build_village_clusters
        from app.contracts.domain.l1_contracts import L1LocationFact

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        villages = ["园寨","田坑","社前","分水","清明","塘笃","长塘","炉池","肩丰","营仔","新山","黄竹"]
        facts = [L1LocationFact(mention=v, normalized_name=v, role="village", aliases=[v],
                                spatial_hint="", source_span="socio|%s|" % v,
                                source_report_ref="r", dimension_key="d", confidence=1.0) for v in villages]
        facts.append(L1LocationFact(mention="祠堂", normalized_name="祠堂", role="facility",
                                    aliases=["祠堂"], spatial_hint="社前村",
                                    source_span="现状设施|祠堂|社前村|",
                                    source_report_ref="r", dimension_key="d", confidence=1.0))
        inv = extract_spatial_inventory(report, facts, bundle)
        clusters = build_village_clusters(list(bundle.polygons.get("landuse_current") or []))
        mapping = deterministic_village_partition(inv, bundle, clusters)

        assigned = {k for k, v in mapping.items() if v.get("cluster_indexes")}
        assert not assigned
        assert all(
            "空间就近" not in str(item.get("evidence") or "")
            for item in mapping.values()
        )
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_unresolved_grounding_requires_human_review(sqlite_db, pipeline_reset):
    """Names without graph evidence remain unresolved and reviewable.

    The review queue must not receive a fabricated nearest-cluster BSM.
    """
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-always-land-%s" % uuid.uuid4().hex[:8]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.spatial.grounding.report_grounder import ground_report
        from app.contracts.domain.l1_contracts import L1LocationFact

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        villages = ["园寨","田坑","社前","分水","清明","塘笃","长塘","炉池","肩丰","营仔","新山","黄竹"]
        facts = [L1LocationFact(mention=v, normalized_name=v, role="village", aliases=[v],
                                spatial_hint="", source_span="socio|%s|" % v,
                                source_report_ref="r", dimension_key="d", confidence=1.0) for v in villages]
        for n in ["金田河", "石窟河"]:
            facts.append(L1LocationFact(mention=n, normalized_name=n, role="water", aliases=[n],
                                        spatial_hint="", source_span="nat|%s|" % n,
                                        source_report_ref="r", dimension_key="d", confidence=1.0))
        facts.append(L1LocationFact(mention="祠堂", normalized_name="祠堂", role="facility", aliases=["祠堂"],
                                    spatial_hint="社前村", source_span="现状设施|祠堂|社前村|",
                                    source_report_ref="r", dimension_key="d", confidence=1.0))
        for n, r, hint in [("206国道","road","村北"), ("Y122乡道","road","村北"), ("古树名木","landmark","营仔")]:
            facts.append(L1LocationFact(mention=n, normalized_name=n, role=r, aliases=[n],
                                        spatial_hint=hint, source_span="%s|%s|%s|" % (r, n, hint),
                                        source_report_ref="r", dimension_key="d", confidence=1.0))

        parcels = list(bundle.polygons.get("landuse_current") or [])
        context = SimpleNamespace(session_id=sid, version=1, kg_version=1,
                                  gazetteer=gazetteer, kg=kg, workspace=bundle,
                                  location_facts=facts)
        context.current_parcels = lambda: parcels
        result = await ground_report(context, facts, report, llm=None, session_id=sid)

        assert result.unresolved, "unresolved names must remain visible"
        assert len(result.entities) == len(facts), (len(result.entities), len(facts))
        assert any(e.status == "unresolved" for e in result.entities)

        review_names = {r.name for r in result.reviews}
        assert review_names & {"206国道", "Y122乡道", "古树名木"}

        item = next(
            r
            for r in result.reviews
            if r.name in {"Y122乡道", "古树名木"}
        )
        assert item.status == "pending"
        assert item.recommended_bsms == []
        queue = result.queue
        assert queue is not None
        decided = queue.decide(sid, item.name, item.role, accept=True)
        assert decided is not None and decided.status == "confirmed"
        override = queue.decide(sid, "206国道", "road", accept=False, override_bsms=["bsm-human-1"])
        assert override is not None and override.status == "overridden"
        assert override.recommended_bsms == ["bsm-human-1"]
    finally:
        await teardown()


@pytest.mark.asyncio
async def test_hydration_production_path_grounds_facts(sqlite_db, pipeline_reset, monkeypatch):
    """The production hydration path keeps unanchored L1 names reviewable.

    A typed model response cannot manufacture a village geometry when the
    persisted L1 snapshot and EvidenceGraph have no cross-source spatial
    anchor.
    """
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-hydrate-%s" % uuid.uuid4().hex[:8]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        from app.application.sessions.session_bundle import build_session_bundle
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.workflow.layers.context_bootstrap import _hydrate_l1_spatial_facts
        from app.contracts.domain.l1_contracts import L1LocationFact, L1Snapshot
        from app.infrastructure.artifacts.runtime import ARTIFACT_SCHEMA_VERSION

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        report = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        villages = ["园寨","田坑","社前","分水","清明","塘笃","长塘","炉池","肩丰","营仔","新山","黄竹"]
        facts = [L1LocationFact(mention=v, normalized_name=v, role="village", aliases=[v],
                                spatial_hint="", source_span="socio|%s|" % v,
                                source_report_ref="r", dimension_key="d", confidence=1.0) for v in villages]
        facts.append(L1LocationFact(mention="金田河", normalized_name="金田河", role="water", aliases=["金田河"],
                                    spatial_hint="", source_span="nat|金田河|",
                                    source_report_ref="r", dimension_key="d", confidence=1.0))
        facts.append(L1LocationFact(mention="祠堂", normalized_name="祠堂", role="facility", aliases=["祠堂"],
                                    spatial_hint="社前村", source_span="现状设施|祠堂|社前村|",
                                    source_report_ref="r", dimension_key="d", confidence=1.0))
        snapshot = L1Snapshot(location_facts=facts)

        state = {"session_id": sid, "context_version": "1",
                 "artifact_schema_version": str(ARTIFACT_SCHEMA_VERSION),
                 "artifact_refs": {}}
        from app.infrastructure.artifacts.runtime import store_artifact
        ref = store_artifact(state, "l1_snapshot", "l1", "L1Snapshot", snapshot)
        state["artifact_refs"]["l1_snapshot"] = ref

        context = SimpleNamespace(
            session_id=sid, version=1, kg_version=1,
            gazetteer=gazetteer, kg=kg, workspace=bundle,
            reports={"socio_economic": {"content": report}},
            ports=None, evidence_graph=None, evidence_graph_key="", location_facts=[],
        )
        context.current_parcels = lambda: list(bundle.polygons.get("landuse_current") or [])

        class HydrateLLM:
            @staticmethod
            def _payload(prompt):
                p = str(prompt)
                if "聚落分配到" in p:
                    mapping = {
                        v: {
                            "candidate_indexes": [0 if i == 0 else i + 1],
                            "evidence": "园寨、田坑、社前",
                        }
                        for i, v in enumerate(villages)
                    }
                    mapping["园寨"] = {
                        "candidate_indexes": [0, 1],
                        "evidence": "主要集中于金田村中部的园寨",
                    }
                    return mapping
                if "水体" in p:
                    return {
                        "金田河": {
                            "candidate_indexes": [0, 5],
                            "evidence": "金田河由西南至东北贯穿金田村",
                        }
                    }
                return {}

            def with_structured_output(self, schema, **_kwargs):
                owner = self

                class _Runner:
                    async def ainvoke(self, messages):
                        prompt = (
                            messages[-1]["content"]
                            if isinstance(messages, list)
                            else messages
                        )
                        payload = owner._payload(prompt)
                        if "entries" in schema.model_fields:
                            payload = {
                                "entries": [
                                    {"name": name, **item}
                                    for name, item in payload.items()
                                ]
                            }
                        return schema.model_validate(payload)

                return _Runner()

        import app.spatial.grounding.report_grounder as rg
        monkeypatch.setenv("GROUND_LLM_ENABLED", "true")
        monkeypatch.setattr(rg, "create_grounding_llm", lambda: HydrateLLM())

        await _hydrate_l1_spatial_facts(state, context)

        assert context.evidence_graph is not None
        unresolved = []
        for f in facts:
            res = context.evidence_graph.resolve_mention(f.normalized_name, role=f.role)
            cand = res.candidates[0] if res.candidates else None
            if cand is None or not (cand.source_bsms or cand.geometry_ref):
                unresolved.append(f.normalized_name)
        assert unresolved
    finally:
        await teardown()
