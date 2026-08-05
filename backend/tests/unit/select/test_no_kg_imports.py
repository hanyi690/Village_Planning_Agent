"""Guardrail: the SELECT subgraph must not import kg or the legacy select package.

Wave H requires SELECT to stay decoupled from the knowledge-graph implementation
layer (app.modules.kg) and from the legacy parse agent (app.agent.select). The
independent spatial_ops scan locks selection.py as a pure module with no
app.agent imports. The AST scan is authoritative; the sys.modules snapshot is a
best-effort delta check (it only flags kg modules newly loaded by importing the
select package, so it tolerates kg being pre-loaded by other fixtures in
the full suite).
"""
from __future__ import annotations

import ast
import pathlib
import sys

_PACKAGE_ROOT = pathlib.Path(__file__).resolve().parents[3] / "app"
_SELECT_DIR = _PACKAGE_ROOT / "agent" / "select"
_SPATIAL_OPS_SELECTION_FILE = _PACKAGE_ROOT / "modules" / "spatial_ops" / "selection.py"


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


def _scan_for(directory, roots):
    return _scan_files(_py_files(directory), roots)


def _test_matcher_detects_forbidden_import():
    tree = ast.parse(
        "from app.modules.kg.ontology import PLN\n"
        "import app.modules.kg\n"
        "from app.agent.select.parse_agent import parse_agent\n"
        "import app.agent.select\n"
    )
    refs = [ref for node in ast.walk(tree) for ref in _module_refs(node)]
    assert _matches_any(refs[0], ("app.modules.kg",))
    assert _matches_any(refs[1], ("app.modules.kg",))
    assert _matches_any(refs[2], ("app.agent.select",))
    assert _matches_any(refs[2], ("app.agent.select.parse_agent",))
    assert _matches_any(refs[3], ("app.agent",))
    assert _matches_any(refs[3], ("app.agent.select",))


def test_select_package_no_kg_imports():
    _test_matcher_detects_forbidden_import()
    offenders = _scan_for(_SELECT_DIR, ("app.modules.kg",))
    assert not offenders, "select imports kg:\n" + "\n".join(offenders)


def test_select_package_no_legacy_parse_agent():
    offenders = _scan_for(_SELECT_DIR, ("app.agent.select.parse_agent",))
    assert not offenders, (
        "select imports app.agent.select.parse_agent:\n" + "\n".join(offenders)
    )


def test_import_select_loads_no_kg_modules():
    before = set(sys.modules)
    import app.agent.select  # noqa: F401

    new_modules = set(sys.modules) - before
    offenders = [
        name for name in new_modules if name.startswith("app.modules.kg")
    ]
    assert not offenders, "importing select loaded kg modules: " + ", ".join(
        sorted(offenders)
    )


def test_spatial_ops_selection_no_agent_imports():
    offenders = _scan_files([_SPATIAL_OPS_SELECTION_FILE], ("app.agent",))
    assert not offenders, "selection.py imports app.agent:\n" + "\n".join(offenders)


_ALLOWED_APP_ROOTS = (
    "app.modules.schema",
    "app.modules.context",
    "app.modules.spatial_ops",
    "app.agent.select",
    "app.modules.ports",
)


def _disallowed_app_imports(node):
    for ref in _module_refs(node):
        if ref.startswith("app.") and not _matches_any(ref, _ALLOWED_APP_ROOTS):
            yield ref


def test_select_imports_only_allowed_modules():
    offenders = []
    for file in _py_files(_SELECT_DIR):
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _disallowed_app_imports(node):
                offenders.append(f"{file.name}: {ref!r}")
    assert not offenders, (
        "select reaches beyond schema/context/spatial_ops/ports/select:\n"
        + "\n".join(offenders)
    )
