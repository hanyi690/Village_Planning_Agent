"""Test execution and validation contract types.

Verifies:
1. All new types can be constructed
2. No reverse dependencies in new contract files
3. ValidationCheckItem supports all 8 check IDs from design doc §5.6
4. MIPModel supports constraint compiler output structure
"""

import os


# ── Construction tests ──────────────────────────────────────────────


def test_mip_constraint():
    from app.modules.schema.contracts.execution_contracts import MIPConstraint
    c = MIPConstraint(
        constraint_type="hard",
        name="protected_farmland_lock",
        parcels=["BSM-001", "BSM-002"],
        zones=["construction"],
        coefficient=1.0,
        bound=0,
        sense="<=",
        source="kg_protected",
    )
    assert c.constraint_type == "hard"
    assert c.name == "protected_farmland_lock"


def test_mip_model():
    from app.modules.schema.contracts.execution_contracts import MIPModel
    model = MIPModel(
        variables={"BSM-001": ["construction", "agriculture"]},
        hard_constraints=[],
        soft_constraints=[],
        target_map={"construction": 50.0, "agriculture": 200.0},
    )
    assert "BSM-001" in model.variables


def test_execution_plan():
    from app.modules.schema.contracts.execution_contracts import ExecutionPlan, MIPModel
    plan = ExecutionPlan(mip_model=MIPModel())
    assert plan.intent is None
    assert plan.operations == []


def test_constraint_adjustment():
    from app.modules.schema.contracts.execution_contracts import ConstraintAdjustment
    adj = ConstraintAdjustment(
        constraint_id="construction_cap",
        adjustment_type="relax",
        original_value=50.0,
        adjusted_value=55.0,
        reason="面积偏差略超5%",
        source_check="construction_cap",
    )
    assert adj.adjustment_type == "relax"


def test_changelog_entry():
    from app.modules.schema.contracts.execution_contracts import ChangelogEntry
    entry = ChangelogEntry(
        entry_id="op-001",
        action="create",
        target_parcels=["BSM-003"],
        article_ref="第15条第二款",
    )
    assert entry.action == "create"


def test_clause_reference():
    from app.modules.schema.contracts.validation_contracts import ClauseReference
    ref = ClauseReference(
        document="金田村规划文本",
        article_number="第15条",
        clause="第二款",
        section="用地布局",
        raw_text="产业用地应布局在南部靠近主干道的位置",
    )
    assert ref.document == "金田村规划文本"


def test_validation_check_item():
    from app.modules.schema.contracts.validation_contracts import ValidationCheckItem
    item = ValidationCheckItem(
        check_id="construction_cap",
        check_name="建设用地不超上限",
        passed=True,
        actual_value=48.5,
        expected_value=50.0,
        deviation_pct=-3.0,
        constraint_source="kg_constraint",
    )
    assert item.passed is True


def test_validation_check_result():
    from app.modules.schema.contracts.validation_contracts import ValidationCheckResult, ValidationCheckItem
    result = ValidationCheckResult(
        checks=[
            ValidationCheckItem(check_id="construction_cap", passed=True),
            ValidationCheckItem(check_id="farmland_floor", passed=False),
        ],
        total_checks=2,
        passed_count=1,
    )
    assert result.overall_passed is False


def test_all_8_validation_checks():
    """Verify all 8 check IDs from design doc §5.6 can be constructed."""
    from app.modules.schema.contracts.validation_contracts import ValidationCheckItem
    check_ids = [
        "construction_cap",
        "farmland_floor",
        "no_basic_farmland",
        "no_ecological_redline",
        "within_boundary",
        "area_deviation",
        "adjacency_compliance",
        "three_line_compliance",
    ]
    for cid in check_ids:
        item = ValidationCheckItem(check_id=cid, passed=True)
        assert item.check_id == cid


# ── No reverse dependencies ─────────────────────────────────────────


def test_execution_contracts_no_reverse_deps():
    """Static check: execution_contracts.py does not import from tools/agent/kg."""
    fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "schema",
        "contracts", "execution_contracts.py",
    )
    fpath = os.path.normpath(fpath)
    import re
    import_pattern = re.compile(r'^\s*(from|import)\s+.*(app\.tools|app\.agent|app\.modules\.kg)')
    violations = []
    with open(fpath, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if import_pattern.match(line):
                violations.append(f"Line {lineno}: {line.strip()}")
    assert violations == [], f"Forbidden imports found:\n" + "\n".join(violations)


def test_validation_contracts_no_reverse_deps():
    """Static check: validation_contracts.py does not import from tools/agent/kg."""
    fpath = os.path.join(
        os.path.dirname(__file__), "..", "..", "app", "modules", "schema",
        "contracts", "validation_contracts.py",
    )
    fpath = os.path.normpath(fpath)
    import re
    import_pattern = re.compile(r'^\s*(from|import)\s+.*(app\.tools|app\.agent|app\.modules\.kg)')
    violations = []
    with open(fpath, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if import_pattern.match(line):
                violations.append(f"Line {lineno}: {line.strip()}")
    assert violations == [], f"Forbidden imports found:\n" + "\n".join(violations)
