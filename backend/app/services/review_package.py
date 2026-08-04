"""
Review package serialization - write/read/query review packages on disk.

Layout: {base_dir}/{run_id}/{module}/ containing summary.md, artifact.json,
trace.json and optional preview.geojson / before_after.geojson.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from app.modules.schema.contracts.review_contracts import ReviewPackage, ReviewStatus
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SUMMARY_FILE = "summary.md"
_ARTIFACT_FILE = "artifact.json"
_TRACE_FILE = "trace.json"
_PREVIEW_FILE = "preview.geojson"
_BEFORE_AFTER_FILE = "before_after.geojson"


def write_review_package(pkg: ReviewPackage, base_dir: str | Path = ".run-tmp") -> None:
    pkg_dir = Path(base_dir) / pkg.run_id / pkg.module
    pkg_dir.mkdir(parents=True, exist_ok=True)
    (pkg_dir / _SUMMARY_FILE).write_text(pkg.summary_md, encoding="utf-8")
    (pkg_dir / _ARTIFACT_FILE).write_text(
        json.dumps(pkg.artifact_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (pkg_dir / _TRACE_FILE).write_text(
        json.dumps(pkg.trace_json, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if pkg.preview_geojson is not None:
        (pkg_dir / _PREVIEW_FILE).write_text(
            json.dumps(pkg.preview_geojson, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    if pkg.before_after_geojson is not None:
        (pkg_dir / _BEFORE_AFTER_FILE).write_text(
            json.dumps(pkg.before_after_geojson, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    logger.debug("[ReviewPackage] Wrote %s/%s", pkg.run_id, pkg.module)


def read_review_package(
    run_id: str, module: str, base_dir: str | Path = ".run-tmp"
) -> ReviewPackage:
    pkg_dir = Path(base_dir) / run_id / module
    summary_file = pkg_dir / _SUMMARY_FILE
    if not summary_file.exists():
        raise FileNotFoundError(f"review package summary missing: {summary_file}")
    return ReviewPackage(
        run_id=run_id,
        module=module,
        summary_md=summary_file.read_text(encoding="utf-8"),
        artifact_json=_read_json(pkg_dir / _ARTIFACT_FILE) or {},
        trace_json=_read_json(pkg_dir / _TRACE_FILE) or {},
        preview_geojson=_read_json(pkg_dir / _PREVIEW_FILE),
        before_after_geojson=_read_json(pkg_dir / _BEFORE_AFTER_FILE),
        status=ReviewStatus.AWAITING_REVIEW,
    )


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
        for pkg_dir in sorted(run_dir.iterdir()):
            if not pkg_dir.is_dir():
                continue
            if module is not None and pkg_dir.name != module:
                continue
            if not (pkg_dir / _SUMMARY_FILE).exists():
                continue
            try:
                packages.append(read_review_package(run_dir.name, pkg_dir.name, base_dir=base))
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


__all__ = ["write_review_package", "read_review_package", "query_reviews"]
