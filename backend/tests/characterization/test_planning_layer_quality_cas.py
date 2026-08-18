"""CAS-backed read-side audit coverage for descriptor-only replay branches."""

from __future__ import annotations

import json
from pathlib import Path

from app.infrastructure.artifacts.repository import ContentAddressedArtifactRepository
from scripts.audit_planning_layer_quality import audit_planning_layer_quality


def _write_ref(
    repository: ContentAddressedArtifactRepository,
    refs_dir: Path,
    key: str,
    payload: object,
) -> None:
    descriptor = repository.put_json(
        payload,
        schema_id=key,
        schema_version="3",
        producer_stage="test",
        run_id="cas-audit-run",
        branch_id="cas-audit-branch",
    )
    refs_dir.mkdir(parents=True, exist_ok=True)
    (refs_dir / f"{key}.json").write_text(
        json.dumps({"descriptor_digest": descriptor.descriptor_digest}),
        encoding="utf-8",
    )


def test_audit_resolves_descriptor_only_delivery_refs_from_same_cas(tmp_path):
    repository = ContentAddressedArtifactRepository(tmp_path)
    refs_dir = tmp_path / "runs" / "cas-audit-run" / "branches" / "cas-audit-branch" / "refs"
    _write_ref(
        repository,
        refs_dir,
        "delivery_manifest",
        {"delivery_status": "partial", "diagnostic_summary": {}},
    )
    _write_ref(
        repository,
        refs_dir,
        "delivery_spatial_snapshot",
        {"change_summary": {"modified": 0}},
    )
    _write_ref(
        repository,
        refs_dir,
        "render_layers",
        [
            {
                "layerType": "current_landuse",
                "data": {"type": "FeatureCollection", "features": [{"type": "Feature"}]},
            },
            {
                "layerType": "facility_point",
                "data": {"type": "FeatureCollection", "features": [{"type": "Feature"}]},
            },
        ],
    )
    _write_ref(
        repository,
        refs_dir,
        "planning_program",
        {"interventions": [{"id": "target-1"}]},
    )
    _write_ref(
        repository,
        refs_dir,
        "grounding_result",
        {"candidates": [{"id": "candidate-1"}]},
    )
    _write_ref(
        repository,
        refs_dir,
        "site_selection",
        {"target_assignments": [{"status": "placed"}]},
    )

    report = audit_planning_layer_quality(refs_dir.parent)

    assert report.status == "ready"
    assert report.materialized_feature_count == 2
    assert report.non_baseline_feature_count == 1
    assert report.target_count == 1
    assert report.candidate_count == 1
    assert report.selected_count == 1
    assert any("resolved render_layers descriptor to CAS blob" in item for item in report.evidence)


def test_audit_fails_closed_when_descriptor_only_branch_lacks_manifest(tmp_path):
    repository = ContentAddressedArtifactRepository(tmp_path)
    refs_dir = tmp_path / "runs" / "cas-audit-run" / "branches" / "cas-audit-branch" / "refs"
    _write_ref(
        repository,
        refs_dir,
        "delivery_spatial_snapshot",
        {"change_summary": {"created": 1}},
    )
    _write_ref(
        repository,
        refs_dir,
        "render_layers",
        [{
            "layerType": "facility_point",
            "data": {"type": "FeatureCollection", "features": [{"type": "Feature"}]},
        }],
    )

    report = audit_planning_layer_quality(refs_dir.parent)

    assert report.status == "no_planning_output"
    assert report.non_baseline_feature_count == 1
    assert any("missing authoritative delivery refs: delivery_manifest" in item for item in report.evidence)
