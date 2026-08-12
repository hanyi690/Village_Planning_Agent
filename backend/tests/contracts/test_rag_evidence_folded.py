import pathlib


def test_no_modules_rag_or_evidence_import():
    root = pathlib.Path("app")
    text_checks = ["app.modules.rag", "app.modules.evidence"]
    offenders = [
        str(p) for p in root.rglob("*.py")
        if any(t in p.read_text(encoding="utf-8") for t in text_checks)
    ]
    assert not offenders, f"modules rag/evidence still referenced: {offenders}"
