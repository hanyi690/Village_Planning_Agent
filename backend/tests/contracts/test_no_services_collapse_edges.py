import pathlib
import re


def test_workflow_and_domain_do_not_import_services():
    root = pathlib.Path("app")
    banned = re.compile(
        r"(?:from|import) app\.services\b"
    )
    offenders = [
        p for p in root.rglob("*.py")
        if ("/workflow/" in p.as_posix() or "/domain/" in p.as_posix())
        and banned.search(p.read_text(encoding="utf-8"))
    ]
    assert not offenders, f"workflow/domain must not import app.services: {offenders}"
