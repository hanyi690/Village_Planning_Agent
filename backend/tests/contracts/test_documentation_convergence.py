import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DOCS = ROOT / "docs"

ACTIVE_DESIGN = {
    "README.md",
    "00_SYSTEM_DESIGN.md",
    "01_CONTRACTS_AND_INVARIANTS.md",
    "02_EVIDENCE_AND_GROUNDING.md",
    "03_PLANNING_EXECUTION.md",
    "04_EVALUATION_AND_ACCEPTANCE.md",
    "05_MIGRATION.md",
}

ACTIVE_ARCHITECTURE = {
    "README.md",
    "CURRENT_RUNTIME.md",
    "API_AND_STATE.md",
    "OPERATIONS.md",
}

AUTHORITATIVE_CHAIN = (
    "L1 / L2 / L3",
    "TARGET_PROJECTION",
    "GROUND",
    "GroundedPlanningProblem",
    "ScenarioOptimizer",
    "ScenarioSet",
    "Approval Gate",
    "ApprovedExecutionInput",
    "Atomic EXECUTE",
    "PlannedState",
    "VALIDATE",
    "ValidationCertificate",
    "RECONCILE",
    "DELIVER",
)


def test_active_document_sets_are_small_and_canonical() -> None:
    design = {path.name for path in (DOCS / "design").glob("*.md")}
    architecture = {path.name for path in (DOCS / "architecture").glob("*.md")}
    assert design == ACTIVE_DESIGN
    assert architecture == ACTIVE_ARCHITECTURE


def test_active_docs_do_not_link_to_retired_status_ledgers() -> None:
    retired = re.compile(
        r"10_IMPLEMENTATION_STATUS|27_IMPLEMENTATION_VS_DESIGN|"
        r"RELATION_AWARE_MODIFICATION_LEDGER|IMPLEMENTATION_GAP_AUDIT"
    )
    active = [DOCS / "README.md"]
    active += list((DOCS / "design").glob("*.md"))
    active += list((DOCS / "architecture").glob("*.md"))
    violations = [
        str(path.relative_to(ROOT))
        for path in active
        if retired.search(path.read_text(encoding="utf-8"))
    ]
    assert violations == []


def test_runtime_comments_do_not_reference_retired_active_docs() -> None:
    retired = re.compile(
        r"docs/architecture/agent-graph\.md|"
        r"docs/design/04_PLANNING_PIPELINE\.md|"
        r"docs/design/07_VALIDATION_FEEDBACK\.md|"
        r"docs/design/12_PLACE_NAME_RESOLUTION\.md"
    )
    violations = []
    for path in (ROOT / "backend" / "app").rglob("*.py"):
        if retired.search(path.read_text(encoding="utf-8")):
            violations.append(str(path.relative_to(ROOT)))
    assert violations == []


def test_active_docs_declare_status_and_authority() -> None:
    active = list((DOCS / "design").glob("*.md"))
    active += list((DOCS / "architecture").glob("*.md"))
    missing = []
    for path in active:
        text = path.read_text(encoding="utf-8")
        if "Status:" not in text or "Authority:" not in text:
            missing.append(str(path.relative_to(ROOT)))
    assert missing == []


def test_system_design_preserves_the_authoritative_planning_chain() -> None:
    text = (DOCS / "design" / "00_SYSTEM_DESIGN.md").read_text(encoding="utf-8")
    chain = text.split("正常主链是：", 1)[1].split("```text", 1)[1].split("```", 1)[0]
    positions = [chain.index(name) for name in AUTHORITATIVE_CHAIN]
    assert positions == sorted(positions)
    assert "现有 SELECT 的目标内核" in text
    assert "不要求各自成为新的顶层图节点" in text


def test_target_specs_cover_planning_and_embedding_degradation() -> None:
    evidence = (DOCS / "design" / "02_EVIDENCE_AND_GROUNDING.md").read_text(
        encoding="utf-8"
    )
    planning = (DOCS / "design" / "03_PLANNING_EXECUTION.md").read_text(
        encoding="utf-8"
    )
    assert "嵌入服务失效时" in evidence
    assert "GROUND explicitly forbids final location selection" in evidence
    assert "A single weighted winner is not a sufficient planning product" in planning
    assert "An infeasible result is a valid outcome" in planning
    assert "EXECUTE explicitly forbids re-selecting a location" in planning


def test_current_runtime_distinguishes_implemented_partial_boundaries() -> None:
    text = (DOCS / "architecture" / "CURRENT_RUNTIME.md").read_text(encoding="utf-8")
    assert "max_scenarios=1" in text
    assert "ScenarioSet" in text
    assert "[`ApprovedExecutionInput`]" in text
    assert "staging ChangeSet" in text
    assert "`ValidationCertificate`" in text
