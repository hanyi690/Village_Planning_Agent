"""Document adapter — MinerU Markdown with explicit provenance.

DATA deliberately has one textual interchange format: Markdown.  Frontend
uploads of PDF/Office/image files are converted by MinerU before they reach
this adapter; GIS files take the spatial ingestion path instead.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.data.model.layer_registry import GisLayerTypeEntry
from app.contracts.data.dlq import DlqCategory, DlqEntry
from app.infrastructure.logging import get_logger

from app.data.model.document_types import Document, L3Report, ReferencePlanningText
from . import AdapterResult, IngestAdapter

logger = get_logger(__name__)
_MARKDOWN_MEDIA_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


class DocumentAdapter(IngestAdapter):
    """Convert a Markdown payload without turning prose into planning facts.

    The adapter only loads text and source metadata.  Semantic facts remain
    the responsibility of Evidence/L1 and are never inferred here.
    """

    @staticmethod
    def _read(data: Any) -> Any:
        if isinstance(data, Path):
            if not data.is_file():
                raise FileNotFoundError(str(data))
            if data.suffix.casefold() not in {".md", ".markdown"}:
                raise ValueError("DATA document input must be Markdown (.md)")
            return data.read_text(encoding="utf-8-sig")
        if isinstance(data, str):
            try:
                path = Path(data)
                is_file = path.is_file()
            except (OSError, ValueError):
                is_file = False
            if is_file:
                if path.suffix.casefold() not in {".md", ".markdown"}:
                    raise ValueError("DATA document input must be Markdown (.md)")
                return path.read_text(encoding="utf-8-sig")
        if isinstance(data, dict):
            content_format = str(
                data.get("format") or data.get("content_format") or data.get("parsed_text_format") or ""
            ).strip().casefold()
            if content_format not in {"md", "markdown", "text/markdown"}:
                raise ValueError("DATA document payload must declare Markdown format")
            value = data.get("markdown")
            if value is None:
                value = data.get("text") or data.get("content")
            if not isinstance(value, str):
                raise ValueError("DATA Markdown payload is empty")
            return value
        if isinstance(data, str):
            # A raw string from DocumentDriver is already validated as a
            # Markdown file.  Markdown itself may be plain prose, so syntax
            # heuristics would reject legitimate documents.
            return data
        raise ValueError("unsupported DATA document payload")

    @staticmethod
    def _document_type(entry: GisLayerTypeEntry) -> str:
        return str(entry.ingest.feature_type if entry.ingest else "").strip().casefold()

    def load(
        self,
        data: dict,
        entry: GisLayerTypeEntry,
        *,
        strict: bool = False,
        **metadata: Any,
    ) -> AdapterResult:
        try:
            declared_format = str(metadata.get("content_format") or "markdown").strip().casefold()
            if declared_format not in {"md", "markdown", "text/markdown"}:
                raise ValueError("DATA document input must declare Markdown format")
            payload = self._read(data)
        except Exception as exc:
            if strict:
                raise
            reason = f"document decode failed: {type(exc).__name__}"
            return AdapterResult(
                warnings=[reason],
                dlq=[DlqEntry(
                    category=DlqCategory.REVIEW,
                    reason=reason,
                    source_layer=str(entry.gis_type_ref),
                    raw_feature={},
                )],
            )

        kind = self._document_type(entry)
        source = str(
            metadata.get("source")
            or (data.get("source") if isinstance(data, dict) else "")
            or (data.get("path") if isinstance(data, dict) else "")
            or entry.gis_type_ref
        )
        features: list[Any] = []
        try:
            media_refs = [match.strip() for match in _MARKDOWN_MEDIA_RE.findall(str(payload or "")) if match.strip()]
            parser = str(metadata.get("parser") or "mineru")
            cls = L3Report if kind in {"l3_report", "l3_reports"} else (
                ReferencePlanningText if kind in {"planning_text", "planning_markdown", "planning"} else Document
            )
            features.append(cls(
                text=str(payload or ""),
                doc_type=kind or ("planning_text" if cls is ReferencePlanningText else "document"),
                source=source,
                content_format="markdown",
                parser=parser,
                media_refs=media_refs,
                media_policy="deferred",
            ))
        except Exception as exc:
            reason = f"document model validation failed: {type(exc).__name__}"
            if strict:
                raise ValueError(reason) from exc
            return AdapterResult(
                warnings=[reason],
                dlq=[DlqEntry(
                    category=DlqCategory.REVIEW,
                    reason=reason,
                    source_layer=str(entry.gis_type_ref),
                    raw_feature={"source": source},
                )],
            )
        return AdapterResult(features=features)
