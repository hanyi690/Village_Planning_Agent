"""
Review package serialization - write/read/query review packages on disk.

Layout (per review: reviews are separated from artifacts under one run):
    {base_dir}/{run_id}/reviews/{module}/{review_id}/manifest.json
    {base_dir}/{run_id}/reviews/{module}/{review_id}/summary.md
    {base_dir}/{run_id}/reviews/{module}/{review_id}/trace.json
    {base_dir}/{run_id}/reviews/{module}/{review_id}/preview.geojson   (optional)
    {base_dir}/{run_id}/reviews/{module}/{review_id}/before_after.geojson (optional)
    {base_dir}/{run_id}/reviews/{module}/{review_id}/decision.json     (optional)

- ``manifest.json`` persists review_id, revision, run_id, module, status,
  created_at/updated_at and the artifact_ref (a lightweight ArtifactRefLite,
  NOT the embedded payload).
- ``status`` and ``decision`` are persisted and round-tripped (no reset to
  awaiting_review on read).
- Writes are atomic (temp file -> rename).
- Path identifiers constrained to ``[A-Za-z0-9._-]``.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.modules.schema.contracts.review_contracts import (
    ArtifactRefLite,
    ReviewDecision,
    ReviewPackage,
    ReviewStatus,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_MANIFEST = "manifest.json"
_SUMMARY = "summary.md"
_TRACE = "trace.json"
_PREVIEW = "preview.geojson"
_BEFORE_AFTER = "before_after.geojson"
_DECISION = "decision.json"


def _validate_id(value: str, label: str) -> str:
    # must start with an alnum char and contain only safe chars -> no "..",
    # no leading ".", no empty, no "/" or "\".
    if not value or not _SAFE_ID.match(value) or ".." in value:
        raise ValueError(f"unsafe {label} identifier: {value!r}")
    return value


def _atomic_write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data: Any) -> None:
    _atomic_write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pkg_dir(base: Path, run_id: str, module: str, review_id: str) -> Path:
    _validate_id(run_id, "run_id")
    _validate_id(module, "module")
    _validate_id(review_id, "review_id")
    return base / run_id / "reviews" / module / review_id


def _ensure_review_id(pkg: ReviewPackage) -> str:
    rid = pkg.review_id or pkg.artifact_ref.artifact_id if pkg.artifact_ref else ""
    if not rid:
        rid = f"{pkg.module}-{pkg.revision}"
    return _validate_id(rid, "review_id")


def write_review_package(pkg: ReviewPackage, base_dir: str | Path = ".run-tmp") -> str:
    """Persist a review package. Returns the review_id used (auto-generated if blank)."""
    base = Path(base_dir)
    review_id = _ensure_review_id(pkg)
    d = _pkg_dir(base, pkg.run_id, pkg.module, review_id)
    d.mkdir(parents=True, exist_ok=True)

    manifest = {
        "review_id": review_id,
        "revision": pkg.revision,
        "run_id": pkg.run_id,
        "module": pkg.module,
        "status": pkg.status.value,
        "artifact_ref": pkg.artifact_ref.model_dump() if pkg.artifact_ref else None,
        "created_at": pkg.created_at.isoformat(),
        "updated_at": pkg.updated_at.isoformat(),
    }
    _atomic_write_json(d / _MANIFEST, manifest)
    _atomic_write_text(d / _SUMMARY, pkg.summary_md)
    _atomic_write_json(d / _TRACE, pkg.trace_json)
    if pkg.preview_geojson is not None:
        _atomic_write_json(d / _PREVIEW, pkg.preview_geojson)
    if pkg.before_after_geojson is not None:
        _atomic_write_json(d / _BEFORE_AFTER, pkg.before_after_geojson)
    if pkg.decision is not None:
        _atomic_write_json(d / _DECISION, pkg.decision.model_dump())
    logger.debug("[ReviewPackage] Wrote %s/%s/%s@%d", pkg.run_id, pkg.module, review_id, pkg.revision)
    return review_id


def read_review_package(
    run_id: str, module: str, review_id: str, base_dir: str | Path = ".run-tmp"
) -> ReviewPackage:
    d = _pkg_dir(Path(base_dir), run_id, module, review_id)
    manifest_file = d / _MANIFEST
    if not manifest_file.exists():
        raise FileNotFoundError(f"review package manifest missing: {manifest_file}")

    manifest = _read_json(manifest_file) or {}
    artifact_ref = None
    if manifest.get("artifact_ref"):
        artifact_ref = ArtifactRefLite(**manifest["artifact_ref"])
    decision = None
    if (d / _DECISION).exists():
        decision = ReviewDecision(**_read_json(d / _DECISION))
    status = ReviewStatus(manifest.get("status", "awaiting_review"))

    return ReviewPackage(
        review_id=review_id,
        revision=int(manifest.get("revision", 1)),
        run_id=run_id,
        module=module,
        summary_md=(d / _SUMMARY).read_text(encoding="utf-8") if (d / _SUMMARY).exists() else "",
        artifact_ref=artifact_ref,
        trace_json=_read_json(d / _TRACE) or {},
        preview_geojson=_read_json(d / _PREVIEW),
        before_after_geojson=_read_json(d / _BEFORE_AFTER),
        status=status,
        decision=decision,
    )


def record_review_decision(
    run_id: str,
    module: str,
    review_id: str,
    decision: ReviewDecision,
    base_dir: str | Path = ".run-tmp",
) -> ReviewPackage:
    """Persist a decision and return the updated package (status derived from decision)."""
    d = _pkg_dir(Path(base_dir), run_id, module, review_id)
    _atomic_write_json(d / _DECISION, decision.model_dump())
    status = {
        "approved": ReviewStatus.APPROVED,
        "rejected": ReviewStatus.CHANGES_REQUESTED,
        "changes_requested": ReviewStatus.CHANGES_REQUESTED,
    }.get(decision.decision, ReviewStatus.AWAITING_REVIEW)
    manifest_file = d / _MANIFEST
    if manifest_file.exists():
        manifest = _read_json(manifest_file) or {}
        manifest["status"] = status.value
        manifest["updated_at"] = _now().isoformat()
        _atomic_write_json(manifest_file, manifest)
    return read_review_package(run_id, module, review_id, base_dir=base_dir)


def query_reviews(
    run_id: str | None = None,
    module: str | None = None,
    base_dir: str | Path = ".run-tmp",
) -> list[ReviewPackage]:
    base = Path(base_dir)
    if run_id is not None:
        run_dirs = [base / run_id]
    elif base.exists():
        run_dirs = [d for d in sorted(base.iterdir()) if d.is_dir()]
    else:
        run_dirs = []
    packages: list[ReviewPackage] = []
    for run_dir in run_dirs:
        if not run_dir.exists():
            continue
        reviews_root = run_dir / "reviews"
        if not reviews_root.exists():
            continue
        for module_dir in sorted(reviews_root.iterdir()):
            if not module_dir.is_dir():
                continue
            if module is not None and module_dir.name != module:
                continue
            for review_dir in sorted(module_dir.iterdir()):
                if not review_dir.is_dir():
                    continue
                if not (review_dir / _MANIFEST).exists():
                    continue
                try:
                    packages.append(
                        read_review_package(run_dir.name, module_dir.name, review_dir.name, base_dir=base)
                    )
                except FileNotFoundError:
                    continue
    return packages


def _read_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        with path.open("r", encoding="utf-8") as fh:
            return json.load(fh)
    except json.JSONDecodeError:
        logger.warning("[ReviewPackage] Invalid JSON at %s", path)
        return None


__all__ = [
    "write_review_package",
    "read_review_package",
    "query_reviews",
    "record_review_decision",
]
