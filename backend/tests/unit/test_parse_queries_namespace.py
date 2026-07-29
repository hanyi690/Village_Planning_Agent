"""Verify parse_queries namespace exposes resolve_candidates and get_parcels_near_point."""
from app.modules.kg.queries import parse_queries


def test_resolve_candidates_in_parse_queries():
    entry = parse_queries.get("resolve_candidates")
    assert entry is not None, "resolve_candidates must be in parse_queries"
    assert callable(entry["func"]), "func must be callable"
    assert entry["writes_kg"] is False
    assert entry.get("status") == "available"


def test_get_parcels_near_point_in_parse_queries():
    entry = parse_queries.get("get_parcels_near_point")
    assert entry is not None, "get_parcels_near_point must be in parse_queries"
    assert callable(entry["func"])
    assert entry.get("status") == "available"


def test_execute_queries_status_not_reserved_for_wired():
    from app.modules.kg.queries import execute_queries
    for name, entry in execute_queries.items():
        status = entry.get("status", "")
        assert status in ("available", "exists_not_wired", "reserved", "wired"), \
            f"{name} has invalid status: {status}"