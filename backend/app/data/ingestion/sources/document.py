"""Document file driver - MinerU Markdown only.

Loads the canonical Markdown artifact produced by MinerU from local disk.
Frontend PDF/Office/image uploads are converted before reaching DATA;
non-GIS binary formats are intentionally rejected here.

Unlike vector/raster drivers, documents have no geometry - bbox is
always ignored. The driver returns raw Markdown for downstream
parse/consumption.
"""

from __future__ import annotations

import glob
from pathlib import Path
from typing import Any, Optional

from app.contracts.data.geometry_contracts import BBox
from app.infrastructure.logging import get_logger

from ..contracts import DataResult, DataSourceMetadata
from .base import DataSourceDriver
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("document")
class DocumentDriver(DataSourceDriver):
    """Document file driver.

    Supports Markdown (.md/.markdown) only.

    Config keys:
        path: str          # file path or glob pattern
        doc_type: str      # "planning_markdown" | "l3_report" | "text"
        encoding: str      # accepted for legacy config; input is always UTF-8
        layer_type: str    # semantic layer type
    """

    driver_type = "document"

    def __init__(self, config: dict[str, Any]):
        self.path = Path(config["path"])
        self.doc_type = config.get("doc_type", "text")
        self.layer_type = config.get("layer_type", "")

    def fetch(self, bbox: Optional[BBox] = None, **kwargs: Any) -> DataResult:
        """Load a MinerU Markdown artifact.

        Args:
            bbox: Ignored (documents have no geometry).
            **kwargs: Unused.

        Returns:
            DataResult with data_type="document" and Markdown text.
        """
        resolved = self._resolve_path()
        if resolved is None:
            return DataResult.fail(
                error=f"No file matching pattern: {self.path}"
            )

        if not resolved.exists():
            return DataResult.fail(error=f"File not found: {resolved}")

        if resolved.suffix.casefold() not in {".md", ".markdown"}:
            return DataResult.fail(
                error="DATA document sources must be MinerU Markdown (.md/.markdown)"
            )

        try:
            return self._load_text(resolved)
        except Exception as e:
            logger.error("[DocumentDriver] Failed to load %s: %s", resolved, e)
            return DataResult.fail(error=str(e))

    def _resolve_path(self) -> Optional[Path]:
        """Resolve glob pattern to first match, or return literal path."""
        path_str = str(self.path)
        if any(c in path_str for c in "*?["):
            matches = sorted(glob.glob(path_str))
            if not matches:
                return None
            logger.debug(
                "[DocumentDriver] Glob %s matched %d files, using first: %s",
                self.path,
                len(matches),
                matches[0],
            )
            return Path(matches[0])
        return self.path

    def _load_text(self, path: Path) -> DataResult:
        """Load a text/markdown file."""
        text = path.read_text(encoding="utf-8-sig")
        return DataResult.ok(
            data=text,
            data_type="document",
            path=str(path),
            doc_type=self.doc_type,
            content_format="markdown",
            parser="mineru",
            size_chars=len(text),
        )

    def get_metadata(self) -> DataSourceMetadata:
        """Return metadata for this data source."""
        has_glob = any(c in str(self.path) for c in "*?[")
        name = self.doc_type if has_glob else self.path.stem
        return DataSourceMetadata(
            name=name,
            driver="document",
            layer_type=self.layer_type,
        )

    @property
    def supports_bbox_query(self) -> bool:
        return False


__all__ = ["DocumentDriver"]
