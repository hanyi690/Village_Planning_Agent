import pathlib


def test_no_app_tools_reference():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "app.tools" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.tools still referenced: {offenders}"
