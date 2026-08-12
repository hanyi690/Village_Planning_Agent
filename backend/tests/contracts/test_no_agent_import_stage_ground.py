import pathlib
import re


def test_stage_ground_production_modules_have_no_app_agent_dependency():
    root = pathlib.Path("app")
    banned = re.compile(r"from app\.agent\.ground\b|import app\.agent\.ground\b")
    offenders = [
        p for p in root.rglob("*.py")
        if "tests" not in str(p)
        and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"stage ground still imports app.agent.ground: {offenders}"
