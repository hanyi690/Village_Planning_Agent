from __future__ import annotations

from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.spatial.parcel_change_contracts import ParcelChange
from app.contracts.workflow.execution_plan_contracts import WorkerResult
from app.domain.materialization.merge import _detect_bsm_conflicts


def _classification(code: str) -> ClassificationRef:
    return ClassificationRef(
        system="gbt21010",
        code=code,
        canonical_name="农村道路",
        source="derived",
        evidence_refs=["test:evidence"],
    )


def _change(bsm: str, wkt: str, target_id: str) -> ParcelChange:
    return ParcelChange(
        bsm=bsm,
        action="split",
        derived_from_bsms=["SOURCE-1"],
        after_classification=_classification("1006"),
        after_geometry_wkt=wkt,
        new_area_ha=1,
        intervention_id=target_id,
    )


def test_merge_blocks_overlapping_derived_writes_from_project_and_road_workers():
    conflicts = _detect_bsm_conflicts([
        WorkerResult(
            worker_type="site_area",
            parcel_changes=[_change("project-1:footprint", "POLYGON ((0 0, 4 0, 4 4, 0 4, 0 0))", "project-1")],
        ),
        WorkerResult(
            worker_type="road",
            parcel_changes=[_change("SOURCE-1:road:road-1", "POLYGON ((2 2, 6 2, 6 6, 2 6, 2 2))", "road-1")],
        ),
    ])

    assert len(conflicts) == 1
    assert conflicts[0]["code"] == "authoritative_source_geometry_overlap"
    assert conflicts[0]["source_bsms"] == ["SOURCE-1"]


def test_merge_allows_disjoint_project_and_road_subgeometries_from_one_parcel():
    conflicts = _detect_bsm_conflicts([
        WorkerResult(
            worker_type="site_area",
            parcel_changes=[_change("project-1:footprint", "POLYGON ((0 0, 2 0, 2 2, 0 2, 0 0))", "project-1")],
        ),
        WorkerResult(
            worker_type="road",
            parcel_changes=[_change("SOURCE-1:road:road-1", "POLYGON ((3 3, 5 3, 5 5, 3 5, 3 3))", "road-1")],
        ),
    ])

    assert conflicts == []
