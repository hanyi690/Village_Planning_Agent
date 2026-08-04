"""Guardrail: app/agent/bootstrap must not import advisory_crosswalks.

Wave M1 introduces the post-L3 chain (post_l3_chain.py / post_l3_nodes.py /
post_l3_state.py) in app/agent/bootstrap. This subgraph must stay decoupled
from app.modules.schema.advisory_crosswalks. The AST scan is authoritative;
the sys.modules snapshot is a best-effort delta check.
"""
from __future__ import annotations

import ast
import pathlib
import sys

from tests.unit.test_no_advisory_crosswalk_imports import (
    LEGACY_GATED_FILES,
    VIOLATION_BUDGET,
)

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"
_BOOTSTRAP_DIR = _PACKAGE_ROOT / "agent" / "bootstrap"

_CROSSWALK_ROOTS = ("app.modules.schema.advisory_crosswalks", "advisory_crosswalks")


def _py_files(directory):
    return sorted(directory.glob("*.py"))


def _module_refs(node):
    refs = []
    if isinstance(node, ast.Import):
        refs.extend(a.name for a in node.names)
    elif isinstance(node, ast.ImportFrom) and node.module:
        refs.append(node.module)
    return refs


def _matches_any(ref, roots):
    return any(ref == root or ref.startswith(root + ".") for root in roots)


def _scan_files(files, roots):
    offenders = []
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _module_refs(node):
                if _matches_any(ref, roots):
                    offenders.append(f"{file.name}: {ref!r}")
    return offenders


def test_bootstrap_no_crosswalk_imports():
    offenders = _scan_files(_py_files(_BOOTSTRAP_DIR), _CROSSWALK_ROOTS)
    assert not offenders, "bootstrap imports advisory_crosswalks:\n" + "\n".join(
        offenders
    )


def test_bootstrap_budget_is_zero():
    assert len(VIOLATION_BUDGET) == 0
    assert LEGACY_GATED_FILES == []


def test_import_bootstrap_loads_no_crosswalks():
    before = set(sys.modules)
    import app.agent.bootstrap  # noqa: F401

    new_modules = set(sys.modules) - before
    offenders = [
        name for name in new_modules if "advisory_crosswalks" in name
    ]
    assert not offenders, (
        "importing bootstrap loaded advisory_crosswalks: " + ", ".join(sorted(offenders))
    )


def test_matcher_detects_crosswalk_imports():
    tree = ast.parse(
        "from app.modules.schema.advisory_crosswalks import dynamic_zoning\n"
        "import app.modules.schema.advisory_crosswalks\n"
    )
    found = [ref for node in ast.walk(tree) for ref in _module_refs(node)]
    assert _matches_any(found[0], _CROSSWALK_ROOTS)
    assert _matches_any(found[1], _CROSSWALK_ROOTS)
