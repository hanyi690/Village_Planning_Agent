import pathlib
import re


def test_no_production_import_of_app_agent():
    root = pathlib.Path("app")
    banned = re.compile(r"(?:from|import) app\.agent\b")
    offenders = [
        p for p in root.rglob("*.py")
        if "tests" not in str(p)
        and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"production still imports app.agent: {offenders}"
