import pathlib


def test_no_utils_leaf_modules_referenced():
    root = pathlib.Path("app")
    moved = ["app.utils.geo_utils", "app.utils.geojson_utils", "app.utils.coord_transform",
             "app.utils.crs_engine", "app.utils.area_engine", "app.utils.code_lookup",
             "app.utils.document_loader", "app.utils.docling_loader", "app.utils.mineru_loader",
             "app.utils.pdf_fallback", "app.utils.location_parser", "app.utils.rate_limiter",
             "app.utils.retry", "app.utils.stats_collector", "app.utils.sse_events",
             "app.utils.sse_publisher", "app.utils.event_factory"]
    offenders = [
        str(p) for p in root.rglob("*.py")
        if any(m in p.read_text(encoding="utf-8") for m in moved)
    ]
    assert not offenders, f"moved utils modules still referenced: {offenders}"
