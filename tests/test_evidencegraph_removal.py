from importlib.util import find_spec
from pathlib import Path

from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.feature_identity_contracts import (
    FeatureEvidenceRef,
    SourceFeatureIdentity,
)
from app.infrastructure.llm.tools.access import ACCESS_TOOLS


def test_legacy_evidence_graph_boundary_is_absent():
    assert find_spec("app.infrastructure.evidence_runtime.evidence_graph") is None
    assert not Path(
        "backend/app/infrastructure/ground_runtime/compatibility.py"
    ).exists()


def test_evidence_access_exposes_only_data_geometry_lookup():
    tool_names = {tool.name for tool in ACCESS_TOOLS}

    assert "data_geometry_by_ref" in tool_names
    assert "query_evidence_graph" not in tool_names
    assert "query_facility_bsms" not in tool_names


def test_evidence_contracts_have_only_data_feature_identity():
    assert set(SourceFeatureIdentity.model_fields).isdisjoint({
        "bundle_feature_bsm",
        "bundle_snapshot_digest",
        "source_bsm",
        "bsm_kind",
    })
    assert set(FeatureEvidenceRef.model_fields).isdisjoint({
        "related_parcel_bsms",
    })
    assert "bundle_snapshot_digest" not in EvidencePacket.model_fields
