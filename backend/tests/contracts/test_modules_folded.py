import pathlib


def test_no_modules_schema_or_modules_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "app.modules." in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.modules still referenced: {offenders}"
