"""Tests for L1 review package builder."""
from __future__ import annotations

from app.agent.l1_observe.review import (
    build_l1_review_package,
    build_preview_geojson,
    build_summary_md,
    build_trace_json,
)
from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.l1_contracts import EvidenceGap, L1Snapshot
from app.modules.schema.contracts.review_contracts import ReviewPackage, ReviewStatus
from app.modules.schema.contracts.workflow_contracts import GateDecision


def _snapshot() -> L1Snapshot:
    return L1Snapshot(
        context_version="v1",
        artifact_id="l1-001",
        facts=["[socio_economic] 村域人口 3200 人"],
        constraints=["基本农田保护红线"],
        issues=[],
        opportunities=["闲置宅基地可盘活"],
        evidence_gaps=[EvidenceGap(gap_id="g1", dimension="infrastructure", description="缺水网")],
        sources=[],
        classification_refs=[
            ClassificationRef(system="gbt21010", code="0101", canonical_name="水田", source="ingested"),
        ],
    )


def _artifact_ref() -> ArtifactRef:
    return ArtifactRef(
        context_version="v1", artifact_id="l1-001", module="l1_observe",
        run_id="r1", artifact_type="L1Snapshot", revision="v1",
    )


def _gate(passed: bool) -> GateDecision:
    return GateDecision(
        stage="l1", passed=passed,
        feedback_route=None if passed else "EXPLORE",
        evidence_requests=[] if passed else ["缺水网"],
        context_version="v1", artifact_id="l1-001",
    )


def test_build_summary_md_has_five_required_sections():
    md = build_summary_md(_snapshot(), _gate(passed=True))
    for section in ("事实", "证据", "约束", "问题", "证据缺口"):
        assert section in md


def test_build_summary_md_includes_gate_outcome():
    md = build_summary_md(_snapshot(), _gate(passed=False))
    assert "EXPLORE" in md or "缺水网" in md


def test_build_trace_json_carries_dimension_provenance():
    from app.modules.schema.contracts.provenance import Provenance

    snap = _snapshot()
    snap.dimension_provenance = [
        Provenance(source="l1_observe", run_id="r1", module="l1_observe", trace=["socio_economic", "rpt-1"]),
    ]
    trace = build_trace_json(snap, dimension_reports_meta={"socio_economic": {"report_id": "rpt-1"}})
    assert trace["dimension_provenance"][0]["trace"][0] == "socio_economic"


def test_build_preview_geojson_is_valid_feature_collection():
    gj = build_preview_geojson(_snapshot())
    assert gj["type"] == "FeatureCollection"
    assert isinstance(gj["features"], list)


def test_build_l1_review_package_returns_awaiting_review():
    pkg = build_l1_review_package(
        snapshot=_snapshot(),
        artifact_ref=_artifact_ref(),
        gate_decision=_gate(passed=True),
        run_id="r1",
    )
    assert isinstance(pkg, ReviewPackage)
    assert pkg.module == "l1_observe"
    assert pkg.run_id == "r1"
    assert pkg.status == ReviewStatus.AWAITING_REVIEW
    assert pkg.artifact_ref is not None
    assert pkg.artifact_ref.artifact_id == "l1-001"
    assert pkg.summary_md
    assert pkg.trace_json
    assert pkg.preview_geojson is not None
