from types import SimpleNamespace

import pytest

from app.contracts.evidence.evidence_contracts import (
    EvidenceBundle,
    EvidenceFact,
    ExplorationResult,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.feature_identity_contracts import (
    BundleFeatureIdentity,
    FeatureEvidenceRef,
)
from app.contracts.spatial.grounding_contracts import SpatialQueryEvidence
from app.domain.ground.aggregate import retrieve_evidence


@pytest.mark.asyncio
async def test_ground_retry_uses_unified_evidence_packet(monkeypatch):
    calls = []

    async def fake_retrieve(request, session_id, **kwargs):
        calls.append((request, session_id, kwargs))
        packet = EvidencePacket(
            request=request.query,
            sufficiency="sufficient",
            candidate_refs=[
                FeatureEvidenceRef(
                    identity=BundleFeatureIdentity(
                        bundle_feature_bsm="44142611000000000001",
                        source_feature_id="bundle:annotations_current:facility-001",
                        source_layer="annotations_current",
                    ),
                    geometry_ref="bundle://feature/44142611000000000001",
                    entity_refs=["kg:facility:001"],
                )
            ],
            relation_evidence=[],
        )
        return ExplorationResult(
            evidence_bundle=EvidenceBundle(
                request=request.query,
                facts=[
                    EvidenceFact(
                        statement="祠堂的 BSM 已由 bundle 验证",
                        spatial_refs=["bundle://feature/44142611000000000001"],
                        source_refs=["l1:fact:facility-001"],
                    )
                ],
            ),
            evidence_packet=packet,
        )

    monkeypatch.setattr(
        "app.evidence.retrieval.evidence_service.retrieve_evidence",
        fake_retrieve,
    )
    rows = await retrieve_evidence(
        SimpleNamespace(session_id="ground-retry", village_name="金田村"),
        ["祠堂的 BSM", "定位祠堂"],
    )

    unified = next(item for item in rows if item.query_type == "evidence:unified")
    assert "bundle://feature/44142611000000000001" in unified.result_refs
    assert "kg:facility:001" in unified.result_refs
    assert calls
    request, session_id, kwargs = calls[0]
    assert session_id == "ground-retry"
    assert request.stage == "GROUND"
    assert request.entity_scope == ["facilities", "parcels", "roads", "waters"]
    assert kwargs["external_port"] is None
    assert any(item.query_type == "retry:evidence_requests" for item in rows)
