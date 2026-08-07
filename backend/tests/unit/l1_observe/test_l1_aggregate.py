"""Tests for l1_aggregate - merge fragments into L1Snapshot + gate + review."""
from __future__ import annotations

import copy
import json

import pytest

from app.agent.l1_observe.aggregate import l1_aggregate, merge_fragments
from app.services.artifact_store import FilesystemArtifactStore
from app.services.review_package import read_review_package


def test_merge_fragments_combines_fields(sample_fragments):
    snap = merge_fragments(sample_fragments, run_id="r1")
    assert len(snap.facts) == 2
    assert "基本农田保护红线" in snap.constraints
    assert any("闲置宅基地" in o for o in snap.opportunities)
    assert len(snap.dimension_provenance) == 2


def test_merge_fragments_dedups_repeated_facts(sample_fragments):
    frags = sample_fragments + [copy.deepcopy(sample_fragments[0])]
    snap = merge_fragments(frags, run_id="r1")
    assert snap.facts.count("[socio_economic] 人口: 村域人口 3200 人") == 1


@pytest.mark.asyncio
async def test_l1_aggregate_produces_snapshot_and_review(tmp_path, monkeypatch):
    run_id = "r1"
    session_id = "s1"

    fake_reports = {
        "socio_economic": {
            "content": "# 社会经济\n村域人口 3200 人",
            "knowledge_sources": None,
            "summary": json.dumps({"dimension_key": "socio_economic", "text_summary": "人口 3200"}),
            "report_id": "rpt-socio-v1",
        },
        "land_use": {
            "content": (
                "# 现状用地\n"
                "## 控制线\n- 基本农田保护红线\n"
                "## 用地结构\n"
                "| 地类 | 面积(公顷) | 占比(%) |\n"
                "| --- | --- | --- |\n"
                "| 水田 | 120.0 | 46.2 |\n"
            ),
            "knowledge_sources": None,
            "summary": json.dumps({"dimension_key": "land_use", "text_summary": "水田 120 公顷"}),
            "report_id": "rpt-landuse-v1",
        },
    }

    async def fake_get_layer_reports_with_sources(self, session_id, layer):
        return fake_reports

    monkeypatch.setattr(
        "app.services.report_store.ReportStore.get_layer_reports_with_sources",
        fake_get_layer_reports_with_sources,
    )

    state = {"session_id": session_id, "run_id": run_id, "context_version": "v1"}

    result = await l1_aggregate(state, base_dir=str(tmp_path))

    assert "l1_snapshot_ref" in result
    assert result["artifact_refs"]["l1_snapshot"]["artifact_type"] == "L1Snapshot"
    assert "l1_gate_decision" in result
    assert "l1_review_id" in result

    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    snap_refs = store.list_by_module("l1_observe", run_id=run_id)
    assert len(snap_refs) == 1
    assert snap_refs[0].artifact_type == "L1Snapshot"
    payload = store.retrieve(snap_refs[0])
    assert payload["facts"]
    assert payload["constraints"]
    assert payload["classification_refs"]
    assert payload["sources"]

    review_id = result["l1_review_id"]
    pkg = read_review_package(run_id, "l1_observe", review_id, base_dir=str(tmp_path))
    assert "事实" in pkg.summary_md
    assert "证据缺口" in pkg.summary_md

    gate = result["l1_gate_decision"]
    assert gate["passed"] is True
    assert gate["feedback_route"] is None


@pytest.mark.asyncio
async def test_l1_aggregate_no_advisory_crosswalks_import():
    import ast
    import pathlib

    agg_path = pathlib.Path("app/agent/l1_observe/aggregate.py")
    tree = ast.parse(agg_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            assert "advisory_crosswalks" not in module, f"forbidden import: {module}"
