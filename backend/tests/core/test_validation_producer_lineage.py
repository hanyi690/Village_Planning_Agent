from __future__ import annotations

import hashlib

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.artifacts.validation_report_contracts import ValidationReport
from app.contracts.domain.road_planning import (
    RoadArtifactEvidence,
    RoadEndpointEvidence,
    RoadRoutingEvidence,
)
from app.contracts.spatial.planned_state_contracts import PlannedParcel, PlannedState
from app.contracts.workflow.parse_contracts import RoadTarget
from app.contracts.workflow.repair_directive_contracts import RepairDirectiveType
from app.domain.materialization.nodes import road_worker
from app.domain.validation.repair_directives import (
    compile_validation_report_directives,
)
from app.domain.validation.repair_impact import analyze_repair_impact
from app.domain.validation.report_service import build_validation_report
from app.domain.validation.validate_checks import (
    check_hard_constraints,
    check_overlap,
)
from app.spatial.query.bridge import ConstraintOverlap


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ref(key: str, stage: str = "VALIDATE") -> ArtifactRef:
    return ArtifactRef(
        digest=_sha(f"blob:{key}"),
        descriptor_digest=_sha(f"descriptor:{key}"),
        size_bytes=10,
        schema_id=key,
        schema_version="1.0",
        semantic_digest=_sha(f"semantic:{key}"),
        producer_stage=stage,
        run_id="run-1",
        branch_id="main",
    )


class _ConstraintIndex:
    def geometry_in_constraint(self, geometry):
        return [
            ConstraintOverlap(
                bsm="",
                constraint_type="farmland_protection",
                constraint_label="永久基本农田",
                overlap_area_sqm=12.5,
                overlap_pct=25.0,
            )
        ]


def _parcel(bsm: str, target_id: str, geometry: str) -> PlannedParcel:
    return PlannedParcel(
        bsm=bsm,
        derived_from_zone_target=target_id,
        geometry=geometry,
        planning_land_use="村庄建设用地",
    )


def test_hard_constraint_finding_carries_target_bsm_and_evidence_lineage() -> None:
    state = PlannedState(
        parcels=[
            _parcel(
                "BSM-1",
                "zone-1",
                "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
            )
        ]
    )

    checks = check_hard_constraints(state, _ConstraintIndex())

    assert len(checks) == 1
    finding = checks[0]
    assert finding.passed is False
    assert finding.code == "hard_constraints"
    assert finding.violation_id == "hard_constraints:zone-1:BSM-1:farmland_protection"
    assert finding.affected_target_ids == ["zone-1"]
    assert finding.affected_parcels == ["BSM-1"]
    assert "planned-parcel:BSM-1" in finding.evidence_refs
    assert "constraint:farmland_protection" in finding.evidence_refs

    source = _ref("validation_report")
    compiled = compile_validation_report_directives(
        ValidationReport(checks=checks),
        source_artifact_key="validation_report",
        source_artifact_ref=source,
    )
    assert compiled.status == "ready"
    assert compiled.directives[0].directive_type == RepairDirectiveType.EXCLUDE_BSMS
    assert compiled.directives[0].target_id == "zone-1"
    assert compiled.directives[0].exclude_bsms == ["BSM-1"]


def test_hard_constraints_ignore_preserved_split_remainder() -> None:
    parcel = PlannedParcel(
        bsm="BSM-REMAINDER",
        derived_from_zone_target="road-1",
        geometry="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
        operation="preserve",
    )

    checks = check_hard_constraints(PlannedState(parcels=[parcel]), _ConstraintIndex())

    assert checks[0].passed is True


