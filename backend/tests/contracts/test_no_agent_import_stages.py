import pathlib
import re


def test_no_production_import_of_agent_stage_packages():
    root = pathlib.Path("app")
    banned = re.compile(
        r"(?:from|import) app\.agent\.(?:l1_observe|l2_strategize|l3_plan|explore|conversation_router|tools)\b"
    )
    offenders = [
        p for p in root.rglob("*.py")
        if "tests" not in str(p)
        and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"stage packages still import app.agent.*: {offenders}"
