"""Bounded deterministic retrieval over session-owned planning text.

This is deliberately separate from ``rag_retriever``. It searches the
current session's bundle input documents and L1 source spans. Report bodies
are handled by the bundle-backed report retriever. This retriever never reads
vector embeddings, never calls an external provider, and never returns
geometry.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "local-text-v2"

_MAX_RECORDS = 180
_MAX_FACTS = 12
_MAX_SOURCE_CHARS = 120000
_MAX_CHUNK_CHARS = 420
_CHUNK_SEPARATORS = frozenset("。！？；\n")
_PLANNING_TERMS = (
    "规划", "布局", "发展", "建设", "优先", "约束", "适宜", "保护", "整治",
    "公共服务", "交通组织", "服务半径", "设施", "道路", "用地", "空间", "建议",
)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _tokens(value: str) -> list[str]:
    tokens: list[str] = []
    cjk_run: list[str] = []
    latin_run: list[str] = []

    def flush_cjk() -> None:
        if len(cjk_run) < 2:
            return
        run = "".join(cjk_run)
        tokens.extend(run[index : index + 2].casefold() for index in range(len(run) - 1))
        if len(run) <= 12:
            tokens.append(run.casefold())

    def flush_latin() -> None:
        if len(latin_run) >= 2:
            tokens.append("".join(latin_run).casefold())

    for char in value or "":
        if "\u4e00" <= char <= "\u9fff":
            flush_latin()
            latin_run.clear()
            cjk_run.append(char)
        elif char.isascii() and (char.isalnum() or char in "_.-"):
            flush_cjk()
            cjk_run.clear()
            latin_run.append(char)
        else:
            flush_cjk()
            flush_latin()
            cjk_run.clear()
            latin_run.clear()
    flush_cjk()
    flush_latin()
    return list(dict.fromkeys(token for token in tokens if token))[:64]


def _chunks(value: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for char in value or "":
        if char in _CHUNK_SEPARATORS:
            if current:
                raw = "".join(current)
                if len(raw) <= _MAX_CHUNK_CHARS:
                    chunks.append(raw)
                else:
                    step = max(1, _MAX_CHUNK_CHARS - 80)
                    chunks.extend(
                        raw[start : start + _MAX_CHUNK_CHARS]
                        for start in range(0, len(raw), step)
                    )
                current.clear()
            continue
        current.append(char)
    if current:
        raw = "".join(current)
        if len(raw) <= _MAX_CHUNK_CHARS:
            chunks.append(raw)
        else:
            step = max(1, _MAX_CHUNK_CHARS - 80)
            chunks.extend(
                raw[start : start + _MAX_CHUNK_CHARS]
                for start in range(0, len(raw), step)
            )
    return chunks


def _record(kind: str, key: str, text: str, *, title: str = "", **metadata: Any) -> dict[str, str]:
    return {
        "kind": _text(kind),
        "key": _text(key),
        "title": _text(title),
        "text": _text(text)[:_MAX_SOURCE_CHARS],
        **{
            str(name): _text(value)
            for name, value in metadata.items()
            if _text(value)
        },
    }


def _records_from_context(context: Any) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    for item in list(getattr(context, "input_documents", []) or []):
        if isinstance(item, dict):
            records.append(_record(
                "bundle_document",
                item.get("name") or item.get("source") or "document",
                item.get("content", ""),
                title=item.get("name") or item.get("source", ""),
                source=item.get("source", ""),
                content_digest=item.get("content_digest", ""),
            ))

    snapshot_ref = _text(getattr(context, "l1_snapshot_ref", "")) or "snapshot"
    for index, fact in enumerate(list(
        getattr(context, "location_mentions", None) or []
    )[:48]):
        mention = _text(getattr(fact, "mention", ""))
        span = _text(getattr(fact, "source_span", ""))
        spatial_hint = _text(getattr(fact, "spatial_hint", ""))
        related = "、".join(
            _text(value)
            for value in (getattr(fact, "related_mentions", None) or [])
            if _text(value)
        )
        text = span or "；".join(value for value in (mention, spatial_hint, related) if value)
        if not text:
            continue
        records.append(_record(
            "l1_source_span",
            f"{snapshot_ref}:{index}",
            text,
            title=mention,
            dimension=getattr(fact, "dimension_key", ""),
            source_report_ref=getattr(fact, "source_report_ref", ""),
        ))
    return records


async def _collect_records(session_id: str) -> list[dict[str, str]]:
    records: list[dict[str, str]] = []
    try:
        from app.infrastructure.context_runtime.manager import get_cached_context

        context = get_cached_context(session_id)
        if context is None and session_id:
            # Evidence execution can start from a resumed/cold process. Do
            # not treat an empty in-process cache as an empty source corpus:
            # hydrate the current session's canonical context first. This
            # path never loads history sessions and never calls a retriever.
            from app.infrastructure.evidence_runtime.context_hydration import (
                prepare_evidence_context,
            )

            context = await prepare_evidence_context(
                session_id,
                include_reports=False,
            )
        if context is not None:
            records = _records_from_context(context)
    except Exception as exc:
        logger.debug("[local_text_retriever] context unavailable: %s", exc)

    return [record for record in records if record.get("text")][:_MAX_RECORDS]



def _source_type(kind: str) -> str:
    if kind.startswith("report"):
        return "report"
    if kind == "l1_source_span":
        return "l1"
    return "bundle"


def _retrieve_records(
    records: Iterable[dict[str, str]],
    *,
    query: str,
    dimension_key: str,
    required_facts: Iterable[str],
    entity_scope: Iterable[str],
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    requested = " ".join([query, dimension_key, *required_facts, *entity_scope]).strip()
    query_terms = _tokens(requested)
    query_text = requested.casefold()
    candidates: list[tuple[float, dict[str, str], str]] = []
    for record in records:
        for index, raw in enumerate(_chunks(record.get("text", ""))):
            chunk = " ".join(raw.split()).strip()[:_MAX_CHUNK_CHARS]
            if len(chunk) < 8:
                continue
            chunk_lower = chunk.casefold()
            overlap = sum(1 for term in query_terms if term in chunk_lower)
            exact = sum(1 for term in _tokens(query) if term in chunk_lower)
            planning = sum(1 for term in _PLANNING_TERMS if term in chunk)
            if not query_terms:
                score = min(0.45, 0.1 * planning)
            else:
                score = (
                    0.42 * min(overlap, 5) / 5
                    + 0.42 * min(exact, 4) / 4
                    + 0.08 * min(planning, 3)
                    + (0.08 if dimension_key and dimension_key.casefold() in chunk_lower else 0.0)
                )
            if query_text and not overlap and not exact:
                continue
            if score <= 0.05:
                continue
            candidates.append((min(0.98, score), record, f"{index}:{chunk}"))

    candidates.sort(key=lambda item: (-item[0], item[1].get("kind", ""), item[1].get("key", "")))
    facts: list[EvidenceFact] = []
    sources: list[EvidenceSource] = []
    seen: set[str] = set()
    for score, record, indexed in candidates:
        _, chunk = indexed.split(":", 1)
        source_ref = "local-text:{kind}:{key}:chunk:{digest}".format(
            kind=record.get("kind", "unknown"),
            key=record.get("key", "unknown"),
            digest=hashlib.sha256(
                f"{record.get('kind')}:{record.get('key')}:{chunk}".encode("utf-8")
            ).hexdigest()[:16],
        )
        if source_ref in seen:
            continue
        seen.add(source_ref)
        kind = record.get("kind", "bundle_document")
        fact_type = "l1_semantic_context" if kind == "l1_source_span" else "planning_text"
        fact = EvidenceFact(
            statement=chunk,
            confidence=round(max(0.35, min(0.9, score)), 3),
            source_refs=[source_ref],
            fact_type=fact_type,
            fields={
                "evidence_role": "semantic_place_context" if kind == "l1_source_span" else "planning_background",
                "source_kind": kind,
                "source_title": record.get("title", ""),
                "source_key": record.get("key", ""),
                "content_digest": record.get("content_digest", ""),
                "dimension_key": record.get("dimension", dimension_key),
                "source_report_ref": record.get("source_report_ref", ""),
                "retrieval_mode": "local_lexical",
                "relevance_score": f"{score:.3f}",
            },
            evidence_span=chunk,
            source_locator=source_ref,
            support_relation="session_text_retrieval",
            status="needs_review",
            evidence_role=(
                "semantic_place_context"
                if kind == "l1_source_span"
                else "planning_background"
            ),
            source_kind=str(kind),
            spatial_granularity="feature" if kind == "l1_source_span" else "none",
            planning_use="grounding" if kind == "l1_source_span" else "context",
        )
        facts.append(fact)
        sources.append(EvidenceSource(
            source_type=_source_type(kind),
            reference=source_ref,
            confidence=fact.confidence,
        ))
        if len(facts) >= _MAX_FACTS:
            break
    return facts, sources


async def retrieve_from_local_text(
    session_id: str,
    dimension_key: str,
    stage: str = "",
    *,
    query: str = "",
    required_facts: list[str] | None = None,
    entity_scope: list[str] | None = None,
) -> tuple[list[EvidenceFact], list[EvidenceSource]]:
    """Retrieve bounded semantic spans from session-owned text sources."""
    return _retrieve_records(
        await _collect_records(session_id),
        query=query,
        dimension_key=dimension_key,
        required_facts=required_facts or [],
        entity_scope=entity_scope or [],
    )


__all__ = ["RETRIEVER_VERSION", "retrieve_from_local_text"]
