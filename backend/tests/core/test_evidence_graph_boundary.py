from pathlib import Path


def test_ground_production_modules_have_no_place_index_dependency() -> None:
    """The graph is the only evidence boundary visible to GROUND."""
    app_root = Path(__file__).resolve().parents[2] / "app"
    files = (
        app_root / "domain" / "ground" / "aggregate.py",
        app_root / "spatial" / "grounding" / "grounding.py",
        app_root / "spatial" / "grounding" / "resolver.py",
        app_root / "infrastructure" / "context" / "planning_context.py",
    )
    violations = {
        str(path.relative_to(app_root)): "evidence_index"
        for path in files
        if "evidence_index" in path.read_text(encoding="utf-8")
    }
    assert not violations, violations
