"""Tests for EXPLORE access layer: access tools, summaries, facade, _optimize_semantics.

Covers:
  - 6 access tools (bundle_overview / spatial_context / spatial_features /
    layer_reports / knowledge_graph / rag_search)
  - summaries builders (ReportSummaryIndex + SpatialCognitionSummary)
  - ExploreAccess facade (snapshot-first + unknown-kind error)
  - _optimize_semantics regression (L2/L3 no longer blocked)
"""

import pytest

from tests.unit.test_bundle_serialization import _build_sample_bundle


def _make_kg():
    """A minimal fake PlanningKG-shaped object for query dispatch."""
    class _FakeKG:
        def __init__(self):
            self.g = _FakeGraph()
    class _FakeGraph:
        def triples(self, pattern):
            return iter(())
        def subjects(self, *a, **k):
            return iter(())
    return _FakeKG()


async def _patch_bundle(monkeypatch, bundle=None):
    """Point access shared helpers at a fixed bundle (snapshot-first short-circuit)."""
    bundle = bundle if bundle is not None else _build_sample_bundle()
    monkeypatch.setattr(
        "app.tools.access.bundle.resolve_bundle",
        _async_returns(bundle),
    )
    monkeypatch.setattr(
        "app.tools.access.reports.resolve_bundle",
        _async_returns(bundle),
    )
    monkeypatch.setattr(
        "app.tools.access.knowledge.session_kg",
        lambda session_id: None,
    )
    monkeypatch.setattr(
        "app.tools.access.rag.resolve_bundle",
        _async_returns(bundle),
    )
    monkeypatch.setattr(
        "app.agent.explore.summaries.resolve_bundle",
        _async_returns(bundle),
    )
    return bundle


def _async_returns(value):
    async def _f(*args, **kwargs):
        return value
    return _f


# ============================================================
# bundle_overview
# ============================================================

@pytest.mark.asyncio
async def test_bundle_overview_impl(monkeypatch):
    from app.tools.access.bundle import bundle_overview_impl

    await _patch_bundle(monkeypatch)
    payload = await bundle_overview_impl("sess-001")

    assert payload["village_name"] == "金田村"
    assert payload["planning_period"] == "2022-2035年"
    assert payload["admin"]["province"] == "广东省"
    assert payload["parcel_count"] == 1
    assert payload["total_area_ha"] == 1.2
    assert payload["spatial_groups"]["polygons"]["landuse_current"]["count"] == 1
    assert payload["spatial_groups"]["lines"]["roads_current"]["count"] == 1
    assert len(payload["documents"]) == 2
    assert payload["layer_reports"]["1"] == ["location"]
    assert "_token_estimate" in payload
    # 概览不含原始坐标
    assert "geometry" not in str(payload["spatial_groups"])


# ============================================================
# spatial_context
# ============================================================

@pytest.mark.asyncio
async def test_spatial_context_without_kg(monkeypatch):
    from app.tools.access.bundle import spatial_context_impl

    await _patch_bundle(monkeypatch)
    payload = await spatial_context_impl("sess-001")

    assert payload["parcel_count"] == 1
    assert "kg_cognition_error" not in payload
    assert "kg_cognition" not in payload


@pytest.mark.asyncio
async def test_spatial_context_with_kg(monkeypatch):
    from app.tools.access import bundle as bundle_mod
    from app.tools.access.bundle import spatial_context_impl

    await _patch_bundle(monkeypatch)
    monkeypatch.setattr(
        bundle_mod, "session_kg", lambda session_id: _make_kg(),
    )
    monkeypatch.setattr(
        "app.modules.kg.queries.cognition.get_village_cognition",
        lambda kg, village_name="", mode="full", token_budget=4000: _DualPayloadStub(),
    )
    payload = await spatial_context_impl("sess-001")

    assert payload["kg_cognition"]["semantic"]["context_block"]["parcel_count"] == 5
    assert payload["kg_cognition"]["structured"]["total_count"] == 5


class _DualPayloadStub:
    def __init__(self):
        self.semantic = {
            "context_block": {"village": "金田村", "parcel_count": 5, "total_area_ha": 100.0},
            "layer_cards": [],
            "constraint_block": {},
        }
        self.structured = {"total_count": 5}
        self.token_estimate = 10
        self.truncated = False
        self.next_cursor = None


# ============================================================
# spatial_features
# ============================================================

@pytest.mark.asyncio
async def test_spatial_features_metadata_only(monkeypatch):
    from app.tools.access.bundle import spatial_features_impl

    bundle = await _patch_bundle(monkeypatch)
    payload = await spatial_features_impl("sess-001", group="polygons")

    landuse = payload["polygons"]["landuse_current"]
    assert landuse["count"] == 1
    assert landuse["shown"] == 1
    assert landuse["features"][0]["bsm"] == "001"
    assert landuse["features"][0]["dlbm"] == "0101"
    # 默认不含几何
    assert "geometry" not in landuse["features"][0]


