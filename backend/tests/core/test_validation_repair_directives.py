from __future__ import annotations

import hashlib

import pytest
from pydantic import ValidationError

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.artifacts.validation_report_contracts import (
    ValidationCheck,
    ValidationReport,
)
from app.contracts.workflow.repair_directive_contracts import (
    RepairDirective,
    RepairDirectiveType,
    RepairEvidenceScope,
)
from app.domain.validation.repair_directives import (
    compile_repair_directives,
    compile_validation_report_directives,
)
from app.domain.validation.repair_impact import analyze_repair_impact


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ref(
    key: str,
    stage: str,
    *,
    parents: dict[str, ArtifactRef] | None = None,
) -> ArtifactRef:
    parent_refs = parents or {}
    return ArtifactRef(
        digest=_sha(f"blob:{key}"),
        descriptor_digest=_sha(f"descriptor:{key}"),
        size_bytes=10,
        schema_id=key,
        schema_version="1.0",
        semantic_digest=_sha(f"semantic:{key}"),
        parent_digests={name: ref.digest for name, ref in parent_refs.items()},
        producer_stage=stage,
        run_id="run-1",
        branch_id="main",
    )


def _artifact_chain() -> dict[str, ArtifactRef]:
    refs: dict[str, ArtifactRef] = {}
    refs["l1_snapshot"] = _ref("l1_snapshot", "L1")
    refs["l2_strategy"] = _ref(
        "l2_strategy", "L2", parents={"l1_snapshot": refs["l1_snapshot"]}
    )
    refs["planning_program"] = _ref(
        "planning_program", "L3", parents={"l2_strategy": refs["l2_strategy"]}
    )
    refs["target_projection"] = _ref(
        "target_projection",
        "TARGET_PROJECTION",
        parents={"planning_program": refs["planning_program"]},
    )
    refs["grounding_result"] = _ref(
        "grounding_result",
        "GROUND",
        parents={"target_projection": refs["target_projection"]},
    )
    refs["scenario_set"] = _ref(
        "scenario_set",
        "SELECT",
        parents={"grounding_result": refs["grounding_result"]},
    )
    refs["planning_scenario"] = _ref(
        "planning_scenario",
        "SELECT",
        parents={"scenario_set": refs["scenario_set"]},
    )
    refs["approved_execution_input"] = _ref(
        "approved_execution_input",
        "SELECT",
        parents={"planning_scenario": refs["planning_scenario"]},
    )
    refs["execution_plan"] = _ref(
        "execution_plan",
        "EXECUTE",
        parents={"approved_execution_input": refs["approved_execution_input"]},
    )
    refs["planned_state"] = _ref(
        "planned_state",
        "EXECUTE",
        parents={"execution_plan": refs["execution_plan"]},
    )
    refs["validation_report"] = _ref(
        "validation_report",
        "VALIDATE",
        parents={"planned_state": refs["planned_state"]},
    )
    refs["reconciliation_report"] = _ref(
        "reconciliation_report",
        "RECONCILE",
        parents={"validation_report": refs["validation_report"]},
    )
    refs["delivery_manifest"] = _ref(
        "delivery_manifest",
        "DELIVER",
        parents={"reconciliation_report": refs["reconciliation_report"]},
    )
    return refs


def test_directive_contract_rejects_relax_and_unbound_target() -> None:
    with pytest.raises(ValidationError):
        RepairDirective.model_validate(
            {
                "directive_id": "directive-1",
                "directive_type": "relax",
                "target_id": "target-1",
                "source_violation_ids": ["check-1"],
                "source_artifact_key": "validation_report",
                "source_artifact_digest": _sha("validation"),
                "issue_fingerprint": _sha("issue"),
            }
        )

    with pytest.raises(ValidationError):
        RepairDirective(
            directive_id="directive-1",
            directive_type=RepairDirectiveType.REALLOCATE,
            target_id="",
            source_violation_ids=["check-1"],
            source_artifact_key="validation_report",
            source_artifact_digest=_sha("validation"),
            issue_fingerprint=_sha("issue"),
        )


