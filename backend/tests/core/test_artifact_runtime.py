import pytest

from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.infrastructure.artifacts import ContentAddressedArtifactRepository
from app.infrastructure.artifacts.runtime import (
    ArtifactReplayError,
    load_artifact,
    store_artifact,
)


def test_store_artifact_adopts_identical_named_ref_after_interrupted_stage(tmp_path):
    state = {
        "run_id": "run-1",
        "session_id": "run-1",
        "branch_id": "branch-1",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-1", "version": "1"},
        "artifact_refs": {},
    }

    first = store_artifact(
        state,
        "execution_diagnostics",
        "execute",
        "ExecutionDiagnostics",
        {"status": "partial"},
        base_dir=tmp_path,
    )
    retry = store_artifact(
        state,
        "execution_diagnostics",
        "execute",
        "ExecutionDiagnostics",
        {"status": "partial"},
        base_dir=tmp_path,
    )

    assert retry["descriptor_digest"] == first["descriptor_digest"]


def test_store_artifact_rejects_null_payload(tmp_path):
    state = {
        "run_id": "run-null",
        "session_id": "run-null",
        "branch_id": "main",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-null", "version": "1"},
        "artifact_refs": {},
    }

    with pytest.raises(ArtifactReplayError, match="null payload"):
        store_artifact(
            state,
            "delivery_spatial_snapshot",
            "deliver",
            "DeliverySpatialSnapshot",
            None,
            base_dir=tmp_path,
        )


def test_load_artifact_rejects_a_persisted_null_payload(tmp_path):
    repository = ContentAddressedArtifactRepository(tmp_path)
    descriptor = repository.put_json(
        None,
        schema_id="DeliverySpatialSnapshot",
        schema_version="3",
        producer_stage="deliver",
        run_id="run-null-load",
        branch_id="main",
    )
    state = {
        "run_id": "run-null-load",
        "session_id": "run-null-load",
        "branch_id": "main",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-null-load", "version": "1"},
        "artifact_refs": {"delivery_spatial_snapshot": descriptor.model_dump(mode="json")},
    }

    with pytest.raises(ArtifactReplayError, match="null payload"):
        load_artifact(state, "delivery_spatial_snapshot", base_dir=tmp_path)


def test_load_artifact_roundtrip_preserves_legacy_confidence_compatibility(tmp_path):
    state = {
        "run_id": "run-grounding-legacy",
        "session_id": "run-grounding-legacy",
        "branch_id": "main",
        "artifact_schema_version": "3",
        "context_ref": {"session_id": "run-grounding-legacy", "version": "1"},
        "artifact_refs": {},
    }
    legacy_problem = {
        "schema_version": "2.0",
        "target_domains": [{
            "target_id": "legacy-site",
            "target_kind": "site_area",
            "expected_output_kind": "polygon",
            "candidate_site_refs": ["legacy-candidate"],
            "geometry_roles": ["execution_geometry"],
            "status": "candidate_only",
        }],
        "candidate_domains": [{
            "target_id": "legacy-site",
            "candidate_ids": ["legacy-candidate"],
            "candidate_geometry_refs": ["legacy-candidate"],
            "status": "candidate_only",
        }],
        "candidate_geometries": [{
            "candidate_id": "legacy-candidate",
            "target_id": "legacy-site",
            "kind": "polygon",
            "role": "execution_geometry",
            "materialization_role": "site_footprint",
            "wkt": "POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
            "spatial_domain_kind": "parcel_extent",
            "availability_status": "fully_available",
            "source_area_ha": 1.0,
            "planning_area_ha": 0.5,
            "eligible_area_ha": 1.0,
            "excluded_area_ha": 0.0,
            "source_bsms": ["P-LEGACY"],
            "source_ref": "ground:legacy",
            "evidence_refs": ["ground:legacy"],
            "hard_constraint_status": "passed",
            "confidence": 1.8,
        }],
    }

    first = store_artifact(
        state,
        "scoped_grounding_problem",
        "ground",
        "GroundedPlanningProblem",
        legacy_problem,
        base_dir=tmp_path,
    )
    state["artifact_refs"]["scoped_grounding_problem"] = first

    loaded = load_artifact(
        state,
        "scoped_grounding_problem",
        GroundedPlanningProblem,
        base_dir=tmp_path,
    )
    candidate = loaded.candidate_geometries[0]

    assert candidate.geometry_confidence == 0.0
    assert candidate.identity_confidence == 0.0
    assert candidate.suitability_score == 1.8
    assert any(
        item.startswith("legacy_confidence_overloaded:")
        for item in candidate.compatibility_diagnostics
    )
    assert loaded.candidate_completeness.status == "human_required"

    second = store_artifact(
        state,
        "scoped_grounding_problem",
        "ground",
        "GroundedPlanningProblem",
        loaded,
        base_dir=tmp_path,
    )
    state["artifact_refs"]["scoped_grounding_problem"] = second
    reloaded = load_artifact(
        state,
        "scoped_grounding_problem",
        GroundedPlanningProblem,
        base_dir=tmp_path,
    )

    assert reloaded.candidate_geometries[0].suitability_score == 1.8
    assert reloaded.candidate_geometries[0].geometry_confidence == 0.0
