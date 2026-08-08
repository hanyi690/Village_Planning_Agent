"""Advisory-crosswalk runtime-isolation tests (Wave A.1).

Requirement (Wave A.1 acceptance):
- The default active chain must not be able to reach
  ``app.modules.schema.advisory_crosswalks`` transitively.
- The old mapping-style EXECUTE chain must fail-closed by default.
- ``map_code`` must not be registered/exposed to the LLM.
- The crosswalk violation budget is MONOTONE NON-INCREASING: it may only
  shrink (each wave removes entries) and must eventually reach zero.

These tests use the AST import-graph scanner in ``_import_graph.py``, which
resolves absolute + relative imports (including function-level lazy imports)
so it catches transitive reachability that a naive direct-import scan misses
(e.g. EXECUTE -> tools/gis/generate -> advisory_crosswalks).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests.unit._import_graph import (
    BACKEND_ROOT,
    build_imports,
    count_crosswalk_imports,
    reachable_modules,
)

APP_ROOT = BACKEND_ROOT / "app"


# ── Active-chain root modules ─────────────────────────────────────────
# The default planning path: all agent stages + the GIS tool bundle that
# EXECUTE invokes + KG builder/service + LLM tool bundles.
def _active_chain_roots() -> list[str]:
    roots = []
    for f in APP_ROOT.rglob("*.py"):
        if "__pycache__" in str(f):
            continue
        r = str(f.relative_to(BACKEND_ROOT)).replace("\\", "/")
        if r.startswith("app/agent/") or r.startswith("app/tools/gis/"):
            roots.append(r)
    for extra in [
        "app/tools/tools.py",
        "app/tools/intent_tools.py",
        "app/tools/access/shared.py",
        "app/tools/__init__.py",
        "app/modules/kg/builder/__init__.py",
        "app/modules/kg/service.py",
        "app/modules/kg/interface.py",
    ]:
        p = BACKEND_ROOT / extra
        if p.exists():
            roots.append(extra)
    return roots


# ── Violation budget: monotone non-increasing ─────────────────────────
# When a wave removes a crosswalk import from an active-chain file, DELETE
# that file's entry here. Adding entries here is forbidden (budget only
# shrinks). The budget must reach zero before Wave A is marked final-pass.
#
# Current baseline (Wave J Task 7): 0 files / 0 imports reachable from the
# active chain — the final 3 legacy dev/validation tools (dynamic_zoning,
# compare_layouts, layout_validator) were deleted in Wave J, so the budget
# is now empty and the active chain is fully decoupled from the legacy
# cross-system mapping symbols.
VIOLATION_BUDGET: dict[str, int] = {}


@pytest.fixture(scope="module")
def _imports():
    return build_imports()


def test_crosswalk_budget_monotone_non_increasing(_imports):
    """Active chain's reachable crosswalk imports must never exceed the budget."""
    per_file, total = count_crosswalk_imports(_active_chain_roots(), _imports)
    budget_total = sum(VIOLATION_BUDGET.values())
    assert total <= budget_total, (
        f"advisory_crosswalks reachable from active chain grew: {total} > {budget_total}.\n"
        "The budget only shrinks. New violations must be removed, not added to the budget.\n"
        f"Files: {sorted(per_file)}"
    )


def test_crosswalk_budget_matches_actual(_imports):
    """Budget entries must exactly match current reachable violations (no stale/extra)."""
    per_file, _ = count_crosswalk_imports(_active_chain_roots(), _imports)
    assert set(per_file) == set(VIOLATION_BUDGET), (
        "Violation budget mismatch.\n"
        f"  budget-only (stale, remove): {sorted(set(VIOLATION_BUDGET) - set(per_file))}\n"
        f"  actual-only (must fix): {sorted(set(per_file) - set(VIOLATION_BUDGET))}"
    )


