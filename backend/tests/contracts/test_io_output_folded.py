import pathlib


def test_no_spatial_ops_io_or_output_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "spatial_ops.io" in p.read_text(encoding="utf-8")
        or "spatial_ops.output" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"spatial_ops io/output still referenced: {offenders}"
