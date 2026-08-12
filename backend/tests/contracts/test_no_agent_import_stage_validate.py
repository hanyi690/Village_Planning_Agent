import pathlib
import re


def test_stage_validate_production_modules_have_no_app_agent_dependency():
    root = pathlib.Path("app")
    banned = re.compile(r"from app\.agent\.validate\b|import app\.agent\.validate\b")
    offenders = [
        p for p in root.rglob("*.py")
        if "tests" not in str(p)
        and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"stage validate still imports app.agent.validate: {offenders}"
