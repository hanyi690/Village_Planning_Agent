"""Report retriever - search L1/L2/L3 AnalysisReports for spatial evidence."""
from __future__ import annotations

from typing import Any, List, Tuple

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
)
from app.infrastructure.llm.tools.access.shared import resolve_bundle
from app.infrastructure.reports.report_store import ReportStore
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)
RETRIEVER_VERSION = "report-v4"

_PLANNING_KEYWORDS = (
    "规划", "布局", "发展", "建设", "优先", "约束", "适宜", "保护", "整治",
    "公共服务", "服务半径", "设施配置", "交通组织", "用地", "空间结构", "建议",
)
_SENTENCE_SEPARATORS = frozenset("。；\n")


def _chunks(value: str) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    for char in value or "":
        if char in _SENTENCE_SEPARATORS:
            if current:
                chunks.append("".join(current))
                current.clear()
            continue
        current.append(char)
    if current:
        chunks.append("".join(current))
    return chunks


def _cjk_terms(value: str) -> list[str]:
    terms: list[str] = []
    run: list[str] = []
    for char in value or "":
        if "\u4e00" <= char <= "\u9fff":
            run.append(char)
            continue
        if len(run) >= 2:
            terms.extend("".join(run[index : index + 2]).lower() for index in range(len(run) - 1))
        run = []
    if len(run) >= 2:
        terms.extend("".join(run[index : index + 2]).lower() for index in range(len(run) - 1))
    return terms


def _query_terms(query: str) -> list[str]:
    terms: list[str] = []
    latin: list[str] = []
    for char in query or "":
        if "\u4e00" <= char <= "\u9fff":
            if latin:
                if len(latin) >= 2:
                    terms.append("".join(latin).lower())
                latin.clear()
            continue
        if char.isascii() and (char.isalnum() or char in "_.-"):
            latin.append(char)
            continue
        if len(latin) >= 2:
            terms.append("".join(latin).lower())
        latin.clear()
    if len(latin) >= 2:
        terms.append("".join(latin).lower())
    terms.extend(_cjk_terms(query or ""))
    return list(dict.fromkeys(terms))


def _extract_relevant_background(
    content: str,
    query: str = "",
    *,
    dimension_match: bool = False,
    limit: int = 8,
) -> List[str]:
    findings: list[str] = []
    query_terms = _query_terms(query)
    for sent in _chunks(content or ""):
        sent = sent.strip()
        if len(sent) < 4:
            continue
        relevant = not query_terms or any(term in sent.lower() for term in query_terms)
        semantic = any(k in sent for k in _PLANNING_KEYWORDS)
        # An explicit entity/query hit is already a relevance signal.  Do not
        # discard location descriptions merely because the sentence does not
        # also contain a planning keyword (for example, a hazard name followed
        # by its village relation).  With no query terms, retain the bounded
        # planning-background filter for dimension-level context retrieval.
        if relevant and (bool(query_terms) or (semantic and dimension_match)):
            findings.append(sent[:240])
        if len(findings) >= limit:
            break
    return findings