def test_no_direct_crosswalk_in_forbidden_agent_stages(_imports):
    """Forbidden stages must not import advisory_crosswalks even directly."""
    forbidden_dirs = [
        "app/agent/l1_observe",
        "app/agent/l2_strategize",
        "app/agent/l3_plan",
        "app/agent/ground",
        "app/agent/select",
        "app/agent/execute",
        "app/agent/validate",
        "app/agent/parse",
        "app/agent/reconcile",
        "app/agent/deliver",
        "app/agent/bootstrap",
        "app/tools/gis/_generation",
    ]
    pattern = re.compile(
        r"^\s*(?:from|import) app\.modules\.schema\.advisory_crosswalks"
    )
    offenders = []
    for dir_rel in forbidden_dirs:
        target = BACKEND_ROOT / dir_rel
        if not target.exists():
            continue
        for py_file in target.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            for i, line in enumerate(py_file.read_text(encoding="utf-8").splitlines(), 1):
                if pattern.match(line):
                    offenders.append(f"{dir_rel}:{i}")
    assert not offenders, "forbidden stages import advisory_crosswalks:\n" + "\n".join(offenders)


# ── map_code must not be exposed to the LLM ───────────────────────────
def test_map_code_not_in_llm_tool_bundle():
    """The LLM tool bundle must not include the cross-system map_code tool."""
    from app.tools.gis import get_gis_pipeline_tools

    tools = get_gis_pipeline_tools()
    names = {getattr(t, "name", "") for t in tools}
    assert "map_code" not in names, "map_code must not be registered/exposed to the LLM"


def test_map_code_not_exported_from_lookup_module():
    """map_code must not be exported from the lookup module (same-system only)."""
    lookup_path = APP_ROOT / "tools" / "gis" / "lookup.py"
    if not lookup_path.exists():
        pytest.skip("lookup.py not found")
    src = lookup_path.read_text(encoding="utf-8")
    m = re.search(r"__all__\s*=\s*\[(.*?)\]", src, re.S)
    assert m and "map_code" not in m.group(1), "map_code must not be in lookup module __all__"


def test_active_chain_no_map_code_definition_exposure():
    """No active-chain module may define an exported cross-system map_code tool."""
    lookup_path = APP_ROOT / "tools" / "gis" / "lookup.py"
    src = lookup_path.read_text(encoding="utf-8")
    m = re.search(r"__all__\s*=\s*\[(.*?)\]", src, re.S)
    assert m and "map_code" not in m.group(1)


# ── Legacy files must be fail-closed (gated) ──────────────────────────
# Wave I deleted the 8 legacy-gated EXECUTE-chain files, so no legacy file
# remains. The list is intentionally empty.
LEGACY_GATED_FILES = []


def test_legacy_files_still_in_violation_budget():
    """Every legacy file must remain in the violation budget (not removed)."""
    for rel in LEGACY_GATED_FILES:
        assert rel in VIOLATION_BUDGET, (
            f"{rel} is legacy-gated and must stay in VIOLATION_BUDGET "
            "(cleared in Wave I when rewritten)"
        )


def test_legacy_crosswalk_imports_are_gated():
    """Every advisory_crosswalks import in a legacy file must be gated.

    Each legacy file that imports advisory_crosswalks must also use
    require_legacy / legacy_enabled so no ungated crosswalk access remains.
    """
    crosswalk_import = re.compile(r"(from app\.modules\.schema\.advisory_crosswalks|import app\.modules\.schema\.advisory_crosswalks)")
    gate_usage = re.compile(r"require_legacy\s*\(|legacy_enabled\s*\(")
    ungated = []
    for rel in LEGACY_GATED_FILES:
        p = BACKEND_ROOT / rel
        src = p.read_text(encoding="utf-8")
        if not crosswalk_import.search(src):
            continue
        if not gate_usage.search(src):
            ungated.append(rel)
    assert not ungated, (
        "legacy files import advisory_crosswalks without a require_legacy/"
        "legacy_enabled gate (must be fail-closed):\n" + "\n".join(ungated)
    )
