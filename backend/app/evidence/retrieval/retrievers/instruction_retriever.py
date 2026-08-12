# backend/app/agent/explore/retrievers/instruction_retriever.py
"""Instruction retriever - 【INSTRUCTION】 sections as structured evidence."""
from __future__ import annotations

from typing import List, Tuple

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
)
from app.infrastructure.reports.report_store import ReportStore, split_instruction
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _table_facts(instruction: str, source_ref: str) -> list[EvidenceFact]:
    """Compile instruction markdown rows into auditable evidence facts."""
    from app.data.ingestion.tables import _iter_tables

    facts: list[EvidenceFact] = []
    seen: set[tuple[str, ...]] = set()
    for table_index, (header, rows) in enumerate(_iter_tables(instruction), start=1):
        normalized_header = [str(cell).strip() for cell in header]
        if not normalized_header or not rows:
            continue
        for row_index, row in enumerate(rows, start=1):
            cells = tuple(str(cell).strip() for cell in row)
            if len(cells) != len(normalized_header) or not any(cells):
                continue
            if cells in seen:
                continue
            seen.add(cells)
            fields = {
                normalized_header[i]: cells[i]
                for i in range(len(normalized_header))
                if cells[i]
            }
            name = fields.get("名称") or fields.get("项目") or fields.get("项目名称") or ""
            location = fields.get("位置") or fields.get("选址") or fields.get("所在位置") or ""
            fact_type = fields.get("类型") or fields.get("类别") or "instruction_row"
            statement = "；".join(f"{key}={value}" for key, value in fields.items())
            evidence_span = " | ".join(cells)
            facts.append(EvidenceFact(
                statement=statement[:500],
                confidence=0.95 if name else 0.8,
                source_refs=[source_ref],
                spatial_refs=[location] if location else [],
                fact_type=fact_type,
                fields=fields,
                evidence_span=evidence_span,
                source_locator=f"{source_ref}:table-{table_index}:row-{row_index}",
                support_relation="quotation",
                status="verified" if fields else "not_stated",
            ))
    return facts


async def retrieve_from_instructions(
    session_id: str,
    dimension_key: str,
    stage: str,
) -> Tuple[List[EvidenceFact], List[EvidenceSource]]:
    """Extract 【INSTRUCTION】 sections from reports as structured evidence.

    Instructions carry structured location/area/function data that is more
    reliable than free-text report content for spatial reasoning.
    """
    store = ReportStore.get_instance()
    facts: List[EvidenceFact] = []
    sources: List[EvidenceSource] = []

    stage_layer = int(stage.lstrip("Ll")) if stage else 1
    layers = [1, 2, 3]
    for layer in layers:
        try:
            reports = await store.get_layer_reports_with_sources(session_id, layer)
        except Exception as e:
            logger.warning("[instruction_retriever] L%d fetch failed: %s", layer, e)
            continue
        for dk, rec in (reports or {}).items():
            content = str((rec or {}).get("content") or "")
            if not content:
                continue
            try:
                _, instr = split_instruction(content)
            except Exception:
                instr = ""
            if not instr or not instr.strip():
                continue
            sources.append(EvidenceSource(
                source_type="report",
                reference=f"L{layer}:{dk}:instruction",
                confidence=0.95,
            ))
            source_ref = f"L{layer}:{dk}:instruction"
            structured = _table_facts(instr, source_ref)
            if structured:
                facts.extend(structured)
            else:
                for line_no, raw in enumerate(instr.strip().splitlines(), start=1):
                    line = raw.strip()
                    if len(line) >= 4 and not line.startswith("【INSTRUCTION】"):
                        facts.append(EvidenceFact(
                            statement=line[:500],
                            confidence=0.6,
                            source_refs=[source_ref],
                            evidence_span=line,
                            source_locator=f"{source_ref}:line-{line_no}",
                            support_relation="quotation",
                            status="unstructured",
                        ))
    return facts, sources
