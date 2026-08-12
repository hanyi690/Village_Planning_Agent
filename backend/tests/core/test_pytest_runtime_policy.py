from pathlib import Path


def test_slow_real_acceptance_is_not_cut_off_by_global_session_timeout():
    """Slow scope owns its timeout through pytest.mark.timeout, not a global cap."""

    root_ini = Path(__file__).resolve().parents[3] / "pytest.ini"
    backend_ini = Path(__file__).resolve().parents[2] / "pytest.ini"
    for path in (root_ini, backend_ini):
        assert "session_timeout" not in path.read_text(encoding="utf-8")
