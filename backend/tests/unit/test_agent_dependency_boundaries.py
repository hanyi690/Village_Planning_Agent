"""Static dependency boundaries for the GROUND and SELECT subgraphs."""

from __future__ import annotations

import ast
import importlib
import sys
from pathlib import Path

import pytest


BACKEND_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = BACKEND_ROOT / "app"


BOUNDARIES = (
    {
        "name": "ground",
        "package": "app.agent.ground",
        "directory": APP_ROOT / "agent" / "ground",
        "forbidden": ("app.modules.kg", "app.agent.select"),
        "allowed": (
            "app.modules.schema",
            "app.modules.context",
            "app.modules.spatial_ops",
            "app.agent.common",
        ),
    },
    {
        "name": "select",
        "package": "app.agent.select",
        "directory": APP_ROOT / "agent" / "select",
        "forbidden": ("app.modules.kg", "app.agent.select.parse_agent"),
        "allowed": (
            "app.modules.schema",
            "app.modules.context",
            "app.modules.spatial_ops",
            "app.agent.select",
            "app.modules.ports",
        ),
    },
)


def _py_files(directory: Path) -> list[Path]:
    return sorted(directory.glob("*.py"))


def _module_refs(node: ast.AST) -> list[str]:
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if isinstance(node, ast.ImportFrom) and node.module:
        return [node.module]
    return []


def _matches_any(ref: str, roots: tuple[str, ...]) -> bool:
    return any(ref == root or ref.startswith(root + ".") for root in roots)


def _scan_files(files: list[Path], roots: tuple[str, ...]) -> list[str]:
    offenders = []
    for file in files:
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _module_refs(node):
                if _matches_any(ref, roots):
                    offenders.append(f"{file.name}: {ref!r}")
    return offenders


@pytest.mark.parametrize("boundary", BOUNDARIES, ids=lambda item: item["name"])
def test_agent_packages_avoid_forbidden_dependencies(boundary):
    offenders = _scan_files(_py_files(boundary["directory"]), boundary["forbidden"])
    assert not offenders, f"{boundary['name']} imports forbidden modules:\n" + "\n".join(offenders)


@pytest.mark.parametrize("boundary", BOUNDARIES, ids=lambda item: item["name"])
def test_importing_agent_packages_loads_no_kg_modules(boundary):
    before = {name for name in sys.modules if name.startswith("app.modules.kg")}
    importlib.import_module(boundary["package"])
    after = {name for name in sys.modules if name.startswith("app.modules.kg")}
    assert after == before, f"importing {boundary['name']} loaded kg modules: {sorted(after - before)}"


@pytest.mark.parametrize(
    ("files", "forbidden", "label"),
    [
        (
            [APP_ROOT / "modules" / "spatial_ops" / "selection" / "selection.py"],
            ("app.agent",),
            "spatial_ops.selection",
        ),
        (
            _py_files(APP_ROOT / "modules" / "spatial_ops"),
            ("app.modules.kg",),
            "spatial_ops",
        ),
    ],
    ids=lambda item: item if isinstance(item, str) else None,
)
def test_spatial_ops_avoid_upward_dependencies(files, forbidden, label):
    offenders = _scan_files(files, forbidden)
    assert not offenders, f"{label} imports forbidden modules:\n" + "\n".join(offenders)


@pytest.mark.parametrize("boundary", BOUNDARIES, ids=lambda item: item["name"])
def test_agent_packages_use_only_allowed_app_modules(boundary):
    offenders = []
    for file in _py_files(boundary["directory"]):
        tree = ast.parse(file.read_text(encoding="utf-8-sig"))
        for node in ast.walk(tree):
            for ref in _module_refs(node):
                if ref.startswith("app.") and not _matches_any(ref, boundary["allowed"]):
                    offenders.append(f"{file.name}: {ref!r}")
    assert not offenders, f"{boundary['name']} reaches beyond allowed modules:\n" + "\n".join(offenders)
