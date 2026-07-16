"""Candidate Proposal Engine — propose classification candidates, never auto-decide.

This engine replaces the old "resolve_mapping" concept. The key semantic difference:
  - "mapping" implies automatic destination selection
  - "proposal" implies returning candidates for human decision

When a source code maps to exactly one target (一一对应), the proposal is confident.
When a source code has multiple possible targets (一对多), the engine returns ALL
candidates with their conditions, and sets needs_human_decision=True.

The Agent is forbidden from auto-selecting when needs_human_decision=True.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ClassificationProposal:
    """Candidate proposal for cross-system code classification.

    NOT a mapping result — a list of suggestions for the planner to choose from.
    """

    source_code: str
    source_domain: str
    target_domain: str
    suggested_code: str
    confidence: str              # "exact" | "conditional" | "ambiguous"
    alternatives: List[Dict[str, Any]] = field(default_factory=list)
    needs_human_decision: bool = False
    rationale: str = ""

    def __str__(self) -> str:
        if self.confidence == "exact":
            return f"{self.source_code} → {self.suggested_code} (exact)"
        if self.needs_human_decision:
            codes = [a.get("candidate", "?") for a in self.alternatives]
            return f"{self.source_code} → candidates: {codes} (NEEDS DECISION)"
        return f"{self.source_code} → {self.suggested_code} ({self.confidence})"


class CandidateEngine:
    """Propose classification candidates — never auto-decide.

    Usage:
        engine = CandidateEngine(center)
        proposal = engine.propose("sddlbm", "ydyhfldm", "2122")
        if proposal.needs_human_decision:
            # Return candidates to planner, do NOT auto-select
            return proposal.alternatives
    """

    def __init__(self, center: Any = None):
        self._center = center

    def _ensure_center(self):
        if self._center is None:
            from .loader import get_center
            self._center = get_center()

    def propose(
        self,
        source_domain: str,
        target_domain: str,
        source_code: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ClassificationProposal:
        self._ensure_center()
        source_code = str(source_code).strip()

        # Try cross-system proposal tables first
        proposal_key = f"{source_domain}_to_{target_domain}"
        try:
            table = self._center.get_proposal(proposal_key)
            return self._propose_from_table(table, source_code, source_domain, target_domain, context)
        except KeyError:
            pass

        # Try direct cross-reference within a dictionary
        # e.g., ghytbm dictionary has "ydyhfldm" and "vne" fields
        return self._propose_from_cross_reference(
            source_domain, target_domain, source_code, context
        )

    def _propose_from_table(
        self,
        table: Any,
        source_code: str,
        source_domain: str,
        target_domain: str,
        context: Optional[Dict[str, Any]],
    ) -> ClassificationProposal:
        entry = table.propose(source_code)
        if entry is None:
            return ClassificationProposal(
                source_code=source_code,
                source_domain=source_domain,
                target_domain=target_domain,
                suggested_code="",
                confidence="ambiguous",
                needs_human_decision=True,
                rationale=f"No candidate found for {source_code} in {source_domain}→{target_domain}",
            )

        conversion_type = entry.get("conversion_type", "")
        needs_decision = entry.get("needs_human_decision", False)
        alternatives = entry.get("alternatives", [])

        if conversion_type == "一一对应" and not needs_decision:
            return ClassificationProposal(
                source_code=source_code,
                source_domain=source_domain,
                target_domain=target_domain,
                suggested_code=str(entry.get("candidate", "")),
                confidence="exact",
                needs_human_decision=False,
                rationale="One-to-one correspondence",
            )

        # 一对多 or needs_human_decision=True
        # Try context-based narrowing if context provided
        if context and alternatives:
            matched = self._match_context(alternatives, context)
            if matched and len(matched) == 1:
                return ClassificationProposal(
                    source_code=source_code,
                    source_domain=source_domain,
                    target_domain=target_domain,
                    suggested_code=str(matched[0].get("candidate", "")),
                    confidence="conditional",
                    alternatives=alternatives,
                    needs_human_decision=False,
                    rationale=f"Context matched: {context}",
                )

        # Return all candidates for human decision
        all_candidates = [{"candidate": entry.get("candidate", ""), "when": "默认"}]
        all_candidates.extend(alternatives)

        return ClassificationProposal(
            source_code=source_code,
            source_domain=source_domain,
            target_domain=target_domain,
            suggested_code=str(entry.get("candidate", "")),
            confidence="conditional" if conversion_type == "一对多" else "ambiguous",
            alternatives=all_candidates,
            needs_human_decision=True,
            rationale=f"Multiple candidates ({conversion_type}), planner must decide",
        )

    def _propose_from_cross_reference(
        self,
        source_domain: str,
        target_domain: str,
        source_code: str,
        context: Optional[Dict[str, Any]],
    ) -> ClassificationProposal:
        """Try to find a cross-reference field in the source dictionary."""
        try:
            source_dict = self._center.get(source_domain)
        except KeyError:
            return ClassificationProposal(
                source_code=source_code,
                source_domain=source_domain,
                target_domain=target_domain,
                suggested_code="",
                confidence="ambiguous",
                needs_human_decision=True,
                rationale=f"Source domain '{source_domain}' not found",
            )

        entry = source_dict.lookup(source_code)
        if entry is None:
            return ClassificationProposal(
                source_code=source_code,
                source_domain=source_domain,
                target_domain=target_domain,
                suggested_code="",
                confidence="ambiguous",
                needs_human_decision=True,
                rationale=f"Code '{source_code}' not found in {source_domain}",
            )

        # Check if the target domain is a field in the source entry
        target_field_map = {
            "ydyhfldm": "ydyhfldm",
            "vne": "vne",
            "zone_type": "zone_type",
            "planning_zone": "planning_zone",
            "primary_zone": "primary_zone",
        }

        field_name = target_field_map.get(target_domain, target_domain)
        target_value = entry.get(field_name)

        if target_value:
            return ClassificationProposal(
                source_code=source_code,
                source_domain=source_domain,
                target_domain=target_domain,
                suggested_code=str(target_value),
                confidence="exact",
                needs_human_decision=False,
                rationale=f"Cross-reference field '{field_name}' in {source_domain}",
            )

        return ClassificationProposal(
            source_code=source_code,
            source_domain=source_domain,
            target_domain=target_domain,
            suggested_code="",
            confidence="ambiguous",
            needs_human_decision=True,
            rationale=f"No '{field_name}' field for code '{source_code}' in {source_domain}",
        )

    @staticmethod
    def _match_context(
        alternatives: List[Dict[str, Any]], context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Try to narrow alternatives using context keywords."""
        matched = []
        context_text = " ".join(str(v) for v in context.values()).lower()
        for alt in alternatives:
            when = str(alt.get("when", "")).lower()
            if when and any(kw in context_text for kw in when.split()):
                matched.append(alt)
        return matched


# Module-level singleton
_engine: Optional[CandidateEngine] = None


def get_candidate_engine() -> CandidateEngine:
    global _engine
    if _engine is None:
        _engine = CandidateEngine()
    return _engine


__all__ = [
    "ClassificationProposal",
    "CandidateEngine",
    "get_candidate_engine",
]