@pytest.mark.asyncio
async def test_spatial_features_include_geometry(monkeypatch):
    from app.tools.access.bundle import spatial_features_impl

    await _patch_bundle(monkeypatch)
    payload = await spatial_features_impl("sess-001", group="polygons", include_geometry=True)

    geom = payload["polygons"]["landuse_current"]["features"][0]["geometry"]
    assert geom["type"] == "Polygon"
    assert "coordinates" in geom


# ============================================================
# layer_reports
# ============================================================

@pytest.mark.asyncio
async def test_layer_reports_summary_first(monkeypatch):
    from app.tools.access.reports import layer_reports_impl

    await _patch_bundle(monkeypatch)
    payload = await layer_reports_impl("sess-001", layer=1)

    loc = payload["1"]["location"]
    assert loc["dimension_key"] == "location"
    assert loc["layer"] == 1
    assert loc["report_available"] is True
    assert "content" not in loc
    assert "summary" in loc


@pytest.mark.asyncio
async def test_layer_reports_include_content(monkeypatch):
    from app.tools.access.reports import layer_reports_impl

    await _patch_bundle(monkeypatch)
    payload = await layer_reports_impl("sess-001", layer=1, include_content=True)

    assert "content" in payload["1"]["location"]
    assert payload["1"]["location"]["content"] == "## 区位分析\n..."


@pytest.mark.asyncio
async def test_layer_reports_filter_by_dim(monkeypatch):
    from app.tools.access.reports import layer_reports_impl

    await _patch_bundle(monkeypatch)
    payload = await layer_reports_impl("sess-001", layer=3, dim_key="project_bank")

    assert set(payload.keys()) == {"3", "_token_estimate"}
    assert "project_bank" in payload["3"]
    assert "location" not in payload["3"]


# ============================================================
# knowledge_graph
# ============================================================

@pytest.mark.asyncio
async def test_knowledge_graph_no_kg(monkeypatch):
    from app.tools.access.knowledge import knowledge_graph_impl

    await _patch_bundle(monkeypatch)
    payload = await knowledge_graph_impl("sess-001", kind="cognition")

    assert payload["success"] is False
    assert "无 session KG" in payload["error"]


@pytest.mark.asyncio
async def test_knowledge_graph_unknown_kind(monkeypatch):
    from app.tools.access import knowledge as knowledge_mod
    from app.tools.access.knowledge import knowledge_graph_impl

    await _patch_bundle(monkeypatch)
    monkeypatch.setattr(knowledge_mod, "session_kg", lambda session_id: _make_kg())
    payload = await knowledge_graph_impl("sess-001", kind="nonsense")

    assert payload["success"] is False
    assert "未知查询类型" in payload["error"]


# ============================================================
# rag_search
# ============================================================

@pytest.mark.asyncio
async def test_rag_search_filtered_keyword(monkeypatch):
    from app.tools.access.rag import rag_search_impl

    bundle = _build_sample_bundle()
    bundle.documents.planning_texts.append(
        {"source": "constraints", "name": "约束条件", "content": "生态保护红线范围内禁止建设；耕地保护面积不少于 127 公顷。"}
    )
    await _patch_bundle(monkeypatch, bundle=bundle)

    payload = await rag_search_impl("sess-001", query="耕地保护", source="constraints")

    assert payload["scope"] == "filtered"
    assert payload["matched_inventory"] == 1
    assert payload["results"]
    assert payload["results"][0]["source"] == "constraints"


@pytest.mark.asyncio
async def test_rag_search_filter_no_match(monkeypatch):
    from app.tools.access.rag import rag_search_impl

    await _patch_bundle(monkeypatch)
    payload = await rag_search_impl("sess-001", query="生态红线", source="constraints")

    assert payload["results"] == []
    assert payload["matched_inventory"] == 0


@pytest.mark.asyncio
async def test_rag_search_vector_scoped_to_inventory(monkeypatch):
    from app.tools.access import rag as rag_mod
    from app.tools.access.rag import rag_search_impl

    bundle = _build_sample_bundle()
    bundle.documents.planning_texts = [
        {"source": "upload", "name": "input.md", "content": "村庄人口 500 人"},
    ]
    await _patch_bundle(monkeypatch, bundle=bundle)

    class _FakeRagService:
        def list_documents(self):
            return [{"source": "input.md", "chunk_count": 2}]

        def search(self, query, top_k=5):
            return [{
                "content": "人口结构：500人",
                "metadata": {"source": "input.md", "doc_type": "report"},
            }]

    monkeypatch.setattr(rag_mod, "_rag_service", lambda: _FakeRagService())
    payload = await rag_search_impl("sess-001", query="人口")

    assert payload["scope"] == "session_inventory"
    assert payload["indexed_in_inventory"] == 1
    assert any(r.get("source") == "vector" for r in payload["results"])


# ============================================================
# index_bundle_texts
# ============================================================

