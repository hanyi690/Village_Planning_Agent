"""Guardrail: the RECONCILE subgraph must not import advisory_crosswalks.

Wave K requires app.agent.reconcile to stay decoupled from
app.modules.schema.advisory_crosswalks. Wave K Tasks 1-6 cleaned the
package, so the AST scan is authoritative; the sys.modules snapshot is a
best-effort delta check (it only flags crosswalk modules newly loaded by
importing app.agent.reconcile, so it tolerates crosswalks being pre-loaded
by other fixtures in the full suite).
"""
from __future__ import annotations

import ast
import pathlib
import sys

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"
_RECONCILE_DIR = _PACKAGE_ROOT / "agent" / "reconcile"

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


def _scan_for(directory, roots):
    offenders = []
    for file in _py_files(directory):
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _module_refs(node):
                if _matches_any(ref, roots):
                    offenders.append(f"{file.name}: {ref!r}")
    return offenders


def test_reconcile_package_no_crosswalk_imports():
    offenders = _scan_for(_RECONCILE_DIR, _CROSSWALK_ROOTS)
    assert not offenders, "reconcile imports advisory_crosswalks:\n" + "\n".join(
        offenders
    )


def test_import_reconcile_loads_no_crosswalks():
    before = set(sys.modules)
    import app.agent.reconcile  # noqa: F401

    new_modules = set(sys.modules) - before
    offenders = [
        name for name in new_modules if "advisory_crosswalks" in name
    ]
    assert not offenders, (
        "importing reconcile loaded advisory_crosswalks: "
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
