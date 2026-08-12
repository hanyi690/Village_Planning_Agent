import pathlib


def test_no_dead_api_files_imported():
    root = pathlib.Path("app")
    text_checks = ["api.human_review_routes", "api.schemas"]
    offenders = [
        str(p) for p in root.rglob("*.py")
        if any(t in p.read_text(encoding="utf-8") for t in text_checks)
    ]
    assert not offenders, f"dead api files still referenced: {offenders}"


def test_flat_v1_routes_deleted():
    assert not pathlib.Path("app/api/v1/routes.py").exists()
