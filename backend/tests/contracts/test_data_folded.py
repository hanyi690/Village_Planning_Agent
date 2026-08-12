import pathlib


def test_no_modules_data_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "app.modules.data" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.modules.data still referenced: {offenders}"
