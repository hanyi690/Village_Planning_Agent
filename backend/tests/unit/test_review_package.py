import pytest

from app.modules.schema.contracts.review_contracts import (
    ArtifactRefLite,
    ReviewDecision,
    ReviewPackage,
    ReviewStatus,
)
from app.services.review_package import (
    query_reviews,
    read_review_package,
    record_review_decision,
    write_review_package,
)


def _pkg(run_id="r1", module="l1_observe", review_id="rev-1", rev=1, status=ReviewStatus.AWAITING_REVIEW):
    return ReviewPackage(
        review_id=review_id,
        revision=rev,
        run_id=run_id,
        module=module,
        summary_md="# L1",
        artifact_ref=ArtifactRefLite(artifact_id="l1-001", module=module, run_id=run_id),
        trace_json={"steps": []},
        preview_geojson={"type": "FeatureCollection", "features": []},
        status=status,
    )


def test_write_and_read(tmp_path):
    rid = write_review_package(_pkg(), base_dir=str(tmp_path))
    read = read_review_package("r1", "l1_observe", rid, base_dir=str(tmp_path))
    assert read.summary_md == "# L1"
    assert read.status == ReviewStatus.AWAITING_REVIEW
    assert read.preview_geojson is not None
    assert read.artifact_ref is not None
    assert read.artifact_ref.artifact_id == "l1-001"


def test_status_persisted_not_reset(tmp_path):
    """Reading must NOT reset a non-awaiting status."""
    rid = write_review_package(_pkg(status=ReviewStatus.APPROVED), base_dir=str(tmp_path))
    read = read_review_package("r1", "l1_observe", rid, base_dir=str(tmp_path))
    assert read.status == ReviewStatus.APPROVED


def test_decision_persisted_and_gate_linked(tmp_path):
    """record_review_decision persists decision and updates status."""
    rid = write_review_package(_pkg(), base_dir=str(tmp_path))
    decision = ReviewDecision(request_id="req-1", decision="approved", comments="ok", decided_by="reviewer")
    updated = record_review_decision("r1", "l1_observe", rid, decision, base_dir=str(tmp_path))
    assert updated.status == ReviewStatus.APPROVED
    assert updated.decision is not None
    assert updated.decision.decision == "approved"
    # re-read still has the decision
    reread = read_review_package("r1", "l1_observe", rid, base_dir=str(tmp_path))
    assert reread.status == ReviewStatus.APPROVED
    assert reread.decision.decided_by == "reviewer"


def test_revision_isolated(tmp_path):
    """Same review_id at different revisions do not clobber each other."""
    rid = write_review_package(_pkg(rev=1, review_id="rev-1"), base_dir=str(tmp_path))
    write_review_package(_pkg(rev=2, review_id="rev-1"), base_dir=str(tmp_path))
    # read always returns the latest written manifest
    read = read_review_package("r1", "l1_observe", rid, base_dir=str(tmp_path))
    assert read.revision == 2


def test_query_by_run(tmp_path):
    for mod in ["l1_observe", "explore"]:
        write_review_package(_pkg(run_id="r1", module=mod, review_id=f"rev-{mod}"), base_dir=str(tmp_path))
    assert len(query_reviews(run_id="r1", base_dir=str(tmp_path))) == 2


def test_query_by_module(tmp_path):
    for rid in ["r1", "r2"]:
        write_review_package(_pkg(run_id=rid, module="explore", review_id="rev-x"), base_dir=str(tmp_path))
    assert len(query_reviews(module="explore", base_dir=str(tmp_path))) == 2


def test_artifact_and_review_dirs_not_polluted(tmp_path):
    """query_reviews must only return reviews/ dirs, not artifacts/."""
    from app.modules.ports.artifact_store import ArtifactRef
    from app.services.artifact_store import FilesystemArtifactStore

    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    store.store(ArtifactRef(context_version="cv", artifact_id="l1-001", module="l1_observe", run_id="r1"), {})
    write_review_package(_pkg(), base_dir=str(tmp_path))
    pkgs = query_reviews(run_id="r1", base_dir=str(tmp_path))
    assert len(pkgs) == 1
    assert pkgs[0].review_id == "rev-1"


def test_path_boundary_rejects_traversal(tmp_path):
    with pytest.raises(ValueError):
        write_review_package(_pkg(run_id="..", review_id="x"), base_dir=str(tmp_path))
    with pytest.raises(ValueError):
        write_review_package(_pkg(run_id="r1", review_id="../x"), base_dir=str(tmp_path))
