from types import SimpleNamespace

import pytest

from app.contracts.domain.l1_contracts import L1LocationFact
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
from app.evidence.retrieval.evidence_graph import EvidenceGraph


def _context():
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000123",
        source_feature_id="source-facility-1",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
    )
    context = SimpleNamespace(
        session_id="llm-evidence-tools",
        village_name="社前村",
        workspace=workspace,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                spatial_hint="社前村",
                confidence=0.95,
            )
        ],
        kg=None,
        kg_version=1,
        l1_snapshot_ref="artifact://l1/1",
        data_snapshot=SimpleNamespace(digest="bundle-digest"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )
    return context, point


@pytest.mark.asyncio
async def test_llm_evidence_tools_are_candidate_only(monkeypatch):
    from app.infrastructure.llm.tools.access import evidence

    context, _ = _context()
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )

    payload = await evidence.query_facility_bsms_impl(
        "llm-evidence-tools", "社前村", "祠堂"
    )
    assert payload["status"] == "resolved"
    assert payload["candidates"][0]["feature_bsm"] == "44142621100000000123"
    assert payload["candidates"][0]["canonical_name"] == "祠堂"
    assert payload["candidates"][0]["role"] == "facility"
    assert payload["candidates"][0]["geometry_ref"].startswith("bundle://feature/")
    assert "geometry" not in payload["candidates"][0]

    packet = await evidence.query_evidence_graph_impl(
        "llm-evidence-tools", "社前村祠堂的BSM", "社前村"
    )
    assert packet["candidate_refs"][0]["identity"]["bundle_feature_bsm"] == (
        "44142621100000000123"
    )
    assert packet["candidate_refs"][0]["geometry_ref"].startswith(
        "bundle://feature/"
    )
    assert "evidence_bundle" in packet
    assert "spatial_cognition" in packet
    assert any(
        source.get("source_type") == "bundle"
        for source in packet["evidence_bundle"]["sources"]
    )


@pytest.mark.asyncio
async def test_llm_tool_uses_shared_report_l1_context_preparation(monkeypatch):
    from app.infrastructure.llm.tools.access import evidence

    context = SimpleNamespace(
        reports={"L1:public_service": "报告正文"},
        l1_fact_records=["typed-l1-fact"],
    )
    captured = {}

    async def prepare(session_id, village_name, *, include_reports, refresh=False):
        captured.update({
            "session_id": session_id,
            "village_name": village_name,
            "include_reports": include_reports,
            "refresh": refresh,
        })
        return context

    monkeypatch.setattr(
        "app.application.queries.evidence.prepare_evidence_context",
        prepare,
    )

    assert await evidence._context_for_session("shared-context", "社前村") is context
    assert captured == {
        "session_id": "shared-context",
        "village_name": "社前村",
        "include_reports": True,
        "refresh": False,
    }


@pytest.mark.asyncio
async def test_geometry_tool_requires_verified_bundle_feature_ref(monkeypatch):
    from app.infrastructure.llm.tools.access import evidence

    _, point = _context()
    bundle = SimpleNamespace(
        points={"facilities_current": [point]},
        lines={},
        polygons={},
    )

    async def resolve(_session_id):
        return bundle

    monkeypatch.setattr(evidence, "resolve_bundle", resolve)

    rejected = await evidence.bundle_geometry_by_feature_ref_impl(
        "llm-evidence-tools", "bundle://feature/not-verified"
    )
    assert rejected["success"] is False

    accepted = await evidence.bundle_geometry_by_feature_ref_impl(
        "llm-evidence-tools", "bundle://feature/44142621100000000123"
    )
    assert accepted["success"] is True
    assert accepted["geometry_authority"] == "bundle"
    assert accepted["geometry"]["coordinates"] == [116.0, 24.0]


def test_simulated_llm_can_only_select_packet_candidate():
    from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
    from app.contracts.evidence.feature_identity_contracts import (
        BundleFeatureIdentity,
        FeatureEvidenceRef,
    )
    from app.infrastructure.llm.tools.candidate_only import (
        CandidateSelectionError,
        SimulatedEvidenceLLM,
    )

    packet = EvidencePacket(
        request="社前村祠堂",
        candidate_refs=[
            FeatureEvidenceRef(
                identity=BundleFeatureIdentity(
                    bundle_feature_bsm="44142621100000000123"
                ),
                entity_refs=["http://example.test/facility-1"],
            )
        ],
    )
    selected = SimulatedEvidenceLLM(
        "44142621100000000123"
    ).choose(packet)
    assert selected.identity.bundle_feature_bsm == "44142621100000000123"

    try:
        SimulatedEvidenceLLM("99999999999999999999").choose(packet)
    except CandidateSelectionError:
        pass
    else:
        raise AssertionError("unknown model-generated candidate must be rejected")
