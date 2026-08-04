from app.services.review_package import write_review_package, read_review_package, query_reviews
from app.modules.schema.contracts.review_contracts import ReviewPackage, ReviewStatus


def test_write_and_read(tmp_path):
    pkg = ReviewPackage(run_id="r1", module="l1_observe", summary_md="# L1",
                        artifact_json={"id": "l1-1"}, trace_json={"steps": []},
                        preview_geojson={"type": "FeatureCollection", "features": []})
    write_review_package(pkg, base_dir=str(tmp_path))
    read = read_review_package("r1", "l1_observe", base_dir=str(tmp_path))
    assert read.summary_md == "# L1"
    assert read.status == ReviewStatus.AWAITING_REVIEW
    assert read.preview_geojson is not None


def test_query_by_run(tmp_path):
    for mod in ["l1_observe", "explore"]:
        pkg = ReviewPackage(run_id="r1", module=mod, summary_md="", artifact_json={}, trace_json={})
        write_review_package(pkg, base_dir=str(tmp_path))
    assert len(query_reviews(run_id="r1", base_dir=str(tmp_path))) == 2


def test_query_by_module(tmp_path):
    for rid in ["r1", "r2"]:
        pkg = ReviewPackage(run_id=rid, module="explore", summary_md="", artifact_json={}, trace_json={})
        write_review_package(pkg, base_dir=str(tmp_path))
    assert len(query_reviews(module="explore", base_dir=str(tmp_path))) == 2
