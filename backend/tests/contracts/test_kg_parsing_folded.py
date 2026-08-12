import pathlib


def test_no_modules_kg_or_parsing_import():
    root = pathlib.Path("app")
    text_checks = ["app.modules.kg", "app.modules.parsing"]
    offenders = [
        str(p) for p in root.rglob("*.py")
        if any(t in p.read_text(encoding="utf-8") for t in text_checks)
    ]
    assert not offenders, f"modules kg/parsing still referenced: {offenders}"
