"""Guardrail: the GROUND subgraph must not import kg or the legacy select package.

Wave G requires GROUND to stay decoupled from the knowledge-graph implementation
layer (app.modules.kg) and from the legacy parse agent (app.agent.select). The
independent spatial_ops scan locks the Task 2 regression fix (95932851) that
removed spatial_ops -> kg reverse imports. The AST scan is authoritative; the
sys.modules snapshot is a best-effort delta check (it only flags kg modules newly
loaded by importing the ground package, so it tolerates kg being pre-loaded by
other fixtures in the full suite).
"""
from __future__ import annotations

import ast
import pathlib
import sys

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"
_GROUND_DIR = _PACKAGE_ROOT / "agent" / "ground"
_SPATIAL_OPS_DIR = _PACKAGE_ROOT / "modules" / "spatial_ops"


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


def _test_matcher_detects_forbidden_import():
    tree = ast.parse(
        "from app.modules.kg.ontology import PLN\nimport app.modules.kg\n"
    )
    found = [ref for node in ast.walk(tree) for ref in _module_refs(node)]
    assert _matches_any(found[0], ("app.modules.kg",))
    assert _matches_any(found[1], ("app.modules.kg",))


def test_ground_package_no_kg_imports():
    offenders = _scan_for(_GROUND_DIR, ("app.modules.kg",))
    assert not offenders, "ground imports kg:\n" + "\n".join(offenders)


def test_ground_package_no_agent_select_imports():
    offenders = _scan_for(_GROUND_DIR, ("app.agent.select",))
    assert not offenders, "ground imports app.agent.select:\n" + "\n".join(offenders)


def test_ground_package_no_legacy_parse_agent():
    offenders = _scan_for(_GROUND_DIR, ("app.agent.select.parse_agent",))
    assert not offenders, "ground imports app.agent.select.parse_agent:\n" + "\n".join(
        offenders
    )


def test_import_ground_loads_no_kg_modules():
    before = set(sys.modules)
    import app.agent.ground  # noqa: F401

    new_modules = set(sys.modules) - before
    offenders = [
        name for name in new_modules if name.startswith("app.modules.kg")
    ]
    assert not offenders, "importing ground loaded kg modules: " + ", ".join(
        sorted(offenders)
    )


def test_spatial_ops_no_kg_imports_regression():
    offenders = _scan_for(_SPATIAL_OPS_DIR, ("app.modules.kg",))
    assert not offenders, "spatial_ops imports kg:\n" + "\n".join(offenders)


_ALLOWED_APP_ROOTS = (
    "app.modules.schema",
    "app.modules.context",
    "app.modules.spatial_ops",
    "app.agent.common",
)


def _disallowed_app_imports(node):
    for ref in _module_refs(node):
        if ref.startswith("app.") and not _matches_any(ref, _ALLOWED_APP_ROOTS):
            yield ref


def test_ground_imports_only_schema_context_spatial_ops_and_common():
    offenders = []
    for file in _py_files(_GROUND_DIR):
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _disallowed_app_imports(node):
                offenders.append(f"{file.name}: {ref!r}")
    assert not offenders, "ground reaches beyond schema/context/spatial_ops/common:\n" + "\n".join(
        offenders
    )
