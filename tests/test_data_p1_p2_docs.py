from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_data_docs_describe_the_canonical_p1_p2_boundary():
    design = (ROOT / "docs/design/DATA_EXECUTABLE_DESIGN.md").read_text(encoding="utf-8")
    acceptance = (ROOT / "docs/design/acceptance/01_data_acceptance.md").read_text(encoding="utf-8")
    readme = (ROOT / "backend/app/data/README.md").read_text(encoding="utf-8")

    for name in (
        "SourceSnapshotArtifact",
        "NormalizedResourceArtifact",
        "RepresentationSnapshotArtifact",
        "CapabilityIndexArtifact",
        "check_local_admission_boundary",
        "DataAdmissionGap",
        "resume()",
        "data/cache/map_observations",
        "structured_runtime",
        "temporal_role_classifier",
        "unclassified → quarantine",
        "reasoning 只作为 provider",
    ):
        assert name in design
    assert "catalog payload" not in acceptance.casefold()
    assert "data_catalog_payload" not in readme
    assert "generic catalog 缺失时必须 fail closed" in readme


def test_data_docs_do_not_describe_retired_data_entrypoints():
    documents = "\n".join(
        (ROOT / relative).read_text(encoding="utf-8")
        for relative in (
            "docs/design/DATA_EXECUTABLE_DESIGN.md",
            "docs/design/DATA_PRODUCTION_RUNBOOK.md",
            "backend/app/data/README.md",
            "backend/app/data/ingestion/README.md",
            "backend/app/data/ingestion/providers/README.md",
        )
    ).casefold()

    assert "旧 output cache" in documents
    assert "dataadmissionfacade" in documents
    assert "data_catalog_retriever" in documents
    assert "旧 ingest.py" in documents
    assert "provider anchor" in documents


def test_data_and_consumer_boundary_decisions_are_documented():
    data = (ROOT / "docs/design/DATA_EXECUTABLE_DESIGN.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/design/DATA_PRODUCTION_RUNBOOK.md").read_text(encoding="utf-8")
    evidence = (ROOT / "docs/design/04_EVIDENCE.md").read_text(encoding="utf-8")
    world_model = (ROOT / "docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md").read_text(encoding="utf-8")
    ground = (ROOT / "docs/design/L1_GROUND_EXECUTABLE_DESIGN.md").read_text(encoding="utf-8")
    planning_ground = (ROOT / "docs/design/PLANNING_GROUND_EXECUTABLE_DESIGN.md").read_text(encoding="utf-8")

    assert "ProviderAcquisitionPlan" in data
    assert "DataChangeSet" in data
    assert "EvidenceQueryPlan" in evidence
    assert "EvidencePolicyRegistry" in evidence
    assert "CognitionRound" in evidence
    assert "SourceLocalIdentity" in world_model
    assert "CurrentWorldQueryPort" in world_model
    assert "WorldModelCommitRequest optional" not in ground
    assert "ProposalBatch" in ground
    assert "Dependency Runtime" in planning_ground
    assert "DATA only publishes DataChangeSet" in runbook


def test_provider_validation_script_is_documented_as_non_production_harness():
    data = (ROOT / "docs/design/DATA_EXECUTABLE_DESIGN.md").read_text(encoding="utf-8")
    runbook = (ROOT / "docs/design/DATA_PRODUCTION_RUNBOOK.md").read_text(encoding="utf-8")
    evidence = (ROOT / "docs/design/04_EVIDENCE.md").read_text(encoding="utf-8")
    migration = (ROOT / "docs/design/05_MIGRATION.md").read_text(encoding="utf-8")

    for document in (data, runbook, evidence, migration):
        assert "collect_amap_jintian_validation.py" in document
        assert "acceptance harness" in document.casefold()
        assert "不能作为正式业务采集入口" in document
    assert "ProviderAttempt" in evidence
    assert "retained_candidates.jsonl" in data
    assert "requests.Session" in migration