async def load_report_corpus(
    session_id: str,
    *,
    context: Any = None,
    max_chars: int = 12000,
) -> str:
    """Load the bounded authoritative L1/L2/L3 report corpus for planning LLMs.

    ``PlanningContext.reports`` is intentionally a manifest and summary index;
    it does not own report bodies.  Grounding and planning prompts therefore
    read bodies through the same bundle-selected report references used by the
    evidence retriever.  This keeps report prose available without copying it
    into Bundle snapshots or treating prose as spatial identity.
    """
    limit = max(0, int(max_chars or 0))
    if not session_id or limit == 0:
        return ""

    bundle = None
    try:
        bundle = await resolve_bundle(str(session_id))
    except Exception as exc:  # pragma: no cover - defensive boundary
        logger.warning("[report_retriever] report bundle resolution failed: %s", exc)

    refs = list(getattr(getattr(bundle, "documents", None), "report_refs", []) or [])
    refs = [
        ref for ref in refs
        if isinstance(ref, dict) and int(ref.get("layer") or 0) in (1, 2, 3)
    ]
    report_ids = list(dict.fromkeys(
        str(ref.get("report_id") or "").strip()
        for ref in refs
        if str(ref.get("report_id") or "").strip()
    ))

    bodies: dict[str, Any] = {}
    if report_ids:
        try:
            bodies = await ReportStore.get_instance().get_reports_by_ids(report_ids)
        except Exception as exc:  # pragma: no cover - storage boundary
            logger.warning("[report_retriever] report body load failed: %s", exc)

    parts: list[str] = []
    seen_ids: set[str] = set()
    total_chars = 0
    for ref in refs:
        report_id = str(ref.get("report_id") or "").strip()
        if not report_id or report_id in seen_ids:
            continue
        report = bodies.get(report_id)
        content = str(getattr(report, "content", "") or "").strip()
        if not content:
            continue
        layer = int(ref.get("layer") or 0)
        dimension_key = str(ref.get("dimension_key") or "").strip()
        header = f"[L{layer} {dimension_key or 'report'} {report_id}]"
        remaining = limit - total_chars
        if remaining <= 0:
            break
        chunk = f"{header}\n{content}"[:remaining]
        parts.append(chunk)
        total_chars += len(chunk)
        seen_ids.add(report_id)

    if not parts:
        # Explicitly support test/injected contexts that carry a report body;
        # summaries remain metadata and are never promoted to report content.
        for payload in dict(getattr(context, "reports", {}) or {}).values():
            if not isinstance(payload, dict):
                continue
            content = str(payload.get("content") or payload.get("body") or "").strip()
            if not content:
                continue
            remaining = limit - total_chars
            if remaining <= 0:
                break
            chunk = content[:remaining]
            parts.append(chunk)
            total_chars += len(chunk)

    if refs and len(seen_ids) < len(report_ids):
        logger.warning(
            "[report_retriever] report corpus incomplete: loaded=%d expected=%d",
            len(seen_ids),
            len(report_ids),
        )
    return "\n\n".join(parts)


async def retrieve_from_reports(
    session_id: str,
    dimension_key: str,
    stage: str,
    query: str = "",
    required_facts: List[str] | None = None,
    entity_scope: List[str] | None = None,
) -> Tuple[List[EvidenceFact], List[EvidenceSource]]:
    """Search L1/L2/L3 reports for bounded planning-background excerpts.

    Report prose is analysis context, not an authoritative spatial identity.
    Even when a sentence contains a place-like word, a number, or a geometry
    term, it must not become a grounding fact.  Concrete location binding is
    supplied by typed L1 facts and the bundle/KG EvidenceGraph instead.

    Returns (facts, sources) - facts are bounded planning excerpts and sources
    reference the report layer+dimension.
    """
    bundle = await resolve_bundle(session_id)
    refs = list(getattr(bundle.documents, "report_refs", []) or [])
    refs = [
        ref for ref in refs
        if int(ref.get("layer") or 0) in (1, 2, 3)
    ]
    report_ids = [str(ref.get("report_id") or "") for ref in refs]
    store = ReportStore.get_instance()
    report_bodies = await store.get_reports_by_ids(report_ids)
    facts: List[EvidenceFact] = []
    sources: List[EvidenceSource] = []

    for ref in refs:
        layer = int(ref.get("layer") or 0)
        dk = str(ref.get("dimension_key") or "")
        report_id = str(ref.get("report_id") or "")
        report = report_bodies.get(report_id)
        content = str(getattr(report, "content", "") or "")
        if not dk or not content:
            continue
        sources.append(EvidenceSource(
            source_type="report",
            reference=f"L{layer}:{dk}:{report_id}",
            confidence=0.9,
        ))
        dimension_match = dk == dimension_key
        query_match = bool(query) and any(
            term in f"{dk} {content}".lower()
            for term in _query_terms(query)
        )
        if dimension_match or query_match:
            for finding in _extract_relevant_background(
                content,
                query=query,
                dimension_match=dimension_match,
            ):
                source_ref = f"L{layer}:{dk}:{report_id}"
                facts.append(EvidenceFact(
                    statement=finding,
                    confidence=0.8,
                    source_refs=[source_ref],
                    fact_type="planning_text",
                    fields={
                        "evidence_role": "planning_background",
                        "source_kind": "analysis_report",
                        "dimension_key": dk,
                        "report_layer": f"L{layer}",
                        "report_id": report_id,
                    },
                    evidence_span=finding,
                    source_locator=source_ref,
                    support_relation="report_retrieval",
                    status="needs_review",
                    evidence_role="planning_background",
                    source_kind="analysis_report",
                    spatial_granularity="none",
                    planning_use="context",
                ))
    return facts, sources
