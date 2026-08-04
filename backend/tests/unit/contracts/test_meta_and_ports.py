from app.modules.schema.contracts.contract_meta import ContractMeta, StageStatus, StageIssue
from app.modules.schema.contracts.provenance import Provenance, SemanticMetadata
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.ports.artifact_store import ArtifactStorePort, ArtifactRef
from app.modules.ports.context_provider import ContextProviderPort
from app.modules.ports.semantic_query import SemanticQueryPort
from app.modules.ports.spatial_query import SpatialQueryPort
from app.modules.ports.gazetteer import GazetteerPort
from app.modules.ports.nomenclature_registry import NomenclatureRegistryPort


def test_contract_meta_is_pydantic_base():
    class Dummy(ContractMeta):
        data: str = "x"

    d = Dummy(artifact_id="d-1", context_version="v1")
    assert d.schema_version == "1.0"
    assert d.artifact_id == "d-1"
    assert d.created_at is not None


def test_stage_issue_fields():
    issue = StageIssue(stage="L1", severity="error", code="EVIDENCE_GAP", message="缺少人口数据")
    assert issue.stage == "L1"
    assert issue.severity == "error"


def test_stage_status_enum():
    assert StageStatus.AWAITING_REVIEW.value == "awaiting_review"


def test_provenance_basic():
    p = Provenance(source="L1_OBSERVE", run_id="r1", module="l1_observe")
    assert p.source == "L1_OBSERVE"
    assert p.trace == []


def test_semantic_metadata_moved():
    sm = SemanticMetadata(natural_language_description="desc")
    assert sm.natural_language_description == "desc"
    assert sm.spatial_hint == ""


def test_classification_ref_preserve_source():
    ref = ClassificationRef(system="unknown", code="", canonical_name="", source="preserve")
    assert ref.source == "preserve"


def test_classification_ref_rejects_bad_source():
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError):
        ClassificationRef(system="gbt21010", code="0101", canonical_name="水田", source="bogus")


def test_artifact_ref_has_meta():
    ref = ArtifactRef(context_version="v1", artifact_id="a1", module="l1_observe", run_id="r1", artifact_type="L1Snapshot")
    assert ref.schema_version == "1.0"
    assert ref.module == "l1_observe"


def test_ports_are_protocols():
    import typing
    is_typedprotocol = getattr(typing, "is_typedprotocol", None)
    for port in (ArtifactStorePort, ContextProviderPort, SemanticQueryPort, SpatialQueryPort, GazetteerPort, NomenclatureRegistryPort):
        is_protocol = bool(is_typedprotocol(port)) if is_typedprotocol else bool(getattr(port, "_is_protocol", False))
        assert is_protocol, f"{port} not a Protocol"
