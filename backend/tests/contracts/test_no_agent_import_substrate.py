import pathlib
import re


def test_no_production_import_of_agent_substrate():
    root = pathlib.Path("app")
    banned = re.compile(
        r"(?:from|import) app\.agent\.(?:bootstrap|common|plan_state)\b"
    )
    offenders = [
        p for p in root.rglob("*.py")
        if "tests" not in str(p)
        and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"substrate still imports app.agent.*: {offenders}"
