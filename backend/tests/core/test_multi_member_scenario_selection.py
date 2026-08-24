from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite
from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
from app.domain.allocation.scenario_optimizer import optimize_scenarios
from app.domain.ground.candidate_domain_builder import build_candidate_domains
from app.domain.relations.service import RelationEvaluationContext


def _source_member(target_id: str, candidate_id: str, x: int) -> CandidateSite:
    geometry = CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="line",
        role="execution_geometry",
        candidate_membership="required_member",
        wkt=f"LINESTRING ({x} 0, {x + 1} 1)",
        source_ref=f"kg:source:{candidate_id}",
        source_feature_ids=[candidate_id],
        generation_operation="grounded_source_feature",
        hard_constraint_status="passed",
    )
    return CandidateSite(
        site_id=f"site:{candidate_id}",
        target_ref=target_id,
        expected_output_kind="line",
        available_geometry_wkt=geometry.wkt,
        geometry=geometry,
    )


def test_current_network_source_members_are_required_as_a_set() -> None:
    candidates = [
        _source_member("road-network", "road-1", 0),
        _source_member("road-network", "road-2", 2),
        _source_member("road-network", "road-3", 4),
    ]
    domains = build_candidate_domains(candidates)

    assert domains[0].selection_mode == "all_members"
    assert domains[0].min_selected == 3
    assert domains[0].max_selected == 3

    problem = GroundedPlanningProblem(
        candidate_domains=domains,
        candidate_geometries=[item.geometry for item in candidates if item.geometry],
    )
    scenario_set = optimize_scenarios(
        problem,
        set_id="scenario:all-roads",
        evaluator_context=RelationEvaluationContext(scenario_id="scenario:all-roads"),
        max_scenarios=1,
    )
    scenario = scenario_set.recommended
    assert scenario is not None, scenario_set.model_dump(mode="json")

    assert scenario.status == "complete"
    selection = scenario.target_selections[0]
    assert selection.selection_mode == "all_members"
    assert selection.candidate_ids == [
        item.geometry.candidate_id for item in candidates if item.geometry
    ]
    assert len([item for item in scenario.feature_intents if item.target_id == "road-network"]) == 3


def test_same_name_source_features_remain_choose_one_alternatives() -> None:
    candidates = [
        _source_member("facility-target", "hall-1", 0),
        _source_member("facility-target", "hall-2", 2),
    ]
    for candidate in candidates:
        candidate.geometry.candidate_membership = "alternative"

    domains = build_candidate_domains(candidates)

    assert domains[0].selection_mode == "choose_one"
    assert domains[0].min_selected == 1
    assert domains[0].max_selected == 1