@pytest.mark.asyncio
async def test_index_bundle_texts_skips_already_indexed(monkeypatch):
    from app.tools.access import rag as rag_mod
    from app.tools.access.rag import index_bundle_texts_impl

    bundle = _build_sample_bundle()
    bundle.documents.planning_texts = [
        {"source": "constraints", "name": "约束.md", "content": "生态红线内禁止建设。"},
        {"source": "village_data", "name": "现状.md", "content": "人口 500 人。"},
    ]
    await _patch_bundle(monkeypatch, bundle=bundle)

    class _FakeRagService:
        def __init__(self):
            self._indexed = {"约束.md"}

        def list_documents(self):
            return [{"source": s, "chunk_count": 1} for s in self._indexed]

        def add_markdown_document(self, file_path, use_llm_inference=True):
            self._indexed.add(file_path.split("\\")[-1])
            return {"status": "success", "message": "added"}

    service = _FakeRagService()
    monkeypatch.setattr(rag_mod, "_rag_service", lambda: service)

    payload = await index_bundle_texts_impl("sess-001")

    assert payload["added"] == 1
    assert payload["skipped"] == 1
    assert payload["errors"] == []


# ============================================================
# summaries
# ============================================================

@pytest.mark.asyncio
async def test_report_summary_index(monkeypatch):
    from app.agent.explore.summaries import build_report_summary_index

    bundle = await _patch_bundle(monkeypatch)
    index = await build_report_summary_index(bundle=bundle)

    assert index["village_name"] == "金田村"
    assert index["total_dimensions"] == 2
    assert index["spatial_relevant_count"] >= 1
    assert "location" in index["entries"]
    entry = index["entries"]["location"]
    assert entry["layer"] == 1
    assert entry["spatial_relevance"] in ("high", "medium", "low")
    assert entry["report_available"] is True
    assert isinstance(entry["key_spatial_findings"], list)


@pytest.mark.asyncio
async def test_spatial_cognition_prompt_section(monkeypatch):
    from app.agent.explore import summaries as summaries_mod
    from app.agent.explore.summaries import build_spatial_cognition

    await _patch_bundle(monkeypatch)
    monkeypatch.setattr(summaries_mod, "session_kg", lambda session_id: _make_kg())
    monkeypatch.setattr(
        "app.modules.kg.queries.cognition.get_village_cognition",
        lambda kg, village_name="", mode="full", token_budget=4000: _DualPayloadStub(),
    )
    cognition = await build_spatial_cognition("sess-001", "location", 1)

    assert cognition["dimension_key"] == "location"
    assert cognition["layer"] == 1
    assert cognition["kg_cognition"]["semantic"]["context_block"]["parcel_count"] == 5
    assert "村域概况" in cognition["prompt_section"]


# ============================================================
# ExploreAccess facade
# ============================================================

@pytest.mark.asyncio
async def test_facade_snapshot_first_overview(monkeypatch):
    from app.services.explore_access import ExploreAccess

    await _patch_bundle(monkeypatch)
    payload = await ExploreAccess.get_instance().get_context_block("sess-001", "overview")

    assert payload["success"] is True
    assert payload["kind"] == "overview"
    assert payload["village_name"] == "金田村"


@pytest.mark.asyncio
async def test_facade_unknown_kind(monkeypatch):
    from app.services.explore_access import ExploreAccess

    payload = await ExploreAccess.get_instance().get_context_block("sess-001", "bogus")

    assert payload["success"] is False
    assert "未知 context kind" in payload["error"]


@pytest.mark.asyncio
async def test_facade_empty_session(monkeypatch):
    from app.services.explore_access import ExploreAccess

    payload = await ExploreAccess.get_instance().get_context_block("", "overview")

    assert payload["success"] is False


# ============================================================
# _optimize_semantics regression (L2/L3 no longer blocked)
# ============================================================

@pytest.mark.asyncio
async def test_optimize_semantics_l2_l3_not_blocked(monkeypatch):
    from app.agent.analysis.node import _optimize_semantics

    async def _fake_cognition(session_id, dim_key, dim_layer):
        return {
            "prompt_section": f"## 空间语义补充（EXPLORE KG 认知）\n**{dim_key}** layer={dim_layer}\n",
        }

    monkeypatch.setattr(
        "app.agent.explore.summaries.build_spatial_cognition", _fake_cognition,
    )

    l2 = await _optimize_semantics("traffic", 2, {"session_id": "sess-001"}, None)
    l3 = await _optimize_semantics("traffic", 3, {"session_id": "sess-001"}, None)

    # L2/L3 不再被早期 return "" 阻断
    assert "layer=2" in l2
    assert "layer=3" in l3


@pytest.mark.asyncio
async def test_optimize_semantics_no_session_returns_empty():
    from app.agent.analysis.node import _optimize_semantics

    assert await _optimize_semantics("land_use", 1, {}, None) == ""


@pytest.mark.asyncio
async def test_optimize_semantics_zone_hint_for_land_use(monkeypatch):
    from app.agent.analysis.node import _optimize_semantics

    async def _fake_cognition(session_id, dim_key, dim_layer):
        return {"prompt_section": "## 空间语义补充\n"}

    monkeypatch.setattr(
        "app.agent.explore.summaries.build_spatial_cognition", _fake_cognition,
    )

    section = await _optimize_semantics("land_use", 1, {"session_id": "sess-001"}, None)
    assert "规划分区候选集提示" in section
