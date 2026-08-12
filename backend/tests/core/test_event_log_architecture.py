from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "app"


def test_public_event_queries_use_durable_repository_boundary() -> None:
    routes = (ROOT / "api" / "v1" / "routes.py").read_text(encoding="utf-8")
    runtime = (ROOT / "services" / "runtime.py").read_text(encoding="utf-8")

    assert "run_event_queries" in routes
    assert "EventRepository" not in routes
    assert "await sse_manager.alist_events" not in routes
    assert "await sse_manager.alist_events" not in runtime
    assert "get_events_from_seq" not in routes
    assert "get_last_seq" not in routes


def test_event_repository_is_the_only_sequence_allocator() -> None:
    app_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for directory in (ROOT / "api", ROOT / "services", ROOT / "utils")
        for path in directory.rglob("*.py")
    )

    assert "get_next_seq(" not in app_sources
