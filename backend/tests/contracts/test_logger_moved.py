import pathlib


def test_no_app_utils_logger_import():
    root = pathlib.Path("app")
    offenders = [
        str(p) for p in root.rglob("*.py")
        if "app.utils.logger" in p.read_text(encoding="utf-8")
        or "app.utils" in p.read_text(encoding="utf-8")
    ]
    assert not offenders, f"app.utils still referenced: {offenders}"


def test_logger_lives_in_infrastructure():
    from app.infrastructure.logging import get_logger
    assert callable(get_logger)
