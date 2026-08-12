"""Document file driver - markdown, json, txt.

Loads non-spatial documents (planning markdown, L3 reports, plain text)
from local disk. Supports glob patterns for fuzzy file matching (e.g.
planning text files with variable names). Migrated from
gis/data/text_loader.py and the L3 report loading in loader.py.

Unlike vector/raster drivers, documents have no geometry - bbox is
always ignored. The driver returns raw text (markdown/txt) or parsed
dict (json) for downstream parse/consumption.
"""

from __future__ import annotations

import glob
import json
from pathlib import Path
from typing import Any, Optional

from app.data.model.canonical import BBox
from app.utils.logger import get_logger

from ..contracts import DataResult, DataSourceMetadata
from .base import DataSourceDriver
from .registry import DriverRegistry

logger = get_logger(__name__)


@DriverRegistry.register("document")
class DocumentDriver(DataSourceDriver):
    """Document file driver.

    Supports:
      - Markdown (.md) - planning text, reports
      - JSON (.json) - L3 reports, structured data
      - Text (.txt) - plain text

    Config keys:
        path: str          # file path or glob pattern
        doc_type: str      # "planning_markdown" | "l3_reports" | "text"
        encoding: str      # default "utf-8"
        layer_type: str    # semantic layer type
    """

    driver_type = "document"

    def __init__(self, config: dict[str, Any]):
        self.path = Path(config["path"])
        self.doc_type = config.get("doc_type", "text")
        self.encoding = config.get("encoding", "utf-8")
        self.layer_type = config.get("layer_type", "")

    def fetch(self, bbox: Optional[BBox] = None, **kwargs: Any) -> DataResult:
        """Load document file and return text or parsed dict.

        Args:
            bbox: Ignored (documents have no geometry).
            **kwargs: Unused.

        Returns:
            DataResult with data_type="document". For json/l3_reports,
            data is the parsed dict; for text/markdown, data is the raw string.
        """
        resolved = self._resolve_path()
        if resolved is None:
            return DataResult.fail(
                error=f"No file matching pattern: {self.path}"
            )

        if not resolved.exists():
            return DataResult.fail(error=f"File not found: {resolved}")

        try:
            if self.doc_type == "l3_reports":
                return self._load_l3_reports(resolved)
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
        text = path.read_text(encoding=self.encoding)
        return DataResult.ok(
            data=text,
            data_type="document",
            path=str(path),
            doc_type=self.doc_type,
            size_chars=len(text),
        )

    def _load_l3_reports(self, path: Path) -> DataResult:
        """Load L3 reports JSON and return the reports dict."""
        with open(path, "r", encoding=self.encoding) as f:
            data = json.load(f)
        reports = data.get("reports", {}) if isinstance(data, dict) else {}
        return DataResult.ok(
            data=reports,
            data_type="document",
            path=str(path),
            doc_type=self.doc_type,
            report_count=len(reports),
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
