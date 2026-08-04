from app.modules.schema.contracts.spatial_reference_contracts import SpatialReferenceSpec, RefObject, GeometryRef
from app.modules.schema.contracts.constraint_contracts import (
    PlanningConstraint, ConstraintSet, ConstraintStrength, ConstraintScope, ConstraintSource,
)
from app.modules.schema.contracts.parse_result_contracts import (
    IntentCompilationResult, ProjectRequirement, CompilationError,
)
from app.modules.schema.contracts.grounding_contracts import (
    GroundingResult, CandidateSite, HardConstraintResult, SpatialQueryEvidence,
)
from app.modules.schema.contracts.selection_contracts import (
    SiteSelectionDecision, RankedCandidate, EliminatedCandidate, LandDesignBrief,
)


def test_spatial_reference_spec_recursive_children():
    spec = SpatialReferenceSpec(type="directional", reference=RefObject(kind="village"), direction="north")
    assert spec.children == []


def test_ref_object_and_geometry_ref():
    ro = RefObject(kind="village", filter={})
    gr = GeometryRef(wkt="POINT(0 0)", crs="EPSG:4547")
    assert ro.kind == "village"
    assert gr.crs == "EPSG:4547"


def test_legacy_candidate_types_still_available():
    from app.modules.schema.contracts.spatial_reference_contracts import CandidateSet, ResolvedSpatialRef
    cs = CandidateSet(bsms=["B1"], ref_bsms=[], ref_geometry_wkt="")
    rs = ResolvedSpatialRef(final_bsms=["B1"], bbox=None, reference_geometry_wkt="", confidence=1.0, provenance={})
    assert cs.bsms == ["B1"]
    assert rs.final_bsms == ["B1"]


def test_planning_constraint():
    c = PlanningConstraint(
        constraint_id="c1", scope=ConstraintScope.PARCEL, strength=ConstraintStrength.HARD,
        source=ConstraintSource.LEGAL, field="area_ha", operator=">=", value=0.5,
    )
    assert c.strength == ConstraintStrength.HARD


def test_constraint_set():
    cs = ConstraintSet(constraints=[], conflicts=[])
    assert cs.constraints == []


def test_intent_compilation_result():
    icr = IntentCompilationResult(context_version="v1", artifact_id="parse-1", intent=None, project_requirements=[], compilation_errors=[])
    assert icr.schema_version == "1.0"


def test_project_requirement():
    pr = ProjectRequirement(project_ref="iv-1", functions=["医疗"])
    assert pr.project_ref == "iv-1"
    assert pr.constraints == []


def test_grounding_result_has_candidates():
    cs = CandidateSite(site_id="cs-1", source_parcels=["BSM001"], available_geometry_wkt="POLYGON((0 0,0 1,1 1,1 0,0 0))", available_area_ha=5.0)
    gr = GroundingResult(context_version="v1", artifact_id="ground-1", candidates=[cs], unresolved=[])
    assert gr.candidates[0].site_id == "cs-1"


def test_hard_constraint_result():
    hr = HardConstraintResult(constraint_id="c1", passed=False, violation_detail="面积不足")
    assert hr.passed is False


def test_site_selection_decision():
    rc = RankedCandidate(candidate_id="cs-1", rank=1, score=0.95, score_breakdown={})
    ec = EliminatedCandidate(candidate_id="cs-2", elimination_reason="硬约束违反", eliminated_by_constraint="c1")
    ssd = SiteSelectionDecision(context_version="v1", artifact_id="select-1", selected_combination=["cs-1"], full_ranking=[rc], eliminated=[ec], decision_factors={}, review_status="approved")
    assert ssd.selected_combination == ["cs-1"]
    assert ssd.review_status == "approved"


def test_land_design_brief():
    ldb = LandDesignBrief(project_ref="iv-1", area_tolerance_pct=5.0)
    assert ldb.area_tolerance_pct == 5.0
    assert ldb.footprint_conditions == []
