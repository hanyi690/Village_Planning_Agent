"""L1-only indexing of opaque village input material.

The source index is a transport surface: it creates stable, addressable text
segments without assigning asset, demand, planning, or spatial meaning. Typed
L1 facts cite these segments directly through ``source_segment_ids`` and
``source_quote``.
"""

from __future__ import annotations

import hashlib

from app.contracts.l1.l1_contracts import L1SourceIndex, L1SourceSegment
from app.infrastructure.context_runtime.table_renderer import build_bounded_table


_L1_FACT_SOURCE_KEYS = frozenset({"village_data", "upload"})


def _source_digest(source: str) -> str:
    return hashlib.sha256((source or "").encode("utf-8")).hexdigest()


def _source_segments(
    source_key: str,
    source: str,
    digest: str,
    *,
    max_chars: int = 1800,
) -> list[L1SourceSegment]:
    """Split arbitrary source text into stable, addressable L1 segments."""

    text = str(source or "")
    if not text.strip():
        return []
    segments: list[L1SourceSegment] = []
    line_start = 1
    section_path: list[str] = []
    pending_lines: list[str] = []
    pending_start = 0
    pending_line_start = 1

    def flush(end_offset: int, end_line: int) -> None:
        nonlocal pending_lines, pending_start, pending_line_start
        body = "".join(pending_lines)
        if not body.strip():
            pending_lines = []
            return
        chunk_start = 0
        while chunk_start < len(body):
            chunk_end = min(chunk_start + max_chars, len(body))
            chunk = body[chunk_start:chunk_end]
            segment_number = len(segments) + 1
            segment_id = f"l1:{digest[:16]}:{source_key}:segment:{segment_number}"
            source_ref = f"input:{source_key}:sha256:{digest[:16]}:segment:{segment_number}"
            chunk_start_line = pending_line_start + body.count("\n", 0, chunk_start)
            chunk_end_line = pending_line_start + body.count("\n", 0, chunk_end)
            if chunk_end > chunk_start and body[chunk_end - 1] == "\n":
                chunk_end_line = max(chunk_start_line, chunk_end_line - 1)
            segments.append(
                L1SourceSegment(
                    segment_id=segment_id,
                    source_key=source_key,
                    source_ref=source_ref,
                    content_digest=digest,
                    start_char=pending_start + chunk_start,
                    end_char=pending_start + chunk_end,
                    start_line=chunk_start_line,
                    end_line=max(chunk_start_line, chunk_end_line),
                    text=chunk,
                    section_path=list(section_path),
                )
            )
            chunk_start = chunk_end
        pending_lines = []

    offset = 0
    for raw_line in text.splitlines(keepends=True):
        line = raw_line.rstrip("\r\n")
        stripped = line.strip()
        if stripped.startswith("#") or (
            stripped.startswith("【") and stripped.endswith("】")
        ):
            if pending_lines:
                flush(offset, line_start - 1)
            section_path = [stripped[:240]]
        if not pending_lines:
            pending_start = offset
            pending_line_start = line_start
        pending_lines.append(raw_line)
        offset += len(raw_line)
        line_end = line_start
        line_start += raw_line.count("\n") or 1
        joined = "".join(pending_lines)
        if len(joined) >= max_chars and (
            not stripped or stripped.endswith(("。", ".", "；", ";", "】"))
        ):
            flush(offset, line_end)
    if pending_lines:
        flush(len(text), max(line_start - 1, pending_line_start))
    return segments


def build_l1_source_index(
    input_texts: dict[str, str] | None,
    *,
    data_rows: list[dict[str, object]] | None = None,
) -> L1SourceIndex:
    """Build a format-neutral source index without producing semantic rows.

    ``data_rows`` is a bounded DATA catalog projection.  It is rendered as a
    source table and indexed like any other source segment; no fixed Bundle
    layer or field is required, and the raw geometry payload never enters the
    LLM page.
    """

    raw_sources = {
        str(key or "").strip(): str(value or "")
        for key, value in (input_texts or {}).items()
        if str(value or "").strip()
    }
    sources = {
        key: value
        for key, value in raw_sources.items()
        if key in _L1_FACT_SOURCE_KEYS
    }
    ignored_source_diagnostics = [
        f"ignored_source:{key}:not_l1_fact_source"
        for key in sorted(set(raw_sources).difference(sources))
    ]
    data_text = ""
    if data_rows:
        columns = (
            "source_feature_ref", "layer_ref", "geometry_kind", "source_crs",
            "feature_digest", "attribute_keys", "attribute_preview", "validity_status",
        )
        _, data_text = build_bounded_table(
            columns,
            data_rows,
            max_rows=32,
            max_chars=6200,
        )
    canonical_source = "\n\n".join(
        f"{key}\n{sources[key]}" for key in sorted(sources)
    )
    if data_text:
        canonical_source = f"{canonical_source}\n\ndata_catalog\n{data_text}"
    index = L1SourceIndex(
        source_documents=[f"input:{key}" for key in sorted(sources)],
        source_digest=_source_digest(canonical_source),
        diagnostics=ignored_source_diagnostics,
    )
    for source_key, source in sources.items():
        digest = _source_digest(source)
        index.source_segments.extend(_source_segments(source_key, source, digest))
    if data_text:
        digest = _source_digest(data_text)
        index.source_documents.append("input:data_catalog")
        index.source_segments.extend(_source_segments("data_catalog", data_text, digest))
    if not index.source_segments:
        index.diagnostics.append("no_nonempty_source_segments")
    return index


def render_l1_source_index(
    index: L1SourceIndex | None,
    *,
    max_rows: int = 96,
) -> str:
    """Render source segments for the L1 extraction prompt only."""

    if index is None:
        return "source_index=unavailable"
    rows = [
        {
            "segment_id": segment.segment_id,
            "source_ref": segment.source_ref,
            "lines": f"{segment.start_line}-{segment.end_line}",
            "section_path": segment.section_path,
            "text": segment.text[:1800],
        }
        for segment in index.source_segments
    ]
    _, table = build_bounded_table(
        ("segment_id", "source_ref", "lines", "section_path", "text"),
        rows,
        max_rows=max_rows,
        max_chars=max(6200, max_rows * 1800),
    )
    truncation = ""
    if len(rows) > max_rows:
        truncation = (
            f"\nsource_index_truncated=true; total_segments={len(rows)}"
        )
    return f"source_digest={index.source_digest}\n{table}{truncation}"


__all__ = ["build_l1_source_index", "render_l1_source_index"]
