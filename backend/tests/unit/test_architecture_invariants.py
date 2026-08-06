"""Architecture invariant tests - parameterized reverse-dependency scanner.

Replaces 9+ duplicated static-analysis tests across 4 files:
- test_kg_no_reverse_deps.py (4 reverse-dep tests)
- test_schema_promotion.py (2 reverse-dep tests)
- test_execution_contracts.py (2 reverse-dep tests)
- test_kg_jintian_e2e.py Part 8 TestKGStaticStructure (3 reverse-dep tests)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]


# ── Parameterized reverse-dependency scanner ─────────────────────────

REVERSE_DEP_CHECKS = [
    # (directory_relative_to_backend, forbidden_import_patterns, description)
    # KG must not import from tools/agent/services or shapely/geopandas
    ("app/modules/kg",
     [r"^\s*from app\.(tools|agent)",
      r"^\s*(from|import)\s+.*(shapely|geopandas)",
      r"^\s*from app\.modules\.data"],
     "KG must not import from tools/agent/data or shapely/geopandas"),
    # KG builder subpackage (stricter: also blocks shapely explicitly)
    ("app/modules/kg/builder",
     [r"^\s*from app\.(tools|agent)",
      r"^\s*(from|import)\s+shapely",
      r"^\s*from shapely",
      r"^\s*from app\.modules\.data"],
     "KG builder must not import shapely or higher layers"),
    # Schema must not import from tools/agent/kg/spatial_ops
    ("app/modules/schema",
     [r"^\s*from app\.(tools|agent)",
      r"^\s*from app\.modules\.(kg|spatial_ops)"],
     "Schema must not import from kg/spatial_ops/tools/agent"),
    # Spatial ops must not import from tools/agent/kg
    ("app/modules/spatial_ops",
     [r"^\s*from app\.(tools|agent)",
      r"^\s*from app\.modules\.kg"],
     "Spatial ops must not import from tools/agent/kg"),
    # Data layer must not import from tools/agent
    ("app/modules/data",
     [r"^\s*from app\.(tools|agent)"],
     "Data must not import from tools/agent"),
]


@pytest.mark.parametrize("dir_rel,patterns,desc", REVERSE_DEP_CHECKS)
def test_no_reverse_dependencies(dir_rel, patterns, desc):
    """No module in {dir} imports from forbidden higher layers."""
    target_dir = BACKEND_ROOT / dir_rel
    if not target_dir.exists():
        pytest.skip(f"Directory not found: {target_dir}")

    compiled = [re.compile(p) for p in patterns]
    offenders = []
    for py_file in target_dir.rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for pat in compiled:
                if pat.match(line):
                    offenders.append(
                        f"{py_file.relative_to(BACKEND_ROOT)}:{line_num}: {stripped}"
                    )
    assert not offenders, f"{desc}:\n" + "\n".join(offenders)


# ── KG builder file structure invariant ──────────────────────────────


def test_no_top_level_contracts_barrel_imports():
    """No app code imports from the contracts barrel (top-level wildcard).

    All business code must import from a specific contract file, e.g.
    ``from app.modules.schema.contracts.l1_contracts import L1Snapshot``.
    """
    pattern = re.compile(r"^\s*from app\.modules\.schema\.contracts\s+import\b")
    offenders = []
    for py_file in (BACKEND_ROOT / "app").rglob("*.py"):
        if "__pycache__" in str(py_file):
            continue
        content = py_file.read_text(encoding="utf-8")
        for line_num, line in enumerate(content.splitlines(), 1):
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if pattern.match(line):
                offenders.append(
                    f"{py_file.relative_to(BACKEND_ROOT)}:{line_num}: {stripped}"
                )
    assert not offenders, (
        "Contracts barrel (top-level wildcard) imports forbidden:\n"
        + "\n".join(offenders)
    )


def test_kg_builder_subpackage_has_expected_files():
    """builder/ subpackage has the expected files for v5 composition architecture."""
    builder_dir = BACKEND_ROOT / "app" / "modules" / "kg" / "builder"
    expected = {
        "__init__.py", "base.py", "builder.py", "enrichment.py",
        "geo_helpers.py", "layer1_core.py", "layer1_extended.py",
        "layer2.py", "layer3.py", "layer4.py", "registry.py",
    }
    actual = {f.name for f in builder_dir.glob("*.py")}
    assert expected.issubset(actual), f"Missing: {expected - actual}"


def test_kg_builder_uses_schema_imports():
    """KG builder core file uses schema imports (not raw dict reverse-deps)."""
    path = BACKEND_ROOT / "app" / "modules" / "kg" / "builder" / "layer1_core.py"
    content = path.read_text(encoding="utf-8")
    assert "from app.modules.schema.types.spatial_types import" in content


# ── Metrics is pure (no geopandas/shapely/tools/agent) ───────────────


def test_metrics_module_pure():
    """compute_land_use_metrics module must not import geopandas/shapely/tools/agent."""
    metrics_path = BACKEND_ROOT / "app" / "modules" / "schema" / "utils" / "metrics.py"
    if not metrics_path.exists():
        pytest.skip(f"metrics.py not found: {metrics_path}")
    pattern = re.compile(r"^\s*(from|import)\s+.*(geopandas|shapely|app\.tools|app\.agent)")
    violations = []
    with open(metrics_path, "r", encoding="utf-8") as f:
        for lineno, line in enumerate(f, 1):
            if pattern.match(line):
                violations.append(f"Line {lineno}: {line.strip()}")
    assert violations == [], f"schema/metrics.py has forbidden imports:\n" + "\n".join(violations)
