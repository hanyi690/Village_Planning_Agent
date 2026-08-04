"""RECONCILE checks: 6 deterministic chain-coverage check functions (Wave K Task 2)."""

from __future__ import annotations

from app.agent.reconcile.checks import (
    check_candidate_selection_coverage,
    check_change_planned_coverage,
    check_intervention_coverage,
    check_quantitative_drift,
    check_selection_change_coverage,
    check_spec_candidate_coverage,
)
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.l3_contracts import PlanningIntervention, PlanningProgram
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.planned_state_contracts import PlannedParcel, PlannedState
from app.modules.schema.contracts.selection_contracts import SiteSelectionDecision
from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec


def make_program(interventions):
    return PlanningProgram(interventions=list(interventions or []))


def make_intervention(id, category="project", area_range_ha=None):
    return PlanningIntervention(intervention_id=id, name=id, category=category, area_range_ha=area_range_ha)


def make_specs(count):
    return [SpatialReferenceSpec(type="directional", direction="N") for _ in range(count)]


def make_grounding(candidate_sites, unresolved=None):
    return GroundingResult(candidates=list(candidate_sites or []), unresolved=list(unresolved or []))


def make_site(site_id, source_parcels):
    return CandidateSite(site_id=site_id, source_parcels=list(source_parcels or []))


def make_decision(selected_combination):
    return SiteSelectionDecision(selected_combination=list(selected_combination or []))


def make_changeset(changes):
    return ParcelChangeSet(changes=list(changes or []))


def make_change(bsm, derived_from_bsms=None):
    return ParcelChange(bsm=bsm, derived_from_bsms=list(derived_from_bsms or []))


def make_planned_state(parcels):
    return PlannedState(parcels=list(parcels or []))


def make_parcel(bsm, area_ha=1.0, derived_from_bsms=None, operation="reclassify"):
    return PlannedParcel(
        bsm=bsm,
        area_ha=area_ha,
        derived_from_bsms=list(derived_from_bsms or []),
        operation=operation,
    )


def test_intervention_coverage_full():
    program = make_program([make_intervention("int-1"), make_intervention("int-2")])
    specs = make_specs(2)
    incs = check_intervention_coverage(program, specs)
    assert incs == []


def test_intervention_coverage_missing_spec():
    program = make_program([make_intervention("int-1"), make_intervention("int-2")])
    specs = make_specs(1)
    incs = check_intervention_coverage(program, specs)
    assert len(incs) == 1
    assert incs[0].responsible_stage == "L3"
    assert incs[0].field == "spec"
    assert incs[0].intervention_id == "int-2"


def test_spec_candidate_coverage_full():
    specs = make_specs(1)
    grounding = make_grounding([make_site("site-0", ["P001"])])
    incs = check_spec_candidate_coverage(specs, grounding)
    assert incs == []


def test_spec_candidate_coverage_missing():
    specs = make_specs(2)
    grounding = make_grounding([make_site("site-0", ["P001"])])
    incs = check_spec_candidate_coverage(specs, grounding)
    assert len(incs) == 1
    assert incs[0].responsible_stage == "GROUND"
    assert incs[0].field == "candidate"


def test_candidate_selection_coverage_full():
    grounding = make_grounding([make_site("site-0", ["P001"])])
    decision = make_decision(["P001"])
    incs = check_candidate_selection_coverage(grounding, decision)
    assert incs == []


def test_candidate_selection_coverage_unselected():
    grounding = make_grounding([make_site("site-0", ["P001"])])
    decision = make_decision(["P002"])
    incs = check_candidate_selection_coverage(grounding, decision)
    assert len(incs) == 1
    assert incs[0].responsible_stage == "SELECT"
    assert incs[0].field == "selection"
    assert incs[0].expected == "site-0"


def test_selection_change_coverage_full():
    decision = make_decision(["P001"])
    changeset = make_changeset([make_change("P001")])
    incs = check_selection_change_coverage(decision, changeset)
    assert incs == []


def test_selection_change_coverage_missing():
    decision = make_decision(["P001"])
    changeset = make_changeset([make_change("P002")])
    incs = check_selection_change_coverage(decision, changeset)
    assert len(incs) == 1
    assert incs[0].responsible_stage == "EXECUTE"
    assert incs[0].field == "change"
    assert incs[0].expected == "P001"


def test_change_planned_coverage_full():
    changeset = make_changeset([make_change("P001")])
    planned = make_planned_state([make_parcel("P001")])
    incs = check_change_planned_coverage(changeset, planned)
    assert incs == []


def test_change_planned_coverage_missing():
    changeset = make_changeset([make_change("P001")])
    planned = make_planned_state([make_parcel("P002")])
    incs = check_change_planned_coverage(changeset, planned)
    assert len(incs) == 1
    assert incs[0].responsible_stage == "EXECUTE"
    assert incs[0].field == "planned"
    assert incs[0].expected == "P001"


def test_quantitative_drift():
    program = make_program([make_intervention("int-1", area_range_ha=(1.0, 2.0))])
    planned = make_planned_state([make_parcel("P001", area_ha=5.0)])
    incs = check_quantitative_drift(program, planned)
    assert len(incs) == 1
    assert incs[0].responsible_stage == "L3"
    assert incs[0].field == "area"
    assert incs[0].expected == "1.0-2.0"
    assert incs[0].actual == "5.0"


def test_quantitative_drift_no_range():
    program = make_program([make_intervention("int-1"), make_intervention("int-2")])
    planned = make_planned_state([make_parcel("P001", area_ha=5.0)])
    incs = check_quantitative_drift(program, planned)
    assert incs == []


def test_quantitative_drift_in_range():
    program = make_program([make_intervention("int-1", area_range_ha=(1.0, 2.0))])
    planned = make_planned_state([make_parcel("P001", area_ha=1.5)])
    incs = check_quantitative_drift(program, planned)
    assert incs == []
