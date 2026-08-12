import pathlib
import re


def test_no_module_level_domain_import_from_modules():
    root = pathlib.Path("app/modules")
    banned = re.compile(r"^from app\.domain\b|^import app\.domain\b")
    offenders = []
    for p in root.rglob("*.py"):
        for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if banned.match(line):
                offenders.append((str(p), i, line.strip()))
    assert not offenders, f"app/modules must not import app.domain at module level: {offenders}"
