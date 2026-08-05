"""Traceability ID tests - end-to-end linkage across planning contracts."""
from __future__ import annotations

from app.modules.parsing.compiler.spec_mapper import (
    map_intervention_to_spec,
    map_interventions_to_specs,
)
from app.modules.schema.contracts.grounding_contracts import CandidateSite
from app.modules.schema.contracts.l3_contracts import PlanningIntervention
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange
from app.modules.schema.contracts.selection_contracts import RankedCandidate
from app.modules.schema.contracts.spatial_reference_contracts import (
    SpatialReferenceSpec,
)


def _intervention(**kwargs) -> PlanningIntervention:
    defaults = {
        "intervention_id": "proj-1",
        "name": "test intervention",
        "spatial_requirements": {"dlbm_in": ["0101"]},
    }
    defaults.update(kwargs)
    return PlanningIntervention(**defaults)


def test_spatial_reference_spec_accepts_traceability_fields():
    spec = SpatialReferenceSpec(
        type="attributive", intervention_id="x", project_ref="y"
    )
    assert spec.intervention_id == "x"
    assert spec.project_ref == "y"


def test_spatial_reference_spec_traceability_fields_default_none():
    spec = SpatialReferenceSpec(type="directional", direction="N")
    assert spec.intervention_id is None
    assert spec.project_ref is None


def test_map_intervention_to_spec_propagates_intervention_id():
    spec = map_intervention_to_spec(
        _intervention(intervention_id="proj-1")
    )
    assert spec is not None
    assert spec.intervention_id == "proj-1"
    assert spec.project_ref is None


def test_map_intervention_to_spec_composed_propagates_intervention_id():
    spec = map_intervention_to_spec(
        _intervention(
            intervention_id="proj-composed",
            spatial_requirements={"location": "村北", "dlbm_in": ["0101"]},
        )
    )
    assert spec is not None
    assert spec.type == "composed"
    assert spec.intervention_id == "proj-composed"
    assert spec.project_ref is None


def test_map_interventions_to_specs_propagates_ids():
    specs, diagnostics = map_interventions_to_specs(
        [
            _intervention(intervention_id="proj-1"),
            _intervention(
                intervention_id="proj-2",
                spatial_requirements={"adjacent_to": "文化广场"},
            ),
        ]
    )
    assert len(diagnostics) == 0
    ids = [spec.intervention_id for spec in specs]
    assert ids == ["proj-1", "proj-2"]
    for spec in specs:
        assert spec.project_ref is None


def test_map_interventions_to_specs_order_matches_input():
    specs, _ = map_interventions_to_specs(
        [
            _intervention(intervention_id="proj-1"),
            _intervention(intervention_id="proj-2"),
        ]
    )
    assert [spec.intervention_id for spec in specs] == ["proj-1", "proj-2"]


def test_candidate_site_accepts_traceability_fields():
    site = CandidateSite(
        site_id="site-1",
        target_ref="proj-1",
        project_ref="proj-1",
    )
    assert site.site_id == "site-1"
    assert site.target_ref == "proj-1"
    assert site.project_ref == "proj-1"


def test_ranked_candidate_accepts_project_ref():
    rc = RankedCandidate(
        candidate_id="cand-1",
        rank=1,
        score=0.9,
        project_ref="proj-1",
    )
    assert rc.candidate_id == "cand-1"
    assert rc.rank == 1
    assert rc.score == 0.9
    assert rc.project_ref == "proj-1"


def test_parcel_change_accepts_traceability_fields():
    change = ParcelChange(
        bsm="P001",
        project_ref="proj-1",
        intervention_id="proj-1",
    )
    assert change.bsm == "P001"
    assert change.project_ref == "proj-1"
    assert change.intervention_id == "proj-1"
