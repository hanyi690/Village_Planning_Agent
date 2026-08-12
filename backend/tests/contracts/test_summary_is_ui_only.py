import pathlib


def test_summary_not_read_as_authoritative_input():
    root = pathlib.Path("app")
    text_checks = ["get_layer_summaries", "services.report_store", "report_summary_index.update"]
    # report_store.py legitimately keeps get_layer_summaries as its public read
    # API; the check targets authoritative READ call sites elsewhere in app/.
    excluded = {
        pathlib.Path("app/infrastructure/reports/report_store.py"),
    }
    offenders = [
        str(p) for p in root.rglob("*.py")
        if p not in excluded and any(t in p.read_text(encoding="utf-8") for t in text_checks)
    ]
    assert not offenders, f"summary still read as input or stale services.report_store ref: {offenders}"