def test_hard_constraint_without_target_lineage_remains_blocked() -> None:
    parcel = PlannedParcel(
        bsm="BSM-ORPHAN",
        geometry="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )
    checks = check_hard_constraints(PlannedState(parcels=[parcel]), _ConstraintIndex())

    compiled = compile_validation_report_directives(
        ValidationReport(checks=checks),
        source_artifact_key="validation_report",
        source_artifact_ref=_ref("validation_report"),
    )

    assert compiled.status == "blocked"
    assert compiled.unresolved[0].reason_code == "missing_target_lineage"
    assert compiled.unresolved[0].affected_bsms == ["BSM-ORPHAN"]


def test_overlap_finding_preserves_concrete_target_pair_bsms_and_evidence() -> None:
    state = PlannedState(
        parcels=[
            _parcel(
                "BSM-A",
                "zone-a",
                "POLYGON ((0 0, 0 2, 2 2, 2 0, 0 0))",
            ),
            _parcel(
                "BSM-B",
                "zone-b",
                "POLYGON ((1 1, 1 3, 3 3, 3 1, 1 1))",
            ),
        ]
    )

    checks = check_overlap(state)

    assert len(checks) == 1
    finding = checks[0]
    assert finding.passed is False
    assert finding.code == "overlap"
    assert finding.violation_id.startswith("overlap:parcel:")
    assert finding.affected_target_ids == ["zone-a", "zone-b"]
    assert finding.affected_parcels == ["BSM-A", "BSM-B"]
    assert len(finding.evidence_refs) == 3
    assert any(ref.startswith("overlap-evidence:") for ref in finding.evidence_refs)

    source = _ref("validation_report")
    compiled = compile_validation_report_directives(
        ValidationReport(checks=checks),
        source_artifact_key="validation_report",
        source_artifact_ref=source,
    )
    assert compiled.status == "ready"
    assert {item.target_id for item in compiled.directives} == {"zone-a", "zone-b"}
    assert {item.directive_type for item in compiled.directives} == {
        RepairDirectiveType.REALLOCATE
    }


def test_validation_report_producer_does_not_emit_legacy_relax_adjustments() -> None:
    checks = check_hard_constraints(
        PlannedState(
            parcels=[
                _parcel(
                    "BSM-1",
                    "zone-1",
                    "POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
                )
            ]
        ),
        _ConstraintIndex(),
    )

    report = build_validation_report("session-1", checks, "SELECT")

    assert report.adjustments == []
    assert report.issues_by_stage["SELECT"][0].code == "hard_constraints"
    assert report.issues_by_stage["SELECT"][0].check_id == checks[0].violation_id


def _routing_evidence() -> RoadRoutingEvidence:
    return RoadRoutingEvidence(
        dem=RoadArtifactEvidence(
            role="dem",
            artifact_ref="artifact:dem",
            checksum=_sha("dem"),
        )
    )


def _endpoint(role: str, coordinate: tuple[float, float]) -> RoadEndpointEvidence:
    return RoadEndpointEvidence(
        role=role,
        resolution_status="resolved",
        entity_ref=f"entity:{role}",
        coordinate=coordinate,
        coordinate_crs="EPSG:4326",
        source_artifact_ref="artifact:gazetteer",
        evidence_refs=[f"evidence:{role}"],
    )


def test_road_unresolved_findings_are_target_bound_and_reason_typed() -> None:
    source_missing = RoadTarget(
        target_id="road-source",
        action="upgrade",
        road_planning_kind="existing_road_intervention",
    )
    anchor_missing = RoadTarget(
        target_id="road-anchor",
        action="new",
        road_planning_kind="new_corridor",
        routing_evidence=_routing_evidence(),
    )
    route_failed = RoadTarget(
        target_id="road-route",
        action="new",
        road_planning_kind="new_corridor",
        start_endpoint=_endpoint("start", (113.0, 23.0)),
        end_endpoint=_endpoint("end", (113.1, 23.1)),
        routing_evidence=_routing_evidence(),
    )

    findings = road_worker._normalize_road_unresolved_findings(
        [source_missing, anchor_missing, route_failed],
        produced_target_ids=set(),
        unresolved_items=[{"message": "road planner returned no geometry"}],
        error="route solver failed",
    )

    assert {item["target_id"] for item in findings} == {
        "road-source",
        "road-anchor",
        "road-route",
    }
    by_target = {item["target_id"]: item for item in findings}
    assert by_target["road-source"]["reason_code"] == "source_contract_missing"
    assert by_target["road-source"]["code"] == "road_unresolved"
    assert by_target["road-anchor"]["reason_code"] == "anchor_missing"
    assert by_target["road-anchor"]["code"] == "road_anchor_unresolved"
    assert by_target["road-route"]["reason_code"] == "route_failed"
    assert by_target["road-route"]["code"] == "road_route_failed"
    assert by_target["road-route"]["evidence_refs"]


def test_road_reason_types_compile_to_distinct_resume_boundaries() -> None:
    roads = [
        RoadTarget(
            target_id="road-source",
            action="upgrade",
            road_planning_kind="existing_road_intervention",
        ),
        RoadTarget(
            target_id="road-anchor",
            action="new",
            road_planning_kind="new_corridor",
            routing_evidence=_routing_evidence(),
        ),
        RoadTarget(
            target_id="road-route",
            action="new",
            road_planning_kind="new_corridor",
            start_endpoint=_endpoint("start", (113.0, 23.0)),
            end_endpoint=_endpoint("end", (113.1, 23.1)),
            routing_evidence=_routing_evidence(),
        ),
    ]
    source = _ref("validation_report")
    expected = {
        "road-source": "L3",
        "road-anchor": "GROUND",
        "road-route": "EXECUTE",
    }

    for finding in road_worker._normalize_road_unresolved_findings(
        roads,
        produced_target_ids=set(),
        unresolved_items=[],
        error="route solver failed",
    ):
        compiled = compile_validation_report_directives(
            ValidationReport.model_validate(
                {
                    "checks": [
                        {
                            "check_id": finding["code"],
                            "code": finding["code"],
                            "violation_id": finding["violation_id"],
                            "passed": False,
                            "affected_target_ids": [finding["target_id"]],
                            "evidence_refs": finding["evidence_refs"],
                        }
                    ]
                }
            ),
            source_artifact_key="validation_report",
            source_artifact_ref=source,
        )
        assert compiled.status == "ready"
        directive = compiled.directives[0]
        if finding["target_id"] == "road-route":
            assert directive.directive_type == RepairDirectiveType.REBUILD_GEOMETRY
        stage = analyze_repair_impact(
            compiled,
            _minimal_artifacts_for(expected[finding["target_id"]], source),
        ).earliest_invalid_stage
        assert stage == expected[finding["target_id"]]


def _minimal_artifacts_for(stage: str, source: ArtifactRef) -> dict[str, ArtifactRef]:
    l1_snapshot = _ref("l1_snapshot", "L1")
    l2_strategy = ArtifactRef(
        **{
            **_ref("l2_strategy", "L2").model_dump(),
            "parent_digests": {"l1_snapshot": l1_snapshot.digest},
        }
    )
    planning_program = ArtifactRef(
        **{
            **_ref("planning_program", "L3").model_dump(),
            "parent_digests": {"l2_strategy": l2_strategy.digest},
        }
    )
    target_projection = ArtifactRef(
        **{
            **_ref("target_projection", "TARGET_PROJECTION").model_dump(),
            "parent_digests": {"planning_program": planning_program.digest},
        }
    )
    grounding_result = ArtifactRef(
        **{
            **_ref("grounding_result", "GROUND").model_dump(),
            "parent_digests": {"target_projection": target_projection.digest},
        }
    )
    site_selection = ArtifactRef(
        **{
            **_ref("site_selection", "SELECT").model_dump(),
            "parent_digests": {"grounding_result": grounding_result.digest},
        }
    )
    refs = {
        "l1_snapshot": l1_snapshot,
        "l2_strategy": l2_strategy,
        "planning_program": planning_program,
        "target_projection": target_projection,
        "grounding_result": grounding_result,
        "site_selection": site_selection,
        "validation_report": source,
    }
    return refs
