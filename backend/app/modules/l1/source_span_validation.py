"""Deterministic source-span validation for L1 observation rows."""

from __future__ import annotations

import hashlib
import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any

from app.contracts.l1.l1_contracts import L1SourceIndex
from app.contracts.l1.validation_contracts import (
    L1QuarantineRecord,
    SourceSpanValidationReport,
)
from app.modules.l1.spatial_admission import spatial_labels


@dataclass
class SourceValidationResult:
    accepted: list[Any] = field(default_factory=list)
    reports: list[SourceSpanValidationReport] = field(default_factory=list)
    quarantine_records: list[L1QuarantineRecord] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)


def _canonical_text(value: Any) -> str:
    text = html.unescape(str(value or ""))
    text = re.sub(r"<[^>]*>", "", text)
    text = unicodedata.normalize("NFKC", text)
    text = text.translate(str.maketrans({
        "“": '"',
        "”": '"',
        "‘": "'",
        "’": "'",
        "–": "-",
        "—": "-",
        "－": "-",
    }))
    return re.sub(r"\s+", "", text)


def _row_ref(observation: Any) -> str:
    payload = observation.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return f"l1-observation:{digest[:24]}"


def _quarantine(
    observation: Any,
    *,
    dimension_key: str,
    reason_code: str,
    errors: list[str],
    page_ref: str,
    model_call_ref: str,
    source_ref: str = "",
) -> L1QuarantineRecord:
    row_ref = _row_ref(observation)
    raw_digest = hashlib.sha256(
        json.dumps(
            observation.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()
    return L1QuarantineRecord(
        quarantine_ref=f"l1-quarantine:{raw_digest[:24]}",
        raw_row_digest=raw_digest,
        dimension=dimension_key,
        reason_code=reason_code,
        validation_errors=tuple(dict.fromkeys(errors)),
        model_call_ref=model_call_ref,
        page_ref=page_ref or row_ref,
        source_ref=source_ref,
    )


def _match_segments(
    ids: tuple[str, ...],
    quote: str,
    segments: list[Any],
) -> tuple[list[Any], bool, bool]:
    by_id = {str(segment.segment_id): segment for segment in segments}
    matched = [by_id[value] for value in ids if value in by_id]
    if not matched or not quote:
        return matched, False, False

    def matches(parts: list[Any]) -> bool:
        text = "".join(str(getattr(part, "text", "") or "") for part in parts)
        return bool(
            re.sub(r"\s+", " ", quote) in re.sub(r"\s+", " ", text)
            or _canonical_text(quote) in _canonical_text(text)
        )

    if matches(matched):
        return matched, True, False
    by_source: dict[str, list[Any]] = {}
    for segment in segments:
        by_source.setdefault(str(segment.source_key), []).append(segment)
    for grouped in by_source.values():
        grouped.sort(key=lambda item: int(getattr(item, "start_char", 0) or 0))
        anchors = [
            index
            for index, segment in enumerate(grouped)
            if str(segment.segment_id) in ids
        ]
        for anchor in anchors:
            for start in range(max(0, anchor - 1), anchor + 1):
                for end in range(anchor, min(len(grouped), anchor + 3)):
                    window = grouped[start:end + 1]
                    if len(window) > 1 and matches(window):
                        return window, True, True
    return matched, False, False


def validate_observation_sources(
    observations: list[Any],
    source_index: L1SourceIndex | None,
    *,
    dimension_key: str,
    source_snapshot_ref: str = "",
    page_ref: str = "",
    model_call_ref: str = "",
) -> SourceValidationResult:
    """Return admitted rows plus persisted validation and quarantine products."""

    result = SourceValidationResult()
    segments = list(getattr(source_index, "source_segments", ()) or ())
    by_id = {
        str(segment.segment_id): segment
        for segment in segments
        if str(segment.segment_id).strip()
    }
    snapshot_ref = source_snapshot_ref or (
        f"source-index:{source_index.source_digest}"
        if source_index is not None and source_index.source_digest
        else ""
    )
    for observation in observations:
        row_ref = _row_ref(observation)
        ids = tuple(
            str(value).strip()
            for value in (getattr(observation, "source_segment_ids", ()) or ())
            if str(value).strip()
        )
        matched = [by_id[value] for value in ids if value in by_id]
        errors: list[str] = []
        status = "valid"
        if source_index is None or not segments:
            status = "source_missing"
            errors.append("source index has no addressable segments")
        elif any(value not in by_id for value in ids):
            status = "segment_missing"
            errors.extend(
                f"unknown source segment: {value}"
                for value in ids
                if value not in by_id
            )
        elif any(
            int(getattr(segment, "start_char", 0) or 0) < 0
            or int(getattr(segment, "end_char", 0) or 0)
            < int(getattr(segment, "start_char", 0) or 0)
            for segment in matched
        ):
            status = "offset_mismatch"
            errors.append("source segment character offsets are invalid")
        quote = str(getattr(observation, "source_quote", "") or "").strip()
        matched, quote_matches, spans_segments = _match_segments(
            ids,
            quote,
            segments,
        )
        source_text = "".join(
            str(getattr(item, "text", "") or "") for item in matched
        )
        if status == "valid" and (
            not matched
            or not quote
            or not quote_matches
        ):
            status = "literal_mismatch"
            errors.append("source quote does not match cited segments")
        if spans_segments:
            result.diagnostics.append(
                f"observation_source_quote_spans_segments:{row_ref}"
            )
        source_refs = tuple(
            dict.fromkeys(
                str(getattr(segment, "source_ref", "")).strip()
                for segment in matched
                if str(getattr(segment, "source_ref", "")).strip()
            )
        )
        if status == "valid" and len(source_refs) > 1:
            status = "cross_source_reference"
            errors.append("one observation cites multiple source snapshots")
        source_text_canonical = _canonical_text(source_text)
        unsupported = [
            label
            for label in spatial_labels(observation)
            if _canonical_text(label) not in source_text_canonical
        ]
        if status == "valid" and unsupported:
            status = "role_not_admitted"
            errors.extend(
                f"spatial label is not source-backed: {label}"
                for label in unsupported
            )
        quote_digest = hashlib.sha256(
            _canonical_text(quote).encode("utf-8")
        ).hexdigest()
        report = SourceSpanValidationReport(
            validation_ref=f"source-span-validation:{row_ref.split(':', 1)[-1]}",
            fact_ref=row_ref,
            source_ref=source_refs[0] if source_refs else "",
            source_snapshot_ref=snapshot_ref,
            span_ref=("segments:" + ",".join(ids)) if ids else "",
            quote_digest=quote_digest,
            status=status,
            validation_errors=tuple(dict.fromkeys(errors)),
        )
        result.reports.append(report)
        if status != "valid":
            result.diagnostics.extend(
                [f"observation_source_{status}:{row_ref}", *errors]
            )
            result.quarantine_records.append(
                _quarantine(
                    observation,
                    dimension_key=dimension_key,
                    reason_code=status,
                    errors=errors,
                    page_ref=page_ref,
                    model_call_ref=model_call_ref,
                    source_ref=source_refs[0] if source_refs else "",
                )
            )
            continue
        result.accepted.append(observation.model_copy(update={
            "source_refs": list(dict.fromkeys([
                *getattr(observation, "source_refs", []),
                *source_refs,
            ])),
        }))
    return result


__all__ = ["SourceValidationResult", "validate_observation_sources"]
