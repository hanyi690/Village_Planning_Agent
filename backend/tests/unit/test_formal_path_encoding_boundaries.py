"""Static guardrails for the formal planning execution path."""

import ast
from pathlib import Path


FORMAL_DIRS = ("parse", "ground", "select", "execute", "deliver", "validate", "reconcile")
FORBIDDEN_MODULES = {
    "app.modules.schema.advisory_crosswalks",
    "app.modules.data.base_conversion",
}
FORBIDDEN_NAMES = {"DLBM_TO_GHYTBM", "GHYTBM_TO_VNE"}


def test_formal_agent_path_has_no_cross_system_inference_imports():
    root = Path(__file__).parents[2] / "app" / "agent"
    violations = []
    for dirname in FORMAL_DIRS:
        directory = root / dirname
        for path in directory.rglob("*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module in FORBIDDEN_MODULES:
                    violations.append(f"{path}: import {node.module}")
                elif isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in FORBIDDEN_MODULES:
                            violations.append(f"{path}: import {alias.name}")
                elif isinstance(node, ast.Name) and node.id in FORBIDDEN_NAMES:
                    violations.append(f"{path}: symbol {node.id}")
    assert not violations, "formal path contains forbidden cross-system inference: " + "; ".join(violations)
