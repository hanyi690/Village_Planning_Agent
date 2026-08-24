"""L1-only indexing of opaque village input material.

The workflow receives narrative text, OCR, tables, exports, or mixed source
documents.  The runtime source index creates addressable segments without
assigning semantic meaning; L1's structured model confirms observations and
current/demand registrations.  Later stages consume the ``L1InputRegister``
artifact instead of parsing raw input.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from app.contracts.domain.l1_contracts import (
    L1InputRegister,
    L1RegisterRow,
    L1SourceSegment,
)
from app.domain.assessment.observation_draft import L1RegisterRowDraft


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
    """Split arbitrary source text into stable, addressable L1 segments.

    This is deliberately a transport operation, not a semantic parser.  It
    keeps line/character offsets and lightweight heading context so the model
    can inspect narrative text, tables, OCR output, or mixed documents using
    the same contract.  No table header, row, unit, or planning meaning is
    inferred here.
    """

    text = str(source or "")
    if not text.strip():
        return []
    segments: list[L1SourceSegment] = []
    start = 0
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
        if stripped.startswith("#") or (stripped.startswith("【") and stripped.endswith("】")):
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
        if len(joined) >= max_chars and (not stripped or stripped.endswith(("。", ".", "；", ";", "。", "】"))):
            flush(offset, line_end)
    if pending_lines:
        flush(len(text), max(line_start - 1, pending_line_start))
    return segments


def build_l1_source_index(input_texts: dict[str, str] | None) -> L1InputRegister:
    """Build an L1 source index without assuming an input document format.

    The index exposes addressable segments to the L1 model.  It does not try
    to decide whether the source is a table, report, OCR dump, spreadsheet
    export, or narrative text.  Explicit ``current_assets``/``demands`` are
    therefore empty until the L1 model confirms such a record through its
    structured output.  The source index never emits semantic rows itself;
    rows are created only when L1 returns a typed draft with a verified source
    segment and quote.
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
    canonical_source = "\n\n".join(
        f"{key}\n{sources[key]}" for key in sorted(sources)
    )
    register = L1InputRegister(
        source_documents=[f"input:{key}" for key in sorted(sources)],
        source_digest=_source_digest(canonical_source),
        diagnostics=ignored_source_diagnostics,
    )
    for source_key, source in sources.items():
        digest = _source_digest(source)
        register.source_segments.extend(
            _source_segments(source_key, source, digest)
        )
    if not register.source_segments:
        register.diagnostics.append("no_nonempty_source_segments")
    return register


def _source_rows(register: L1InputRegister | None) -> dict[str, L1RegisterRow]:
    if register is None:
        return {}
    return {
        row.row_id: row
        for row in [*(register.current_assets or []), *(register.demands or [])]
        if str(row.row_id or "").strip()
    }


def _source_segments_by_id(
    register: L1InputRegister | None,
) -> dict[str, L1SourceSegment]:
    if register is None:
        return {}
    return {
        segment.segment_id: segment
        for segment in (register.source_segments or [])
        if str(segment.segment_id or "").strip()
    }


def _quote_matches_segment(quote: str, segment: L1SourceSegment) -> bool:
    normalized_quote = re.sub(r"\s+", " ", str(quote or "").strip())
    normalized_text = re.sub(r"\s+", " ", str(segment.text or ""))
    return bool(normalized_quote and normalized_quote in normalized_text)


