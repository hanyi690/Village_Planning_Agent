from app.modules.schema.contracts.execution_plan_contracts import ExecutionPlan, WorkerTask, WorkerType, ExecutionResult
from app.modules.schema.contracts.parcel_change_contracts import ParcelChangeSet, ParcelChange
from app.modules.schema.contracts.planned_state_contracts import PlannedState, PlannedParcel
from app.modules.schema.contracts.land_balance_contracts import LandBalanceTable, LandBalanceRow
from app.modules.schema.contracts.validation_report_contracts import ValidationReport, ValidationCheck, ValidationIssue, ConstraintAdjustment
from app.modules.schema.contracts.reconciliation_contracts import ReconciliationReport, CoverageMatrix, ReconciliationInconsistency
from app.modules.schema.contracts.delivery_manifest_contracts import DeliveryManifest, Deliverable, TraceabilityEntry, HumanItem, DeliveryGate
from app.modules.schema.contracts.review_contracts import ReviewPackage, ReviewStatus, HumanReviewRequest, ReviewDecision, ReviewComment


def test_execution_plan_has_worker_tasks():
    wt = WorkerTask(task_id="wt-1", worker_type=WorkerType.PARCEL_TRANSFORMATION, payload={}, depends_on=[])
    ep = ExecutionPlan(context_version="v1", artifact_id="exec-1", plan_id="p1", worker_tasks=[wt], dependencies=[])
    assert ep.worker_tasks[0].worker_type == WorkerType.PARCEL_TRANSFORMATION


def test_worker_type_enum():
    assert WorkerType.ROAD_CONSTRUCTION.value == "road_construction"


def test_parcel_changeset_has_conservation_flag():
    pc = ParcelChange(bsm="BSM001", action="split", derived_from_bsms=["BSM001"])
    cs = ParcelChangeSet(context_version="v1", artifact_id="cs-1", changes=[pc], area_conservation_verified=True, geometry_validity_verified=True)
    assert cs.area_conservation_verified is True


def test_planned_state_schema_level():
    pp = PlannedParcel(bsm="BSM001", planning_land_use="0101", area_ha=5.0, derived_from_bsms=["BSM001"])
    ps = PlannedState(version="v1", parcels=[pp], zones=[], facilities=[], roads=[], axes=[])
    assert ps.planned_parcels if hasattr(ps, "planned_parcels") else ps.parcels[0].bsm == "BSM001"


def test_land_balance_table():
    row = LandBalanceRow(land_use_name="耕地", land_use_code="0101", planning_zone="农田保护区", current_area_ha=10.0, current_ratio=0.5, planned_area_ha=9.0, planned_ratio=0.45, change_ha=-1.0, change_pct=-10.0)
    tbl = LandBalanceTable(rows=[row], total_current_area_ha=10.0, total_planned_area_ha=9.0, closure_deviation_pct=1.0)
    assert tbl.rows[0].change_ha == -1.0


def test_validation_report_unified():
    vc = ValidationCheck(check_id="vc-1", check_name="面积守恒", passed=True, responsible_stage="EXECUTE")
    vr = ValidationReport(context_version="v1", artifact_id="val-1", checks=[vc], overall_passed=True, issues_by_stage={})
    assert vr.overall_passed is True


def test_validation_issue_extends_stage_issue():
    vi = ValidationIssue(stage="EXECUTE", severity="error", code="AREA_LOSS", message="面积损失", check_id="vc-1")
    assert vi.check_id == "vc-1"
    assert vi.severity == "error"


def test_constraint_adjustment():
    ca = ConstraintAdjustment(constraint_id="c1", adjustment_type="relax", original_value=0.5, adjusted_value=0.4)
    assert ca.adjusted_value == 0.4


def test_reconciliation_report_has_coverage():
    rr = ReconciliationReport(context_version="v1", artifact_id="rec-1", coverage_matrix=CoverageMatrix(rows=[]), inconsistencies=[])
    assert rr.inconsistencies == []


def test_delivery_manifest_has_pending_items():
    hi = HumanItem(item_id="hi-1", description="补充规划分类编码", reason="未明确规划分类", blocking=True)
    dm = DeliveryManifest(context_version="v1", artifact_id="del-1", deliverables=[], traceability=[], pending_human_items=[hi], delivery_gate=None)
    assert dm.pending_human_items[0].blocking is True


def test_delivery_gate_passed():
    dg = DeliveryGate(land_balance_closed=True, three_line_violations=0, protected_intrusions=0, changed_parcels_pct=0.1, changed_parcels_threshold=0.5, zones_complete=True)
    assert dg.passed is True


def test_review_package():
    rp = ReviewPackage(run_id="r1", module="l1_observe", summary_md="# 审查", artifact_json={}, trace_json={})
    assert rp.status == ReviewStatus.AWAITING_REVIEW


def test_review_decision():
    rd = ReviewDecision(request_id="req-1", decision="approved", comments="ok")
    assert rd.decision == "approved"
