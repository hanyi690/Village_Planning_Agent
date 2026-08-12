import pathlib


def test_no_modules_spatial_ops_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "modules.spatial_ops" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.modules.spatial_ops still referenced: {offenders}"
