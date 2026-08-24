from app.contracts.domain.l1_contracts import EvidenceGap, L1LocationFact, L1Snapshot
from app.contracts.domain.l2_contracts import L2Strategy
from app.contracts.domain.l3_contracts import PlanningProgram
from app.contracts.program import PlanningClaim
from app.contracts.spatial.grounded_problem import (
    GroundedPlanningProblem,
    GroundedTargetDomain,
)
from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
from app.contracts.planning.intent_graph import PlanRelationIntent, PlanningIntentGraph
from app.contracts.planning.relation_parameters import ConnectParameters
from app.contracts.domain.l3_contracts import PlanningIntervention
from app.contracts.domain.planning_semantics import RoadPlanningParameters
from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)
from app.evidence.retrieval.requirements import (
    compile_requirements,
    requirements_from_ground,
    requirements_from_l1,
    requirements_from_l2,
    requirements_from_l3,
    requirements_from_target_projection,
)
from app.contracts.evidence.evidence_contracts import ExplorationRequest


def test_requirement_producers_bind_requirements_to_stage_artifacts() -> None:
    l1 = L1Snapshot(
        artifact_id="l1-run-a",
        evidence_gaps=[
            EvidenceGap(
                gap_id="gap-1",
                dimension="location",
                description="需要确认学校的现状位置",
                required_fact="学校的 authoritative geometry",
            )
        ],
    )
    l2 = L2Strategy(artifact_id="l2-run-a", development_goals=["提高公共服务可达性"])
    claim = PlanningClaim(
        claim_id="claim-1",
        statement="新增卫生服务点",
        suggested_category="facility",
        suggested_output_kind="point",
        location_hints=["村北"],
    )
    program = PlanningProgram(artifact_id="l3-run-a", claims=[claim])

    for stage, requirements in (
        ("L1", requirements_from_l1(l1)),
        ("L2", requirements_from_l2(l2)),
        ("L3", requirements_from_l3(program)),
    ):
        assert requirements
        assert all(item.producer_stage == stage for item in requirements)
        assert all(item.requesting_artifact_ref for item in requirements)
        assert all(item.success_condition for item in requirements)


def test_target_and_ground_producers_emit_spatial_requirements() -> None:
    target = IntentCompilationResult(
        artifact_id="target-run-a",
        spatial_reference_specs=[
            SpatialReferenceSpec(
                spec_id="spec-1",
                target_id="facility-1",
                type="directional",
                reference=RefObject(kind="place_name", filter={"label_contains": "金田村"}),
                retrieval_scopes=["facilities"],
            )
        ],
    )
    target_requirements = requirements_from_target_projection(target)
    assert target_requirements[0].producer_stage == "TARGET_PROJECTION"
    assert target_requirements[0].kind == "spatial"
    assert target_requirements[0].scope == ("facilities", "金田村")

    problem = GroundedPlanningProblem(
        artifact_id="ground-run-a",
        target_domains=[
            GroundedTargetDomain(
                target_id="facility-1",
                status="unresolved",
            )
        ],
    )
    ground_requirements = requirements_from_ground(problem)
    assert ground_requirements
    assert ground_requirements[0].producer_stage == "GROUND"
    assert ground_requirements[0].kind == "spatial"


def test_exploration_request_preserves_producer_owned_requirement_set() -> None:
    source = requirements_from_l1(
        L1Snapshot(
            artifact_id="l1-run-b",
            evidence_gaps=[
                EvidenceGap(
                    gap_id="gap-2",
                    dimension="population",
                    description="需要核实人口基数",
                )
            ],
        )
    )
    request = ExplorationRequest(
        run_id="run-b",
        request_type="evidence_gap",
        query="补齐 L1 缺口",
        stage="L1",
        requirements=list(source),
    )

    compiled = compile_requirements(request)
    assert tuple(item.requirement_id for item in compiled) == tuple(
        item.requirement_id for item in source
    )
    assert compiled[0].producer_stage == "L1"


def test_l3_structured_inputs_are_routed_as_retrieval_requirements() -> None:
    claim = PlanningClaim(
        claim_id="claim-road",
        statement="拓宽村道并连接道路节点",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        location_hints=["金田村"],
        planning_role="spatial_intervention",
        project_package_ref="pkg-road",
        evidence_refs=["l1:fact:road"],
        road_parameters=RoadPlanningParameters(
            action="widen",
            length_m=120,
            roadbed_width_m=6,
            pavement_width_m=4,
        ),
    )
    intervention = PlanningIntervention(
        intervention_id="target-road",
        target_id="target-road",
        name="村道拓宽",
        planning_role="spatial_intervention",
        project_package_ref="pkg-road",
        admission_reason="typed_spatial_claim_ready",
        execution_mode="spatial",
        expected_output_kind="line",
        category="road",
        asset_kind="road",
        road_parameters=RoadPlanningParameters(
            action="widen",
            length_m=120,
            roadbed_width_m=6,
            pavement_width_m=4,
        ),
        claim_refs=[claim.claim_id],
        evidence_refs=["l1:fact:road"],
        spatial_requirements={
            "required_input_refs": ["l1:fact:road"],
            "network_refs": ["network:road:current"],
            "shared_resource_refs": ["bsm:parcel:road-buffer"],
            "grounding_requirements": ["candidate_geometry", "network_snapshot"],
            "relations": [{
                "relation_template": "connect_network",
                "relation_id": "rel-road-connect",
                "subject_ref": "target-road",
                "object_ref": "road:endpoint:b",
                "parameters": {
                    "network_ref": "network:road:current",
                },
            }],
        },
    )
    requirements = requirements_from_l3(
        PlanningProgram(
            artifact_id="l3-structured",
            claims=[claim],
            interventions=[intervention],
        )
    )
    roles = {item.evidence_role for item in requirements}
    assert {"l3_required_input", "l3_network_snapshot", "l3_candidate_geometry", "l3_relation_network"} <= roles
    assert any(item.source_artifact_refs == ("network:road:current",) for item in requirements)
    assert all(item.producer_stage == "L3" for item in requirements)


def test_target_projection_graph_relations_keep_network_and_topology_requirements() -> None:
    graph = PlanningIntentGraph(
        nodes=[],
        relations=[
            PlanRelationIntent(
                relation_id="rel-connect",
                relation_template="connect_network",
                subject_ref="target-road",
                object_ref="road:endpoint",
                parameters=ConnectParameters(
                    network_kind="road",
                    endpoint_tolerance_m=20,
                    network_ref="network:road:current",
                ),
            ),
            PlanRelationIntent(
                relation_id="rel-part",
                relation_template="part_of",
                subject_ref="target-facility",
                object_ref="target-zone",
                parameters={"parameter_type": "part_of", "parent_ref": "target-zone"},
            ),
        ],
        shared_resource_refs=["bsm:parcel:shared"],
    )
    target = IntentCompilationResult(
        artifact_id="target-structured",
        intent_graph=graph,
    )
    requirements = requirements_from_target_projection(target)
    roles = {item.evidence_role for item in requirements}
    assert "l3_relation_network" in roles
    assert "l3_relation_topology" in roles
    assert "l3_shared_resource" in roles
    assert all(item.producer_stage == "TARGET_PROJECTION" for item in requirements)
