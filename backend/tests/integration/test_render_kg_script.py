"""Test that the render_kg_inspection script runs without error and produces outputs.

Runs the script via subprocess in a tmp_path to avoid polluting the repo.
Asserts the always-available outputs (kg_full.ttl, kg_stats.json, kg_layers.html)
are produced and non-empty. The Graphviz SVG is optional (only emitted when
the `dot` executable is on PATH), so it is not asserted here.

Usage:
    cd F:/project/Village_Planning_Agent
    python -m pytest backend/tests/integration/test_render_kg_script.py -v --tb=short

    Or directly:
    cd backend
    python -m pytest tests/integration/test_render_kg_script.py -v --tb=short
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest


def test_render_kg_script_produces_all_outputs(tmp_path):
    """The render script should produce all non-optional output files."""
    backend = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [sys.executable, "scripts/render_kg_inspection.py",
         "--output-dir", str(tmp_path)],
        capture_output=True, text=True, cwd=str(backend),
        timeout=180,
    )
    assert result.returncode == 0, (
        f"Script failed (rc={result.returncode}):\n"
        f"--- stdout ---\n{result.stdout}\n"
        f"--- stderr ---\n{result.stderr}"
    )

    # Always-available outputs (SVG requires the `dot` executable)
    required = ["kg_full.ttl", "kg_stats.json", "kg_inspection.html"]
    for fname in required:
        out = tmp_path / fname
        assert out.exists(), f"Missing {fname}\nstdout:\n{result.stdout}"
        assert out.stat().st_size > 0, f"Empty {fname}\nstdout:\n{result.stdout}"

    # kg_stats.json must be valid JSON with the expected keys
    import json
    stats = json.loads((tmp_path / "kg_stats.json").read_text(encoding="utf-8"))
    assert stats["village_name"] == "jintian"
    assert stats["triple_count"] > 0, "triple_count should be positive"
    assert stats["parcel_count"] > 0, "parcel_count should be positive"
    assert "entity_breakdown" in stats
    assert "relation_breakdown" in stats

    # The Turtle file should contain the pln namespace prefix
    ttl = (tmp_path / "kg_full.ttl").read_text(encoding="utf-8")
    assert "@prefix pln:" in ttl, "Turtle output missing pln prefix"

    # The HTML should reference deck.gl / MapLibre and embed layer data
    html = (tmp_path / "kg_inspection.html").read_text(encoding="utf-8")
    assert "deck" in html.lower(), "HTML missing deck.gl reference"
    assert "maplibre" in html.lower() or "mapbox" in html.lower(), "HTML missing map library reference"
    assert len(html) > 100_000, "HTML lacks embedded layer data"
