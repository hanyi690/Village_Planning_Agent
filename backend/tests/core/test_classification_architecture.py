"""Prevent advisory classification mappings from re-entering execution paths."""

from __future__ import annotations

import ast
from pathlib import Path


APP = Path(__file__).resolve().parents[2] / "app"
RUNTIME_ROOTS = (
    APP / "agent",
    APP / "infrastructure/rendering",
    APP / "infrastructure/export",
    APP / "modules/kg",
)
FORBIDDEN = (
    "dlbm_to_ghytbm",
    "gbt21010_to_planning_zones",
    "gbt21010_to_three_categories",
    "gbt21010_to_zone_types_appendix5",
)


def test_runtime_paths_do_not_import_or_name_advisory_classification_maps() -> None:
    violations: list[str] = []
    for root in RUNTIME_ROOTS:
        for path in root.rglob("*.py"):
            source = path.read_text(encoding="utf-8-sig").lower()
            tree = ast.parse(source, filename=str(path))
            imports = {
                node.module
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom) and node.module
            }
            if any(name.startswith("app.modules.schema.advisory_crosswalks") for name in imports):
                violations.append(f"{path.relative_to(APP)}: advisory crosswalk import")
            for token in FORBIDDEN:
                if token.lower() in source:
                    violations.append(f"{path.relative_to(APP)}: {token}")

    assert not violations, "\n".join(violations)
