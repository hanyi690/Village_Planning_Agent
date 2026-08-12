import pathlib


def test_no_modules_schema_contracts_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "app.modules.schema.contracts" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.modules.schema.contracts still referenced: {offenders}"
