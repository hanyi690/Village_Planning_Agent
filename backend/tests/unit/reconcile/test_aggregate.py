"""RECONCILE aggregate: reconcile_aggregate orchestrator + coverage matrix (Wave K Task 3)."""

from __future__ import annotations

from app.agent.reconcile.aggregate import build_coverage_matrix, reconcile_aggregate
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.schema.contracts.l3_contracts import PlanningIntervention, PlanningProgram
from app.modules.schema.contracts.parcel_change_contracts import ParcelChange, ParcelChangeSet
from app.modules.schema.contracts.parse_contracts import ProjectTarget, RoadTarget, SpatialPlanningIntent
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


def test_aggregate_full_chain():
    program = make_program([make_intervention("int-1")])
    specs = make_specs(1)
    grounding = make_grounding([make_site("site-0", ["P001"])])
    decision = make_decision(["P001"])
    changeset = make_changeset([make_change("P001")])
    planned = make_planned_state([make_parcel("P001")])
    result = reconcile_aggregate(program, specs, grounding, decision, changeset, planned, SpatialPlanningIntent())
    assert len(result.coverage_matrix.rows) == 1
    row = result.coverage_matrix.rows[0]
    assert row.status == "covered"
    assert row.intervention_id == "int-1"
    assert row.spec_index == 0
    assert row.candidate_site_id == "site-0"
    assert row.selected_bsm == "P001"
    assert row.change_bsm == "P001"
    assert row.planned_parcel_bsm == "P001"
    assert result.inconsistencies == []


def test_aggregate_missing_link():
    program = make_program([make_intervention("int-1")])
    specs = make_specs(1)
    grounding = make_grounding([])
    decision = make_decision([])
    changeset = make_changeset([])
    planned = make_planned_state([])
    result = reconcile_aggregate(program, specs, grounding, decision, changeset, planned, SpatialPlanningIntent())
    row = result.coverage_matrix.rows[0]
    assert row.status == "partial"
    assert len(result.inconsistencies) >= 1
    assert all(i.responsible_stage for i in result.inconsistencies)


def test_aggregate_provenance():
    program = make_program([make_intervention("int-1")])
    result = reconcile_aggregate(
        program,
        make_specs(1),
        make_grounding([]),
        make_decision([]),
        make_changeset([]),
        make_planned_state([]),
        SpatialPlanningIntent(),
        run_id="run-123",
    )
    assert result.provenance is not None
    assert result.provenance.source == "reconcile_aggregate"
    assert result.provenance.run_id == "run-123"


def test_aggregate_empty_inputs():
    result = reconcile_aggregate(None, None, None, None, None, None, None)
    assert result.coverage_matrix.rows == []
    assert result.inconsistencies == []


def test_aggregate_l3_l4_target_coverage():
    intent = SpatialPlanningIntent(project_targets=[ProjectTarget(project_id="proj-1", name="proj-1")])
    result = reconcile_aggregate(
        make_program([]),
        [],
        make_grounding([]),
        make_decision([]),
        make_changeset([]),
        make_planned_state([]),
        intent,
    )
    assert any(i.field == "l3_l4_project" and i.responsible_stage == "L3" for i in result.inconsistencies)


def test_aggregate_road_coverage():
    intent = SpatialPlanningIntent(road_targets=[RoadTarget()])
    result = reconcile_aggregate(
        make_program([]),
        [],
        make_grounding([]),
        make_decision([]),
        make_changeset([]),
        make_planned_state([]),
        intent,
    )
    assert any(i.field == "l3_l4_road" and i.responsible_stage == "L3" for i in result.inconsistencies)


def test_aggregate_deterministic():
    program = make_program([make_intervention("int-1")])
    specs = make_specs(1)
    grounding = make_grounding([make_site("site-0", ["P001"])])
    decision = make_decision(["P001"])
    changeset = make_changeset([make_change("P001")])
    planned = make_planned_state([make_parcel("P001")])
    intent = SpatialPlanningIntent()
    r1 = reconcile_aggregate(program, specs, grounding, decision, changeset, planned, intent)
    r2 = reconcile_aggregate(program, specs, grounding, decision, changeset, planned, intent)
    assert r1.coverage_matrix.model_dump() == r2.coverage_matrix.model_dump()
    assert [i.model_dump() for i in r1.inconsistencies] == [i.model_dump() for i in r2.inconsistencies]


def test_aggregate_partial_status():
    program = make_program([make_intervention("int-1")])
    specs = make_specs(1)
    grounding = make_grounding([make_site("site-0", ["P001"])])
    decision = make_decision([])
    changeset = make_changeset([])
    planned = make_planned_state([])
    result = reconcile_aggregate(program, specs, grounding, decision, changeset, planned, SpatialPlanningIntent())
    assert result.coverage_matrix.rows[0].status == "partial"


def test_build_coverage_matrix_direct():
    program = make_program([make_intervention("int-1")])
    specs = make_specs(1)
    grounding = make_grounding([make_site("site-0", ["P001"])])
    decision = make_decision(["P001"])
    changeset = make_changeset([make_change("P001")])
    planned = make_planned_state([make_parcel("P001")])
    matrix = build_coverage_matrix(program, specs, grounding, decision, changeset, planned)
    assert len(matrix.rows) == 1
    assert matrix.rows[0].status == "covered"
