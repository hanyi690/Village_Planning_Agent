from app.modules.schema.contracts.context_ref_contracts import PlanningContextRef, DatasetRef
from app.modules.schema.contracts.workflow_contracts import (
    PlanningRunRequest, StageId, GateDecision, RoutingDecision, FeedbackRoute, PendingRequest,
)
from app.modules.schema.contracts.evidence_contracts import (
    ExplorationRequest, EvidenceBundle, EvidenceFact, EvidenceSource, EvidenceGapResolution,
)
from app.modules.schema.contracts.l1_contracts import L1Snapshot
from app.modules.schema.contracts.l2_contracts import L2Strategy, StrategyConflict
from app.modules.schema.contracts.l3_contracts import PlanningProgram, PlanningIntervention, InterventionDependency


def test_planning_run_request():
    req = PlanningRunRequest(run_id="r1", village_name="金田村", user_request="做村庄规划")
    assert req.run_id == "r1"


def test_stage_id_enum():
    assert StageId.L1.value == "l1"
    assert StageId.DELIVER.value == "deliver"


def test_planning_context_ref():
    ref = PlanningContextRef(run_id="r1", village_name="金田村", dataset_refs=[], context_version="v1", artifact_id="ctx-1")
    assert ref.village_name == "金田村"
    assert ref.schema_version == "1.0"


def test_gate_decision_with_feedback():
    gd = GateDecision(stage="L1", passed=False, feedback_route="EXPLORE", evidence_requests=["人口数据"], artifact_id="gd-1")
    assert gd.passed is False
    assert gd.evidence_requests == ["人口数据"]


def test_routing_decision():
    rd = RoutingDecision(target_stage="L3", reason="L1+L2 complete", payload_refs=[])
    assert rd.target_stage == "L3"


def test_feedback_route_and_pending():
    fr = FeedbackRoute(source_stage="VALIDATE", target_stage="SELECT", issue_type="site", reason="候选不足")
    pr = PendingRequest(request_id="pr-1", stage="EXPLORE", request_type="evidence", context={})
    assert fr.target_stage == "SELECT"
    assert pr.request_id == "pr-1"


def test_evidence_bundle_has_meta():
    eb = EvidenceBundle(context_version="v1", artifact_id="ev-1", request="查基本农田", facts=[], sources=[], confidence=0.8, unresolved=[])
    assert eb.schema_version == "1.0"
    assert eb.artifact_id == "ev-1"
    assert eb.confidence == 0.8


def test_evidence_fact_and_source():
    fact = EvidenceFact(statement="金田村基本农田50ha", confidence=0.9)
    src = EvidenceSource(source_type="report", reference="L1-001")
    assert fact.statement.startswith("金田村")
    assert src.source_type == "report"


def test_exploration_request():
    er = ExplorationRequest(run_id="r1", request_type="evidence_gap", query="金田村人口数据")
    assert er.query == "金田村人口数据"
    assert er.evidence_gaps_to_resolve == []


def test_l1_snapshot_has_gaps():
    snap = L1Snapshot(context_version="v1", artifact_id="l1-1", facts=[], constraints=[], issues=[], opportunities=[], evidence_gaps=["缺少人口数据"], sources=[])
    assert snap.evidence_gaps == ["缺少人口数据"]


def test_l2_strategy():
    s = L2Strategy(context_version="v1", artifact_id="l2-1", development_goals=["农业现代化"], spatial_structure="一核两轴", implementation_priorities=[], strategy_conflicts=[], evidence_refs=[])
    assert s.spatial_structure == "一核两轴"


def test_l2_strategy_conflict():
    c = StrategyConflict(description="农业与建设冲突", between=["A", "B"])
    assert c.severity == "warning"


def test_planning_program():
    iv = PlanningIntervention(intervention_id="iv-1", name="村道拓宽", category="road", problem_addressed="道路窄", scale="2.5km", functions=["交通"], implementation_phase="short", spatial_requirements={}, constraints=[], evidence_refs=[])
    dep = InterventionDependency(from_intervention_id="iv-1", to_intervention_id="iv-2")
    prog = PlanningProgram(context_version="v1", artifact_id="l3-1", interventions=[iv], dependencies=[dep], omissions=[])
    assert prog.interventions[0].name == "村道拓宽"
    assert prog.dependencies[0].to_intervention_id == "iv-2"
