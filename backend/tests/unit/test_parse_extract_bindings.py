"""C 子任务：PARSE extract_bindings 单测（llm=None 确定性路径 + fake KG/bundle）。

村内/村外规则（实测验证）：
  - annotation.geojson 中 分类='村名' 的 4 个注记点（八社村/上举村/符坑村/文贵村）
    全部位于金田村村界外 → 是毗邻行政村（村外），禁止绑定；
  - 村内 12 个自然村（田坑/黄竹/园寨等）无注记点 → 以"地块中心点在村界内"为空间基座。
"""
from pathlib import Path

import pytest

from app.agent.gis.parse.agent import PendingBinding, extract_bindings
from app.modules.kg import get_kg_manager
from app.modules.schema.types.base import PolygonFeature
from app.modules.schema.types.canonical import VillageBundle
from app.modules.schema.types.spatial_types import CurrentAnnotation


class _FakeKG:
    """只支持 get_entity_by_bsm 语义的 fake；get_parcels_semantic_list 抛错走 fallback。"""

    def __init__(self, known_bsms):
        self.known_bsms = set(known_bsms)

    def get_entity_by_bsm(self, bsm, entity_type=None):
        if bsm in self.known_bsms:
            return {"uri": f"pln:parcel_{bsm}", "type": "Parcel"}
        return None


_BOUNDARY = {
    "type": "MultiPolygon",
    "coordinates": [[[[116.00, 24.80], [116.10, 24.80], [116.10, 24.84], [116.00, 24.84], [116.00, 24.80]]]],
}


def _make_bundle_with_boundary() -> VillageBundle:
    bundle = VillageBundle(village_name="金田村")
    bundle.add(PolygonFeature(geometry=_BOUNDARY, layer_type="admin_area"))
    bundle.add(
        PolygonFeature(
            geometry={
                "type": "MultiPolygon",
                "coordinates": [[[[116.04, 24.83], [116.06, 24.83], [116.06, 24.84], [116.04, 24.84], [116.04, 24.83]]]],
            },
            bsm="441426211000049104", layer_type="landuse_current",
        ),
    )
    # 村外毗邻行政村注记点（实测在村界外）
    bundle.add(
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.047, 24.850]},
            layer_type="current_annotation", text="八社村", category="村名",
        ),
    )
    return bundle


REPORT = (
    "田坑自然村（BSM 441426211000049104）现有耕地12.5公顷，"
    "黄竹自然村依托南药种植发展林下经济。"
)


def test_deterministic_extractor_picks_village_bsm_pairs():
    from app.agent.gis.parse.agent import _extract_bindings_deterministic

    bindings = _extract_bindings_deterministic({"land_use": REPORT})
    assert len(bindings) >= 1
    b = bindings[0]
    assert b.natural_village == "田坑自然村"
    assert "441426211000049104" in b.candidate_bsms
    assert b.source_report_keys == ["land_use"]


def test_validate_accepts_internal_village_without_annotation():
    """田坑自然村无注记点，但地块中心在村界内 → 通过。"""
    from app.agent.gis.parse.agent import _validate_binding

    binding = PendingBinding(
        natural_village="田坑自然村", feature_type="parcel",
        candidate_bsms=["441426211000049104"], description="田坑耕地", confidence=0.8,
        source_report_keys=["land_use"],
    )
    ok, reason = _validate_binding(binding, _FakeKG({"441426211000049104"}), _make_bundle_with_boundary())
    assert ok, reason


def test_validate_rejects_external_admin_village():
    """八社村 注记点在村界外 → 拒绝（村外毗邻行政村，非本村居民点）。"""
    from app.agent.gis.parse.agent import _validate_binding

    binding = PendingBinding(
        natural_village="八社村", feature_type="parcel",
        candidate_bsms=["441426211000049104"], description="八社村", confidence=0.9,
        source_report_keys=["land_use"],
    )
    ok, reason = _validate_binding(binding, _FakeKG({"441426211000049104"}), _make_bundle_with_boundary())
    assert ok is False
    assert "村外" in reason


def test_validate_rejects_internal_name_bound_to_outside_parcel():
    """村内村名绑定到村界外地块 → 拒绝。"""
    from app.agent.gis.parse.agent import _validate_binding

    bundle = _make_bundle_with_boundary()
    bundle.add(
        PolygonFeature(
            geometry={
                "type": "MultiPolygon",
                "coordinates": [[[[116.12, 24.80], [116.13, 24.80], [116.13, 24.81], [116.12, 24.81], [116.12, 24.80]]]],
            },
            bsm="441426211000077777", layer_type="landuse_current",
        ),
    )
    binding = PendingBinding(
        natural_village="田坑自然村", feature_type="parcel",
        candidate_bsms=["441426211000077777"], description="", confidence=0.8,
        source_report_keys=["land_use"],
    )
    ok, reason = _validate_binding(binding, _FakeKG({"441426211000077777"}), bundle)
    assert ok is False


def test_validate_rejects_unknown_bsm():
    from app.agent.gis.parse.agent import _validate_binding

    binding = PendingBinding(
        natural_village="田坑自然村", feature_type="parcel",
        candidate_bsms=["441426211000099999"], description="", confidence=0.9,
        source_report_keys=[],
    )
    ok, reason = _validate_binding(binding, _FakeKG(set()), _make_bundle_with_boundary())
    assert ok is False
    assert "not in KG" in reason


def test_extract_bindings_full_flow(monkeypatch, tmp_path: Path):
    import asyncio

    import app.agent.gis.parse.agent as parse_mod
    import app.modules.kg.memory as mem_mod

    fake_store = mem_mod.SemanticMemoryStore()
    monkeypatch.setattr(mem_mod, "get_memory_dir", lambda: tmp_path)
    monkeypatch.setattr(parse_mod, "_get_semantic_memory", lambda: fake_store)

    manager = get_kg_manager()
    kg = _FakeKG({"441426211000049104"})
    manager.register_session("sess-extract", kg)

    try:
        stats = asyncio.run(
            extract_bindings(
                session_id="sess-extract",
                wave=1,
                reports={"land_use": REPORT},
                llm=None,
                kg=kg,
                bundle=_make_bundle_with_boundary(),
            )
        )
    finally:
        manager.remove_session("sess-extract")

    assert stats["extracted"] >= 1
    assert stats["written"] >= 1
    assert len(fake_store.entity_annotations) >= 1
    # 持久化文件已写入
    assert (tmp_path / "sess-extract_round_1.json").exists()
