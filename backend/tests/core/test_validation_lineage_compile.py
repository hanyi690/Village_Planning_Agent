"""P2: finding producer lineage lets the five checks compile to directives."""

from __future__ import annotations

import hashlib

from app.contracts.artifacts.ref import ArtifactRef
from app.contracts.artifacts.validation_report_contracts import ValidationReport
from app.contracts.spatial.planned_state_contracts import (
    PlannedParcel,
    PlannedState,
    PlannedZone,
)
from app.contracts.workflow.repair_directive_contracts import (
    RepairDirectiveType,
    RepairEvidenceScope,
)
from app.domain.validation.repair_directives import (
    compile_validation_report_directives,
)
from app.domain.validation.validate_checks import (
    check_area_conservation,
    check_classification_missing,
    check_continuity,
    check_topology,
)


def _sha(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _ref() -> ArtifactRef:
    return ArtifactRef(
        digest=_sha("blob:validation_report"),
        descriptor_digest=_sha("descriptor:validation_report"),
        size_bytes=10,
        schema_id="validation_report",
        schema_version="1.0",
        semantic_digest=_sha("semantic:validation_report"),
        producer_stage="VALIDATE",
        run_id="run-1",
        branch_id="main",
    )


def _parcel(bsm: str, *, operation: str = "reclassify", land_use: str = "建设用地") -> PlannedParcel:
    return PlannedParcel(
        bsm=bsm,
        derived_from_zone_target=f"zone-{bsm}",
        operation=operation,
        planning_land_use=land_use,
        geometry="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
    )


def _zone(name: str, *, geometry: str, parcel_bsms: list[str]) -> PlannedZone:
    return PlannedZone(
        zone_id=f"z-{name}",
        name=name,
        geometry=geometry,
        derived_from_zone_target=f"zone-{name}",
        parcel_bsms=parcel_bsms,
    )


def _compile(checks) -> Any:
    return compile_validation_report_directives(
        ValidationReport(checks=checks),
        source_artifact_key="validation_report",
        source_artifact_ref=_ref(),
    )


def test_area_conservation_lineage_compiles_to_rebuild_geometry() -> None:
    from app.contracts.spatial.parcel_change_contracts import ParcelChange, ParcelChangeSet

    changeset = ParcelChangeSet(
        changes=[
            ParcelChange(
                bsm="P1",
                action="split",
                project_ref="zone-P1",
                intervention_id="zone-P1",
                before_geometry_wkt="POLYGON ((0 0, 0 100, 100 100, 100 0, 0 0))",
                after_geometry_wkt="POLYGON ((0 0, 0 1, 1 1, 1 0, 0 0))",
            )
        ]
    )

    checks = check_area_conservation(changeset)

    assert checks[0].passed is False
    assert checks[0].affected_target_ids == ["zone-P1"]
    assert checks[0].affected_parcels == ["P1"]
    assert "parcel-change:P1:area" in checks[0].evidence_refs

    compiled = _compile(checks)
    assert compiled.status == "ready"
    assert compiled.directives[0].directive_type == RepairDirectiveType.REBUILD_GEOMETRY


def test_topology_lineage_compiles_to_rebuild_geometry() -> None:
    state = PlannedState(
        parcels=[
            _parcel("P1", operation="reclassify"),
            PlannedParcel(
                bsm="P2",
                derived_from_zone_target="zone-P2",
                operation="reclassify",
                planning_land_use="建设用地",
                geometry="POLYGON ((0 0, 0 2, 2 0, 2 2, 0 0))",
            ),
        ]
    )

    checks = check_topology(state)

    validity = next(item for item in checks if item.check_id == "topology_validity")
    assert validity.passed is False
    assert set(validity.affected_parcels) == {"P2"}
    assert set(validity.affected_target_ids) == {"zone-P2"}
    assert validity.evidence_refs

    compiled = _compile(checks)
    assert compiled.status == "ready"
    assert compiled.directives[0].directive_type == RepairDirectiveType.REBUILD_GEOMETRY


def test_continuity_lineage_compiles_to_reallocate() -> None:
    fragmented = _zone(
        "Z1",
        geometry=(
            "MULTIPOLYGON (((0 0, 0 1, 1 1, 1 0, 0 0)), "
            "((2 2, 2 3, 3 3, 3 2, 2 2)))"
        ),
        parcel_bsms=["P1", "P2"],
    )
    state = PlannedState(zones=[fragmented], parcels=[])

    checks = check_continuity(state)

    assert checks[0].passed is False
    assert set(checks[0].affected_target_ids) == {"zone-Z1"}
    assert set(checks[0].affected_parcels) == {"P1", "P2"}

    compiled = _compile(checks)
    assert compiled.status == "ready"
    assert compiled.directives[0].directive_type == RepairDirectiveType.REALLOCATE


def test_classification_missing_lineage_compiles_to_require_source_evidence() -> None:
    state = PlannedState(
        parcels=[
            _parcel("P1", operation="reclassify", land_use=""),
        ]
    )

    checks = check_classification_missing(state)

    assert checks[0].passed is False
    assert checks[0].affected_parcels == ["P1"]
    assert checks[0].affected_target_ids == ["zone-P1"]
    assert "planned-parcel:P1" in checks[0].evidence_refs

    compiled = _compile(checks)
    assert compiled.status == "ready"
    assert compiled.directives[0].directive_type == RepairDirectiveType.REQUIRE_SOURCE_EVIDENCE
    assert compiled.directives[0].evidence_scope == RepairEvidenceScope.TARGET_CONTRACT
