"""Report retriever - search L1/L2/L3 AnalysisReports for spatial evidence."""
from __future__ import annotations

import re
from typing import List, Tuple

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
)
from app.infrastructure.reports.report_store import ReportStore
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SPATIAL_KEYWORDS = (
    "公顷", "亩", "平方米", "km²", "面积", "占地", "位于", "沿",
    "临", "集中", "分布", "覆盖", "红线", "边界", "地块", "道路", "设施", "用地",
)
_SENTENCE_SPLIT = re.compile(r"[。；\n]+")


def _extract_spatial_findings(content: str, limit: int = 6) -> List[str]:
    findings = []
    for sent in _SENTENCE_SPLIT.split(content or ""):
        sent = sent.strip()
        if len(sent) < 4:
            continue
        if any(k in sent for k in _SPATIAL_KEYWORDS) and re.search(r"\d", sent):
            findings.append(sent[:140])
        if len(findings) >= limit:
            break
    return findings


async def retrieve_from_reports(
    session_id: str,
    dimension_key: str,
    stage: str,
) -> Tuple[List[EvidenceFact], List[EvidenceSource]]:
    """Search L1/L2/L3 reports for spatial findings relevant to the dimension.

    Returns (facts, sources) - facts are sentence-level spatial findings,
    sources reference the report layer+dimension.
    """
    store = ReportStore.get_instance()
    facts: List[EvidenceFact] = []
    sources: List[EvidenceSource] = []

    layers = [1, 2, 3]
    for layer in layers:
        try:
            reports = await store.get_layer_reports_with_sources(session_id, layer)
        except Exception as e:
            logger.warning("[report_retriever] L%d fetch failed: %s", layer, e)
            continue
        for dk, rec in (reports or {}).items():
            content = str((rec or {}).get("content") or "")
            if not content:
                continue
            sources.append(EvidenceSource(
                source_type="report",
                reference=f"L{layer}:{dk}",
                confidence=0.9,
            ))
            if dk == dimension_key:
                for finding in _extract_spatial_findings(content):
                    facts.append(EvidenceFact(
                        statement=finding,
                        confidence=0.8,
                        source_refs=[f"L{layer}:{dk}"],
                    ))
    return facts, sources
