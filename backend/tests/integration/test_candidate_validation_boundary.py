from __future__ import annotations

from types import SimpleNamespace

from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
from app.domain.materialization.planned_state_builder import changeset_to_planned_state
from app.domain.validation.validate import validate_aggregate
from app.domain.validation.validate_checks import (
    check_candidate_materialization,
    check_contract_completeness,
    check_hard_constraints,
)


def _layout(candidate_id: str, target_id: str, feature_id: str) -> dict:
    return {
        "layerType": "planned_project",
        "data": {
            "type": "FeatureCollection",
            "features": [{
                "type": "Feature",
                "properties": {
                    "target_id": target_id,
                    "candidate_id": candidate_id,
                    "feature_id": feature_id,
                    "scenario_id": "scenario:test",
                    "materialization_role": "execution_geometry",
                    "source_refs": [f"source:{candidate_id}"],
                },
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]],
                },
            }],
        },
    }


def _intent() -> SimpleNamespace:
    return SimpleNamespace(
        site_area_targets=[
            SimpleNamespace(
                target_id="target:overlay",
                materialization_role="protection_overlay",
            ),
            SimpleNamespace(
                target_id="target:footprint",
                materialization_role="site_footprint",
            ),
        ],
        zone_targets=[],
    )


class _ConstraintIndex:
    def geometry_in_constraint(self, _geometry):
        return [
            SimpleNamespace(
                constraint_type="farmland_protection",
                overlap_area_sqm=1.0,
                overlap_pct=1.0,
            )
        ]


def test_candidate_materialization_keeps_candidate_identity_out_of_bsm() -> None:
    state = changeset_to_planned_state(
        ParcelChangeSet(),
        _intent(),
        [
            _layout("candidate:overlay", "target:overlay", "feature:overlay"),
            _layout("candidate:footprint", "target:footprint", "feature:footprint"),
        ],
    )

    assert len(state.overlays) == 1
    assert state.overlays[0].candidate_id == "candidate:overlay"
    assert state.overlays[0].target_ref == "target:overlay"
    assert len(state.parcels) == 1
    assert state.parcels[0].bsm == ""
    assert state.parcels[0].candidate_id == "candidate:footprint"
    assert state.parcels[0].target_ref == "target:footprint"


def test_candidate_branch_does_not_require_parcel_changeset_flags() -> None:
    state = changeset_to_planned_state(
        ParcelChangeSet(),
        _intent(),
        [_layout("candidate:footprint", "target:footprint", "feature:footprint")],
    )

    checks = check_contract_completeness(state, None, _intent())
    flags = next(item for item in checks if item.check_id == "changeset_flags")
    assert flags.passed
    assert check_candidate_materialization(state)[0].passed


def test_legacy_hard_constraint_check_still_applies_to_site_footprint_not_overlay() -> None:
    state = changeset_to_planned_state(
        ParcelChangeSet(),
        _intent(),
        [
            _layout("candidate:overlay", "target:overlay", "feature:overlay"),
            _layout("candidate:footprint", "target:footprint", "feature:footprint"),
        ],
    )

    findings = check_hard_constraints(state, _ConstraintIndex())
    assert len(findings) == 1
    assert not findings[0].passed
    assert findings[0].affected_parcels == []
    assert "candidate:candidate:footprint" in findings[0].evidence_refs


def test_validate_aggregate_accepts_candidate_geometry_without_changeset() -> None:
    state = changeset_to_planned_state(
        ParcelChangeSet(),
        _intent(),
        [_layout("candidate:footprint", "target:footprint", "feature:footprint")],
    )

    report = validate_aggregate(
        state,
        None,
        _intent(),
        None,
        run_id="run:test",
    )
    assert next(item for item in report.checks if item.check_id == "changeset_flags").passed
    assert next(item for item in report.checks if item.check_id == "candidate_materialization").passed
