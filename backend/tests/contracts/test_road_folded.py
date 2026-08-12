import pathlib


def test_no_spatial_ops_road_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "spatial_ops.road" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"spatial_ops.road still referenced: {offenders}"
