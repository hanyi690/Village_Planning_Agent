"""Guardrail: the EXECUTE chain must not import advisory_crosswalks.

Wave I requires app.agent.execute and app.tools.gis._generation (including its
optimizer/ subdir) to stay decoupled from app.modules.schema.advisory_crosswalks.
Wave J Task 7 deleted the final 3 dev/validation-only files (dynamic_zoning,
compare_layouts, layout_validator), shrinking the violation budget to zero. The
AST scan is authoritative; the sys.modules snapshot is a best-effort delta check
(it only flags crosswalk modules newly loaded by importing app.agent.execute, so
it tolerates crosswalks being pre-loaded by other fixtures in the full suite).
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
_EXECUTE_DIR = _PACKAGE_ROOT / "agent" / "execute"
_GENERATION_DIR = _PACKAGE_ROOT / "tools" / "gis" / "_generation"
_BACKEND_ROOT = pathlib.Path(__file__).resolve().parents[3]

_CROSSWALK_ROOTS = ("app.modules.schema.advisory_crosswalks", "advisory_crosswalks")

_DELETED_LEGACY_FILES = (
    "app/tools/gis/_generation/optimizer/mip_allocator.py",
    "app/tools/gis/_generation/optimizer/mip_solver.py",
    "app/tools/gis/_generation/optimizer/planning_zone_mapper.py",
    "app/tools/gis/_generation/zone_generator.py",
    "app/tools/gis/_generation/land_use_zone_generator.py",
    "app/tools/gis/_generation/space_control_generator.py",
    "app/tools/gis/_generation/zone_type_deriver.py",
    "app/tools/gis/generate.py",
)

_EXPECTED_BUDGET_FILES = ()


def _py_files(directory):
    return sorted(directory.glob("*.py"))


def _py_files_recursive(directory):
    return sorted(directory.rglob("*.py"))


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


def _scan_for(directory, roots):
    return _scan_files(_py_files(directory), roots)


def test_execute_agent_no_crosswalk_imports():
    offenders = _scan_for(_EXECUTE_DIR, _CROSSWALK_ROOTS)
    assert not offenders, "execute imports advisory_crosswalks:\n" + "\n".join(
        offenders
    )


def test_generation_no_crosswalk_imports():
    offenders = _scan_files(_py_files_recursive(_GENERATION_DIR), _CROSSWALK_ROOTS)
    assert not offenders, (
        "gis _generation imports advisory_crosswalks:\n" + "\n".join(offenders)
    )


def test_deleted_legacy_files_removed():
    remaining = []
    for rel in _DELETED_LEGACY_FILES:
        if os.path.exists(_BACKEND_ROOT / rel):
            remaining.append(rel)
    assert not remaining, "legacy-gated files still exist:\n" + "\n".join(remaining)


def test_crosswalk_budget_is_zero():
    assert len(VIOLATION_BUDGET) == 0
    assert set(VIOLATION_BUDGET) == set(_EXPECTED_BUDGET_FILES)
    assert LEGACY_GATED_FILES == []
    for rel in _DELETED_LEGACY_FILES:
        assert rel not in VIOLATION_BUDGET, f"{rel} must not be in the violation budget"


def test_import_execute_loads_no_crosswalks():
    before = set(sys.modules)
    import app.agent.execute  # noqa: F401

    new_modules = set(sys.modules) - before
    offenders = [
        name for name in new_modules if "advisory_crosswalks" in name
    ]
    assert not offenders, (
        "importing execute loaded advisory_crosswalks: " + ", ".join(sorted(offenders))
    )


def test_matcher_detects_crosswalk_imports():
    tree = ast.parse(
        "from app.modules.schema.advisory_crosswalks import dynamic_zoning\n"
        "import app.modules.schema.advisory_crosswalks\n"
    )
    found = [ref for node in ast.walk(tree) for ref in _module_refs(node)]
    assert _matches_any(found[0], _CROSSWALK_ROOTS)
    assert _matches_any(found[1], _CROSSWALK_ROOTS)
