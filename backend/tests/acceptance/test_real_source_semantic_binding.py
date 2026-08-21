"""Explicit opt-in acceptance for the production MiniMax source-semantic boundary.

These tests are intentionally skipped in ordinary runs.  Each selected smoke
case spends two provider calls for one unresolved source label and proves only
the closed-set semantic binding contract; geometry is still supplied by the
bundle in the downstream EvidenceGraph path.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

from app.contracts.domain.l1_contracts import L1Fact
from app.data.model.spatial_types import CurrentAnnotation
from app.infrastructure.llm.instructor_client import close_cached_clients
from app.evidence.identity.source_semantic_runtime import classify_source_semantics


def _enabled() -> bool:
    from app.core.settings import MINIMAX_API_KEY

    return bool(
        MINIMAX_API_KEY
        and os.getenv("RUN_REAL_SOURCE_SEMANTIC", "").strip().lower()
        in {"1", "true", "yes", "on"}
    )


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.slow,
    pytest.mark.skipif(
        not _enabled(),
        reason=(
            "set RUN_REAL_SOURCE_SEMANTIC=true and configure MINIMAX_API_KEY "
            "to spend the explicit two-call source-semantic smoke test"
        ),
    ),
]


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_real_minimax_parses_multisource_location_scope():
    """One bounded call must expose every local class needed by the query."""

    from app.spatial.grounding.flash_mention_extractor import (
        extract_spatial_reference_spec,
    )

    query = (
        "请利用炉池地址相关的地质灾害点及其相邻地块，定位炉池自然村内"
        "适合建设文化服务设施的一小片用地"
    )
    try:
        spec = await extract_spatial_reference_spec(query, raise_on_failure=True)

        assert spec is not None
        scopes = set(spec.all_retrieval_scopes())
        assert {"hazards", "parcels", "facilities"}.issubset(scopes)
        assert spec.semantic_terms
        assert all("".join(term.split()) in "".join(query.split()) for term in spec.semantic_terms)
        dumped = spec.model_dump(mode="json")
        assert not any(
            token in str(dumped).casefold()
            for token in ("bundle://", "point(", "linestring(", "source_feature_id")
        )
    finally:
        await close_cached_clients()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_real_minimax_accepts_l1_constrained_facility_binding():
    feature = CurrentAnnotation(
        geometry={"type": "Point", "coordinates": [116.0, 24.8]},
        bsm="44142611000000000001",
        text="祠",
        category="现状设施点",
        _raw={
            "source_feature_id": "feature:real-source-semantic:shrine",
            "source_dataset": "mvp-live-smoke",
        },
    )
    fact = L1Fact(
        fact_id="l1:real-source-semantic:shrine",
        statement="社前村有祠堂设施",
        fact_kind="document_observation",
        semantic_type="facility",
        attributes={"normalized_name": "祠堂", "location": "社前村"},
        value=1,
        unit="处",
        source_refs=["report:real-source-semantic"],
        source_snapshot_ref="snapshot:real-source-semantic",
    )
    context = SimpleNamespace(
        session_id="real-source-semantic-smoke",
        version=1,
        kg_version=1,
        kg=None,
        village_name="社前村",
        workspace=SimpleNamespace(
            points={"annotations_current": [feature], "facilities_current": []},
            lines={"roads_current": []},
            polygons={},
        ),
        current_parcels=lambda: [],
        location_facts=[],
        l1_fact_records=[fact],
        l1_snapshot_ref="snapshot:real-source-semantic",
        data_snapshot=None,
        content_hash="digest:real-source-semantic",
        source_semantic_decisions={},
        source_semantic_fingerprint="",
        source_semantic_diagnostics=[],
        evidence_graph_key="graph:real-source-semantic",
    )

    try:
        snapshot, accepted, diagnostics = await classify_source_semantics(
            context,
            enabled=True,
        )

        assert snapshot is not None
        assert diagnostics == []
        assert set(accepted) == {"feature:real-source-semantic:shrine"}
        decision = snapshot.decisions[0]
        assert decision.status == "accepted"
        assert decision.semantic_type == "祠堂"
        assert len(decision.proposal_digests) == 2
        assert context.evidence_graph is not None
        assert context.source_semantic_fingerprint == snapshot.fingerprint

        from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
        from app.evidence.retrieval.evidence_graph import (
            enrich_evidence_packet_with_spatial_graph,
        )

        packet = enrich_evidence_packet_with_spatial_graph(
            EvidencePacket(request="社前村祠堂的BSM"),
            context,
            query="社前村祠堂的BSM",
            village_name="社前村",
            entity_scope=["facilities"],
        )
        assert packet.ambiguity_status == "resolved"
        assert len(packet.candidate_refs) == 1
        candidate = packet.candidate_refs[0]
        assert candidate.identity.canonical_name == "祠堂"
        assert candidate.identity.source_feature_id == "feature:real-source-semantic:shrine"
        assert "l1:real-source-semantic:shrine" in candidate.l1_fact_refs
    finally:
        await close_cached_clients()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_real_minimax_accepts_one_real_jintian_road_binding():
    """Use one real JinTian line, without spending quota on all 131 roads."""
    import sys
    from pathlib import Path

    scripts_root = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))

    from benchmark_real_evidence import _load_bundle
    from app.infrastructure.kg.builder import KGBuilder

    bundle, counts = _load_bundle()
    assert counts["current_road"] == 131
    road = list(bundle.lines.get("roads_current") or [])[0]
    source_feature_id = str((road._raw or {}).get("source_feature_id") or "").strip()
    assert source_feature_id
    fact = L1Fact(
        fact_id="l1:real-source-semantic:jintian-road",
        statement="金田村有现状村道",
        fact_kind="document_observation",
        semantic_type="road",
        attributes={"normalized_name": "村道", "role": "road", "location": "金田村"},
        value=1,
        unit="条",
        source_refs=["report:real-source-semantic:jintian-road"],
        source_snapshot_ref="snapshot:real-source-semantic:jintian-road",
    )
    context = SimpleNamespace(
        session_id="real-source-semantic-jintian-road",
        version=1,
        kg_version=1,
        kg=KGBuilder.build("金田村", bundle),
        village_name="金田村",
        workspace=bundle,
        current_parcels=lambda: [],
        location_facts=[],
        l1_fact_records=[fact],
        l1_snapshot_ref="snapshot:real-source-semantic:jintian-road",
        data_snapshot=None,
        content_hash=bundle.spatial_snapshot_digest(),
        source_semantic_decisions={},
        source_semantic_fingerprint="",
        source_semantic_diagnostics=[],
        evidence_graph_key="graph:real-source-semantic:jintian-road",
    )

    try:
        snapshot, accepted, diagnostics = await classify_source_semantics(
            context,
            enabled=True,
            source_features={"road": [road]},
        )

        assert snapshot is not None
        assert diagnostics == []
        assert set(accepted) == {source_feature_id}
        decision = snapshot.decisions[0]
        assert decision.status == "accepted"
        assert decision.semantic_type == "村道"
        assert decision.candidate_ref == "l1:l1:real-source-semantic:jintian-road:entity"
        assert decision.supporting_fact_refs == [fact.fact_id]
        assert len(decision.proposal_digests) == 2
        assert context.evidence_graph is not None
    finally:
        await close_cached_clients()


@pytest.mark.asyncio
@pytest.mark.timeout(180)
async def test_real_minimax_accepts_one_real_jintian_axis_binding():
    """Prove that axis semantics remain axis while using a real road line."""
    import sys
    from pathlib import Path

    scripts_root = Path(__file__).resolve().parents[2] / "scripts"
    if str(scripts_root) not in sys.path:
        sys.path.insert(0, str(scripts_root))

    from benchmark_real_evidence import _load_bundle
    from app.infrastructure.kg.builder import KGBuilder

    bundle, counts = _load_bundle()
    assert counts["current_road"] == 131
    road = list(bundle.lines.get("roads_current") or [])[0]
    source_feature_id = str((road._raw or {}).get("source_feature_id") or "").strip()
    assert source_feature_id
    fact = L1Fact(
        fact_id="l1:real-source-semantic:jintian-axis",
        statement="金田村有现状发展轴线",
        fact_kind="document_observation",
        semantic_type="axis",
        attributes={
            "normalized_name": "发展轴线",
            "role": "axis",
            "location": "金田村",
        },
        value=1,
        unit="条",
        source_refs=["report:real-source-semantic:jintian-axis"],
        source_snapshot_ref="snapshot:real-source-semantic:jintian-axis",
    )
    context = SimpleNamespace(
        session_id="real-source-semantic-jintian-axis",
        version=1,
        kg_version=1,
        kg=KGBuilder.build("金田村", bundle),
        village_name="金田村",
        workspace=bundle,
        current_parcels=lambda: [],
        location_facts=[],
        l1_fact_records=[fact],
        l1_snapshot_ref="snapshot:real-source-semantic:jintian-axis",
        data_snapshot=None,
        content_hash=bundle.spatial_snapshot_digest(),
        source_semantic_decisions={},
        source_semantic_fingerprint="",
        source_semantic_diagnostics=[],
        evidence_graph_key="graph:real-source-semantic:jintian-axis",
    )

    try:
        snapshot, accepted, diagnostics = await classify_source_semantics(
            context,
            enabled=True,
            source_features={"road": [road]},
        )

        assert snapshot is not None
        assert diagnostics == []
        assert set(accepted) == {source_feature_id}
        decision = snapshot.decisions[0]
        assert decision.status == "accepted"
        assert decision.semantic_type == "发展轴线"
        assert decision.candidate_ref == "l1:l1:real-source-semantic:jintian-axis:entity"
        assert decision.supporting_fact_refs == [fact.fact_id]
        assert len(decision.proposal_digests) == 2
        assert context.evidence_graph is not None
    finally:
        await close_cached_clients()
