"""Guardrail: the VALIDATE subgraph must not import advisory_crosswalks.

Wave J requires app.agent.validate to stay decoupled from
app.modules.schema.advisory_crosswalks. Wave J Task 7 deleted the final 3
dev/validation-only files (dynamic_zoning, compare_layouts, layout_validator),
shrinking the violation budget to zero. The AST scan is authoritative; the
sys.modules snapshot is a best-effort delta check (it only flags crosswalk
modules newly loaded by importing app.agent.validate, so it tolerates
crosswalks being pre-loaded by other fixtures in the full suite).
"""
from __future__ import annotations

import ast
import os
import pathlib
import sys

from tests.unit.test_no_advisory_crosswalk_imports import (
    LEGACY_GATED_FILES,
    VIOLATION_BUDGET,
)

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"
_VALIDATE_DIR = _PACKAGE_ROOT / "agent" / "validate"
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]

_CROSSWALK_ROOTS = ("app.modules.schema.advisory_crosswalks", "advisory_crosswalks")

_DELETED_CROSSWALK_FILES = (
    "app/tools/gis/_validation/layout_validator.py",
    "app/tools/gis/_rendering/compare_layouts.py",
    "app/tools/gis/_analytics/dynamic_zoning.py",
)

_EXPECTED_BUDGET_FILES = ()


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


def _scan_for(directory, roots):
    offenders = []
    for file in _py_files(directory):
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _module_refs(node):
                if _matches_any(ref, roots):
                    offenders.append(f"{file.name}: {ref!r}")
    return offenders


def test_validate_package_no_crosswalk_imports():
    offenders = _scan_for(_VALIDATE_DIR, _CROSSWALK_ROOTS)
    assert not offenders, "validate imports advisory_crosswalks:\n" + "\n".join(
        offenders
    )


def test_deleted_crosswalk_files_removed():
    remaining = []
    for rel in _DELETED_CROSSWALK_FILES:
        if os.path.exists(_BACKEND_ROOT / rel):
            remaining.append(rel)
    assert not remaining, "deleted crosswalk files still exist:\n" + "\n".join(
        remaining
    )


def test_crosswalk_budget_is_zero():
    assert len(VIOLATION_BUDGET) == 0
    assert set(VIOLATION_BUDGET) == set(_EXPECTED_BUDGET_FILES)
    assert LEGACY_GATED_FILES == []


def test_import_validate_loads_no_crosswalks():
    before = set(sys.modules)
    import app.agent.validate  # noqa: F401

    new_modules = set(sys.modules) - before
    offenders = [
        name for name in new_modules if "advisory_crosswalks" in name
    ]
    assert not offenders, (
        "importing validate loaded advisory_crosswalks: "
        + ", ".join(sorted(offenders))
    )


def test_matcher_detects_crosswalk_imports():
    tree = ast.parse(
        "from app.modules.schema.advisory_crosswalks import dynamic_zoning\n"
        "import app.modules.schema.advisory_crosswalks\n"
    )
    found = [ref for node in ast.walk(tree) for ref in _module_refs(node)]
    assert _matches_any(found[0], _CROSSWALK_ROOTS)
    assert _matches_any(found[1], _CROSSWALK_ROOTS)