def materialize_dimension_register_rows(
    drafts: list[L1RegisterRowDraft | dict[str, Any]] | None,
    source_index: L1InputRegister | None,
    dimension_key: str,
) -> tuple[list[L1RegisterRow], list[str]]:
    """Materialize dimension registrations from verified L1 source evidence.

    Model-provided locators are never authoritative.  A valid row ID and
    matching ledger kind select an existing canonical row; otherwise a typed
    draft must provide a valid ledger kind, source segment IDs, and a quote.
    This prevents a repair call from silently changing source data while still
    allowing L1 to register a record that was not present in a pre-parsed
    table.
    """

    rows_by_id = _source_rows(source_index)
    segments_by_id = _source_segments_by_id(source_index)
    diagnostics: list[str] = []
    result: list[L1RegisterRow] = []
    seen: dict[str, str] = {}
    for raw in drafts or []:
        try:
            draft = raw if isinstance(raw, L1RegisterRowDraft) else L1RegisterRowDraft.model_validate(raw)
        except Exception as exc:  # noqa: BLE001 - bounded row diagnostic
            diagnostics.append(f"register_row_invalid:{type(exc).__name__}")
            continue
        row_id = str(draft.row_id or "").strip()
        source_row = rows_by_id.get(row_id)
        if source_row is None:
            segment_ids = list(dict.fromkeys(
                str(value).strip()
                for value in draft.source_segment_ids
                if str(value).strip()
            ))
            if row_id and not segment_ids:
                diagnostics.append(f"register_row_unknown:{row_id}")
                continue
            kind = str(draft.ledger_kind or "").strip()
            matched_segments = [
                segments_by_id[value]
                for value in segment_ids
                if value in segments_by_id
            ]
            if kind not in {"current_asset", "demand"}:
                diagnostics.append(
                    f"register_row_ledger_kind_missing:{row_id or 'generated'}"
                )
                continue
            if not matched_segments or len(matched_segments) != len(segment_ids):
                diagnostics.append(
                    f"register_row_source_segment_unknown:{row_id or 'generated'}"
                )
                continue
            if not _quote_matches_segment(draft.source_quote, matched_segments[0]):
                diagnostics.append(
                    f"register_row_source_quote_unverified:{row_id or 'generated'}"
                )
                continue
            quote = str(draft.source_quote or "").strip()
            identity = json.dumps(
                {
                    "dimension": dimension_key,
                    "kind": kind,
                    "segments": segment_ids,
                    "quote": quote,
                    "name": str(draft.name or "").strip(),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            generated_id = (
                f"l1:{getattr(source_index, 'source_digest', '')[:16]}:"
                f"{kind}:{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:16]}"
            )
            canonical_ref = matched_segments[0].source_ref
            generated = L1RegisterRow(
                row_id=generated_id,
                ledger_kind=kind,
                status=draft.status,
                dimension_key=str(dimension_key or ""),
                evidence_note=str(draft.evidence_note or "").strip(),
                source_digest=matched_segments[0].content_digest,
                sequence=str(draft.row_id or ""),
                category=str(draft.category or "").strip(),
                name=str(draft.name or "").strip(),
                quantity_text=str(draft.quantity_text or ""),
                quantity_value=draft.quantity_value,
                quantity_unit=str(draft.quantity_unit or ""),
                location_text=str(draft.location_text or ""),
                service_scope=str(draft.service_scope or ""),
                coverage=str(draft.coverage or ""),
                notes=str(draft.notes or ""),
                source_ref=canonical_ref,
                source_span=quote,
                raw_cells=[],
            )
            prior_status = seen.get(generated.row_id)
            if prior_status is not None and prior_status != generated.status:
                diagnostics.append(f"register_row_conflicting_status:{generated.row_id}")
                continue
            seen[generated.row_id] = generated.status
            if generated.status != "not_applicable":
                result.append(generated)
            continue
        if draft.ledger_kind is None:
            diagnostics.append(f"register_row_ledger_kind_missing:{row_id}")
            continue
        if source_row.ledger_kind != draft.ledger_kind:
            diagnostics.append(
                f"register_row_ledger_kind_mismatch:{row_id}:"
                f"{source_row.ledger_kind}!={draft.ledger_kind}"
            )
            continue
        prior_status = seen.get(row_id)
        if prior_status is not None and prior_status != draft.status:
            diagnostics.append(f"register_row_conflicting_status:{row_id}")
            continue
        seen[row_id] = draft.status
        if draft.status == "not_applicable":
            continue
        result.append(
            source_row.model_copy(
                update={
                    "status": draft.status,
                    "dimension_key": str(dimension_key or ""),
                    "evidence_note": str(draft.evidence_note or "").strip(),
                }
            )
        )
    unique: dict[str, L1RegisterRow] = {}
    for row in result:
        unique.setdefault(row.row_id, row)
    return list(unique.values()), diagnostics


def render_l1_source_index(
    register: L1InputRegister | None,
    *,
    row_ids: list[str] | None = None,
    max_rows: int = 96,
) -> str:
    """Render a compact source index for L1 observe/register prompts only."""

    if register is None:
        return "source_index=unavailable"
    wanted = set(row_ids or [])
    rows = [*(register.current_assets or []), *(register.demands or [])]
    if wanted:
        rows = [row for row in rows if row.row_id in wanted]
    if not rows and register.source_segments:
        segments = register.source_segments
        if wanted:
            segments = [segment for segment in segments if segment.segment_id in wanted]
        lines = [
            f"source_digest={register.source_digest}",
            "segment_id | source_ref | lines | section_path | text",
        ]
        for segment in segments[:max_rows]:
            lines.append(
                " | ".join(
                    [
                        segment.segment_id,
                        segment.source_ref,
                        f"{segment.start_line}-{segment.end_line}",
                        "/".join(segment.section_path),
                        segment.text.replace("\n", " ")[:1800],
                    ]
                )
            )
        if len(segments) > max_rows:
            lines.append(
                f"source_index_truncated=true; total_segments={len(segments)}"
            )
        return "\n".join(lines)
    lines = [
        f"source_digest={register.source_digest}",
        "row_id | ledger_kind | category | name | quantity | land_or_length | location | source_ref",
    ]
    for row in rows[:max_rows]:
        quantity = row.quantity_text or (
            f"{row.quantity_value}{row.quantity_unit}" if row.quantity_value is not None else ""
        )
        land = row.land_area_or_length_text or (
            f"{row.land_area_or_length_value}{row.land_area_or_length_unit}"
            if row.land_area_or_length_value is not None else ""
        )
        lines.append(
            " | ".join(
                [
                    row.row_id,
                    row.ledger_kind,
                    row.category,
                    row.name,
                    quantity,
                    land,
                    row.location_text,
                    row.source_ref,
                ]
            )
        )
    if len(rows) > max_rows:
        lines.append(f"source_index_truncated=true; total_rows={len(rows)}")
    if not wanted and register.source_segments:
        lines.append("【原始 source segments（仅证据定位，不代表语义分类）】")
        lines.append("segment_id | source_ref | lines | section_path | text")
        for segment in register.source_segments[:max_rows]:
            lines.append(
                " | ".join(
                    [
                        segment.segment_id,
                        segment.source_ref,
                        f"{segment.start_line}-{segment.end_line}",
                        "/".join(segment.section_path),
                        segment.text.replace("\n", " ")[:1800],
                    ]
                )
            )
    return "\n".join(lines)


def render_l1_input_register(register: L1InputRegister | None, *, max_rows: int = 80) -> str:
    """Render the already-structured L1 register for a downstream prompt.

    This is a projection only: it never reads or tokenizes ``village_data``.
    Keeping the projection here makes it difficult for Project Bank or a UI
    caller to accidentally introduce a second raw-document parser.
    """
    if register is None:
        return "（L1 尚未产出原始输入登记；不得从其他文本自行补造台账。）"

    lines = [
        "source_documents=" + ",".join(register.source_documents),
        "source_digest=" + str(register.source_digest or ""),
        "source_segments=" + str(len(register.source_segments or [])),
        "【现状资产】",
    ]
    rows = [*register.current_assets, *register.demands]
    for row in register.current_assets:
        lines.append(_render_register_row(row))
    lines.append("【需求登记】")
    for row in register.demands:
        lines.append(_render_register_row(row))
    if register.diagnostics:
        lines.append("diagnostics=" + ";".join(register.diagnostics))
    if not rows and register.source_segments:
        lines.append("原始资料尚未确认现状资产/需求登记；只能引用已审计 L1 facts，不得按段落自行补造台账。")
    if len(rows) > max_rows:
        lines.append(f"（共 {len(rows)} 行；上述内容按 L1 顺序完整投影。）")
    return "\n".join(lines)


def _render_register_row(row: L1RegisterRow) -> str:
    def value(text: Any, number: Any, unit: Any) -> str:
        raw = str(text or "").strip()
        if raw:
            return raw
        if number is None:
            return ""
        return f"{number}{unit or ''}"

    return (
        f"{row.status}:{row.ledger_kind}#{row.sequence} | category={row.category} | "
        f"name={row.name} | quantity={value(row.quantity_text, row.quantity_value, row.quantity_unit)} | "
        f"land_or_length={value(row.land_area_or_length_text, row.land_area_or_length_value, row.land_area_or_length_unit)} | "
        f"building={value(row.building_area_text, row.building_area_value, row.building_area_unit)} | "
        f"independent_land_use={row.independent_land_use} | location={row.location_text} | "
        f"service_scope={row.service_scope} | coverage={row.coverage} | notes={row.notes} | "
        f"source_ref={row.source_ref}"
    )


__all__ = [
    "build_l1_source_index",
    "materialize_dimension_register_rows",
    "render_l1_input_register",
    "render_l1_source_index",
]
