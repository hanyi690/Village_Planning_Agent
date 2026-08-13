from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError
from shapely.geometry import Polygon, mapping

from app.contracts.artifacts.classification_ref import (
    ClassificationRef,
    classification_code_names,
)
from app.contracts.spatial.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.contracts.spatial.planned_state_contracts import (
    PlannedParcel,
    PlannedState,
    PlannedZone,
    PlannedZoneOverlay,
)
from app.contracts.workflow.execution_plan_contracts import WorkerResult
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.merge import merge_worker_results
from app.domain.materialization.nodes.merge_and_materialize import (
    _planned_state_builder_node,
)


def _classification(code: str = "1207") -> ClassificationRef:
    names = classification_code_names("gbt21010") or {}
    return ClassificationRef(
        system="gbt21010",
        code=code,
        canonical_name=names[code],
        source="derived",
        evidence_refs=[f"classification:{code}"],
    )


def _change(
    bsm: str,
    *,
    code: str = "1207",
    target_id: str = "zone-A",
    lineage_id: str = "lineage-zone-A-P1",
) -> ParcelChange:
    return ParcelChange(
        bsm=bsm,
        action="reclassify",
        derived_from_bsms=[bsm],
        after_classification=_classification(code),
        after_geometry_wkt="POLYGON ((0 0, 100 0, 100 100, 0 100, 0 0))",
        new_area_ha=1.0,
        project_ref=target_id,
        intervention_id=target_id,
    )


def _assignment_layer() -> dict:
    return {
        "layerType": "authoritative_zone_assignment",
        "layerName": "权威规划地类",
        "data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "bsm": "P1",
                        "target_id": "zone-A",
                        "zone_id": "planning-zone-A",
                        "project_ref": "zone-A",
                        "lineage_id": "lineage-zone-A-P1",
                        "claim_refs": ["claim-zone-A"],
                        "source_instruction_id": "instruction-zone-A",
                        "source_report_key": "report-zone-A",
                        "classification_system": "gbt21010",
                        "classification_code": "1207",
                        "planning_land_use": "设施农用地",
                        "geometry_ref": "bundle://parcel/P1",
                        "materialization_role": "land_use_assignment",
                        "area_ha": 1.0,
                    },
                    "geometry": mapping(
                        Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
                    ),
                }
            ],
        },
    }


def _overlay_layer() -> dict:
    return {
        "layerType": "restoration_overlay",
        "layerName": "修复叠加层",
        "data": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "properties": {
                        "target_id": "restore-1",
                        "project_ref": "restore-1",
                        "bsm": "P1",
                        "materialization_role": "restoration_overlay",
                        "provenance_refs": ["claim-restore-1"],
                    },
                    "geometry": mapping(
                        Polygon([(0, 0), (100, 0), (100, 100), (0, 100)])
                    ),
                }
            ],
        },
    }


def test_merge_blocks_duplicate_authoritative_write_even_when_codes_match():
    zone = WorkerResult(worker_type="zone", parcel_changes=[_change("P1")])
    project = WorkerResult(
        worker_type="project",
        parcel_changes=[_change("P1", target_id="project-1", lineage_id="project-1")],
    )

    changeset, _, diagnostics, _ = merge_worker_results([zone, project])

    assert changeset.changes == []
    assert diagnostics[0]["blocking"] is True
    assert diagnostics[0]["code"] == "authoritative_land_use_conflict"
    assert diagnostics[0]["bsm"] == "P1"


def test_blocking_merge_diagnostic_prevents_planned_state_creation():
    state = ExecuteAgentState(
        parcel_changeset=ParcelChangeSet(changes=[_change("P1")]),
        worker_conflict_diagnostics=[
            {
                "code": "authoritative_land_use_conflict",
                "blocking": True,
                "bsm": "P1",
            }
        ],
    )

    update = asyncio.run(_planned_state_builder_node(state))

    assert update["planned_state"] is None
    assert update["execution_errors"][0]["code"] == "planned_state_blocked_by_conflict"


def test_merge_node_erases_changeset_when_authoritative_conflict_is_blocking():
    state = ExecuteAgentState(
        worker_results=[
            WorkerResult(worker_type="zone", parcel_changes=[_change("P1")]),
            WorkerResult(
                worker_type="project",
                parcel_changes=[_change("P1", target_id="project-1")],
            ),
        ]
    )

    from app.domain.materialization.nodes.merge_and_materialize import (
        _merge_worker_results_node,
    )

    update = asyncio.run(_merge_worker_results_node(state))

    assert update["parcel_changeset"] is None
    assert update["planned_state"] is None
    assert update["execution_errors"][0]["code"] == "planned_state_blocked_by_conflict"


def test_planned_state_contains_lineage_planned_zone_and_separate_overlay():
    state = ExecuteAgentState(
        parcel_changeset=ParcelChangeSet(changes=[_change("P1")]),
        layout_configs=[_assignment_layer(), _overlay_layer()],
    )

    planned = asyncio.run(_planned_state_builder_node(state))["planned_state"]

    assert len(planned.parcels) == 1
    assert planned.parcels[0].target_ref == "zone-A"
    assert planned.parcels[0].project_ref == "zone-A"
    assert planned.parcels[0].lineage_id == "lineage-zone-A-P1"
    assert planned.parcels[0].claim_refs == ["claim-zone-A"]
    assert planned.parcels[0].geometry_ref == "bundle://parcel/P1"
    assert len(planned.zones) == 1
    assert planned.zones[0].zone_id == "planning-zone-A"
    assert planned.zones[0].project_ref == "zone-A"
    assert planned.zones[0].parcel_bsms == ["P1"]
    assert planned.zones[0].lineage_ids == ["lineage-zone-A-P1"]
    assert len(planned.overlays) == 1
    assert planned.overlays[0].materialization_role == "restoration_overlay"
    assert planned.overlays[0].project_ref == "restore-1"
    assert planned.overlays[0].derived_from_bsms == ["P1"]


def test_planned_state_contract_rejects_duplicate_parcel_and_zone_ownership():
    with pytest.raises(ValidationError, match="duplicate PlannedParcel BSM"):
        PlannedState(parcels=[PlannedParcel(bsm="P1"), PlannedParcel(bsm="P1")])

    with pytest.raises(ValidationError, match="multiple authoritative PlannedZone"):
        PlannedState(
            zones=[
                PlannedZone(zone_id="A", parcel_bsms=["P1"]),
                PlannedZone(zone_id="B", parcel_bsms=["P1"]),
            ]
        )

    with pytest.raises(ValidationError, match="multiple authoritative PlannedZone"):
        PlannedState(
            zones=[
                PlannedZone(zone_id="A", parcel_bsms=["P1"]),
                PlannedZone(zone_id="A", parcel_bsms=["P1"]),
            ]
        )


def test_overlay_may_overlap_authoritative_zone_without_contract_conflict():
    state = PlannedState(
        parcels=[PlannedParcel(bsm="P1")],
        zones=[PlannedZone(zone_id="A", parcel_bsms=["P1"])],
        overlays=[
            PlannedZoneOverlay(
                overlay_id="protect-1",
                materialization_role="protection_overlay",
                derived_from_bsms=["P1"],
            )
        ],
    )

    assert state.overlays[0].derived_from_bsms == ["P1"]
