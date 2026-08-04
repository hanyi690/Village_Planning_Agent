# backend/app/agent/explore/retrievers/instruction_retriever.py
"""Instruction retriever - 【INSTRUCTION】 sections as structured evidence."""
from __future__ import annotations

from typing import List, Tuple

from app.modules.schema.contracts.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
)
from app.services.report_store import ReportStore, split_instruction
from app.utils.logger import get_logger

logger = get_logger(__name__)


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
            for line in instr.strip().split("\n"):
                line = line.strip()
                if len(line) >= 4:
                    facts.append(EvidenceFact(
                        statement=line[:200],
                        confidence=0.9,
                        source_refs=[f"L{layer}:{dk}:instruction"],
                    ))
    return facts, sources
