import pathlib


def test_no_modules_context_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "modules.context" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.modules.context still referenced: {offenders}"


def test_planning_context_lives_in_infrastructure():
    from app.infrastructure.context.planning_context import PlanningContext
    assert hasattr(PlanningContext, "current_parcels")