def test_hard_constraint_compiles_target_level_exclusions() -> None:
    refs = _artifact_chain()
    report = ValidationReport(
        artifact_id="validation-1",
        checks=[
            ValidationCheck(
                check_id="hard_constraints",
                passed=False,
                responsible_stage="SELECT",
                affected_parcels=["BSM-1", "BSM-2"],
                affected_target_ids=["facility-1", "facility-2"],
            )
        ],
    )

    compiled = compile_validation_report_directives(
        report,
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    assert compiled.status == "ready"
    assert [item.target_id for item in compiled.directives] == [
        "facility-1",
        "facility-2",
    ]
    assert all(
        item.directive_type == RepairDirectiveType.EXCLUDE_BSMS
        for item in compiled.directives
    )
    assert all(item.exclude_bsms == ["BSM-1", "BSM-2"] for item in compiled.directives)
    assert all(item.source_artifact_digest == refs["validation_report"].digest for item in compiled.directives)


def test_overlap_compiles_reallocation_without_relax_metadata() -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "overlap-1",
                "code": "overlap",
                "target_ids": ["zone-a", "zone-b"],
                "affected_bsms": ["BSM-9"],
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    assert compiled.status == "ready"
    assert {item.target_id for item in compiled.directives} == {"zone-a", "zone-b"}
    assert {item.directive_type for item in compiled.directives} == {
        RepairDirectiveType.REALLOCATE
    }
    payload = compiled.model_dump(mode="json")
    assert "relax" not in str(payload).lower()


def test_road_unresolved_requires_source_evidence_from_l3_contract() -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "road-violation-1",
                "code": "road_unresolved",
                "target_id": "road-1",
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    directive = compiled.directives[0]
    assert directive.directive_type == RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE
    assert directive.evidence_scope == RepairEvidenceScope.TARGET_CONTRACT
    assert directive.required_evidence == [
        "road_endpoint_or_existing_segment",
        "road_mode",
    ]

    impact = analyze_repair_impact(compiled, refs)
    assert impact.status == "ready"
    assert impact.earliest_invalid_stage == "L3"
    assert impact.rerun_stages == [
        "L3",
        "TARGET_PROJECTION",
        "GROUND",
        "SELECT",
        "EXECUTE",
        "VALIDATE",
        "RECONCILE",
        "DELIVER",
    ]


def test_grounding_unresolved_starts_at_ground() -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "ground-1",
                "code": "road_anchor_unresolved",
                "target_id": "road-2",
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    impact = analyze_repair_impact(compiled, refs)
    assert impact.status == "ready"
    assert impact.earliest_invalid_stage == "GROUND"
    assert "target_projection" in impact.reusable_artifact_keys
    assert "grounding_result" in impact.invalidated_artifact_keys


def test_geometry_rebuild_accepts_target_bound_geometry_evidence_without_bsm() -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "road-geometry-1",
                "code": "geometry_invalid",
                "target_id": "road-3",
                "evidence_refs": ["road-candidate:road-3"],
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    assert compiled.status == "ready"
    assert compiled.directives[0].directive_type == RepairDirectiveType.REBUILD_GEOMETRY
    assert compiled.directives[0].evidence_refs == ["road-candidate:road-3"]
    assert analyze_repair_impact(compiled, refs).earliest_invalid_stage == "EXECUTE"


def test_unsupported_or_unbound_violation_blocks_all_auto_repair() -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "overlap-without-lineage",
                "code": "overlap",
                "affected_bsms": ["BSM-1"],
            },
            {
                "violation_id": "unknown-1",
                "code": "unexpected_check",
                "target_id": "target-1",
            },
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    assert compiled.status == "blocked"
    assert compiled.directives == []
    assert {item.reason_code for item in compiled.unresolved} == {
        "missing_target_lineage",
        "unsupported_violation",
    }
    impact = analyze_repair_impact(compiled, refs)
    assert impact.status == "blocked"
    assert impact.rerun_stages == []


@pytest.mark.parametrize(
    ("code", "expected_type", "expected_stage"),
    [
        ("hard_constraints", RepairDirectiveType.EXCLUDE_BSMS, "SELECT"),
        ("overlap", RepairDirectiveType.REALLOCATE, "SELECT"),
        ("topology", RepairDirectiveType.REBUILD_GEOMETRY, "EXECUTE"),
        (
            "road_unresolved",
            RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE,
            "L3",
        ),
    ],
)
def test_directive_type_sets_earliest_invalidation_stage(
    code: str,
    expected_type: RepairDirectiveType,
    expected_stage: str,
) -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": f"violation-{code}",
                "code": code,
                "target_id": "target-1",
                "affected_bsms": ["BSM-1"],
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    assert compiled.directives[0].directive_type == expected_type
    assert analyze_repair_impact(compiled, refs).earliest_invalid_stage == expected_stage


def test_stale_parent_checksum_moves_execute_repair_back_to_select() -> None:
    refs = _artifact_chain()
    stale_ground = _ref("stale-ground", "GROUND")
    refs["scenario_set"] = _ref(
        "scenario_set-stale",
        "SELECT",
        parents={"grounding_result": stale_ground},
    )
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "topology-1",
                "code": "topology",
                "target_id": "zone-1",
                "affected_bsms": ["BSM-1"],
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    impact = analyze_repair_impact(compiled, refs)
    assert impact.status == "ready"
    assert impact.earliest_invalid_stage == "SELECT"
    assert any(
        issue.code == "parent_checksum_mismatch" and issue.artifact_key == "planning_scenario"
        for issue in impact.integrity_issues
    )


def test_l3_resume_reuses_l2_when_previous_program_is_absent() -> None:
    refs = _artifact_chain()
    del refs["planning_program"]
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "road-1",
                "code": "road_unresolved",
                "target_id": "road-1",
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )

    impact = analyze_repair_impact(compiled, refs)
    assert impact.status == "ready"
    assert impact.earliest_invalid_stage == "L3"
    assert impact.rerun_stages[0] == "L3"
    assert "l2_strategy" in impact.reusable_artifact_keys


def test_changed_source_violation_checksum_blocks_stale_directive() -> None:
    refs = _artifact_chain()
    compiled = compile_repair_directives(
        [
            {
                "violation_id": "overlap-1",
                "code": "overlap",
                "target_id": "zone-1",
                "affected_bsms": ["BSM-1"],
            }
        ],
        source_artifact_key="validation_report",
        source_artifact_ref=refs["validation_report"],
    )
    refs["validation_report"] = _ref(
        "validation-report-new",
        "VALIDATE",
        parents={"planned_state": refs["planned_state"]},
    )

    impact = analyze_repair_impact(compiled, refs)
    assert impact.status == "blocked"
    assert any(
        issue.code == "source_violation_checksum_changed"
        for issue in impact.integrity_issues
    )
