"""Candidate Proposal Engine — propose classification candidates, never auto-decide.

This engine replaces the old "resolve_mapping" concept. The key semantic difference:
  - "mapping" implies automatic destination selection
  - "proposal" implies returning candidates for human decision

Decision ladder (L0/L1/L3):
  L0: targets list has single entry → auto (default)
  L1: Condition.evaluate() uniquely hits → rule_based
  L3: decision: manual → manual (all candidates returned)
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel

from .expr_eval import Condition, MappingContext, condition_from_yaml
from .loader import MappingTable
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ClassificationProposal(BaseModel):
    """Candidate proposal for cross-system code classification.

    NOT a mapping result — a list of suggestions for the planner to choose from.
    """

    source_code: str = ""
    source_domain: str = ""
    target_domain: str = ""
    suggested_code: str = ""
    confidence: str = "exact"  # "exact" | "conditional" | "ambiguous"
    alternatives: list[dict[str, Any]] = []
    needs_human_decision: bool = False
    rationale: str = ""

    def __str__(self) -> str:
        if self.confidence == "exact":
            return f"{self.source_code} → {self.suggested_code} (exact)"
        if self.needs_human_decision:
            codes = [a.get("candidate", "?") for a in self.alternatives]
            return f"{self.source_code} → candidates: {codes} (NEEDS DECISION)"
        return f"{self.source_code} → {self.suggested_code} ({self.confidence})"


class Resolution(BaseModel):
    """Decision ladder result — L0/L1/L3."""

    kind: Literal["auto", "rule", "manual", "unmapped"] = "unmapped"
    chosen_code: str = ""
    candidates: list[dict[str, Any]] = []
    confidence: str = "exact"
    rationale: str = ""


class CandidateEngine:
    """Propose classification candidates — never auto-decide.

    Usage:
        engine = CandidateEngine(center)
        resolution = engine.resolve("sddlbm", "ydyhfldm", "2122", ctx)
        if resolution.kind == "manual":
            return resolution.candidates
    """

    def __init__(self, center: Any = None):
        self._center = center

    def _ensure_center(self):
        if self._center is None:
            from .loader import get_center
            self._center = get_center()

    def resolve(
        self,
        source_system: str,
        target_system: str,
        source_code: str,
        ctx: Optional[MappingContext] = None,
    ) -> Resolution:
        self._ensure_center()
        source_code = str(source_code).strip()

        mapping_key = f"{source_system}_to_{target_system}"
        try:
            table = self._center.get_mapping(mapping_key)
        except KeyError:
            return Resolution(
                kind="unmapped",
                rationale=f"No mapping table '{mapping_key}' found",
            )

        entry = table.propose(source_code)
        if entry is None:
            return Resolution(
                kind="unmapped",
                rationale=f"No entry for '{source_code}' in {mapping_key}",
            )

        decision = entry.get("decision", "auto")
        targets = entry.get("targets", [])
        default = entry.get("default", "")

        if decision == "auto" or len(targets) <= 1:
            return Resolution(
                kind="auto",
                chosen_code=default,
                candidates=targets,
                confidence="exact",
                rationale="Single target, auto-resolved",
            )

        if ctx is None:
            candidates = [{"code": t.get("code", ""), "when": t.get("when")} for t in targets]
            return Resolution(
                kind="manual",
                chosen_code=default,
                candidates=candidates,
                confidence="conditional",
                rationale="No context provided, cannot disambiguate",
            )

        hits = []
        for t in targets:
            when_data = t.get("when")
            if when_data is None:
                hits.append(t)
                continue
            try:
                cond = condition_from_yaml(when_data)
                if cond.evaluate(ctx):
                    hits.append(t)
            except Exception:
                logger.warning("Condition evaluation failed for %s: %s", source_code, when_data)
                continue

        if len(hits) == 0:
            return Resolution(
                kind="auto",
                chosen_code=default,
                candidates=targets,
                confidence="conditional",
                rationale="No condition matched, using default",
            )

        if len(hits) == 1:
            return Resolution(
                kind="rule",
                chosen_code=str(hits[0].get("code", default)),
                candidates=targets,
                confidence="conditional",
                rationale="Context uniquely matched",
            )

        if decision == "manual":
            return Resolution(
                kind="manual",
                chosen_code=default,
                candidates=hits,
                confidence="conditional",
                rationale=f"Multiple candidates ({len(hits)}), manual decision required",
            )

        return Resolution(
            kind="manual",
            chosen_code=default,
            candidates=hits,
            confidence="conditional",
            rationale="Multiple survivors after context evaluation",
        )

    def propose(
        self,
        source_domain: str,
        target_domain: str,
        source_code: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ClassificationProposal:
        self._ensure_center()
        source_code = str(source_code).strip()

        ctx = None
        if context:
            ctx = MappingContext(parcel_attrs=context)

        resolution = self.resolve(source_domain, target_domain, source_code, ctx)

        candidates_list = []
        for c in resolution.candidates:
            candidates_list.append({
                "candidate": c.get("code", c.get("candidate", "")),
                "when": str(c.get("when", "默认")),
            })

        needs_decision = resolution.kind in ("manual", "unmapped")
        return ClassificationProposal(
            source_code=source_code,
            source_domain=source_domain,
            target_domain=target_domain,
            suggested_code=resolution.chosen_code,
            confidence=resolution.confidence,
            alternatives=candidates_list,
            needs_human_decision=needs_decision,
            rationale=resolution.rationale,
        )


# Module-level singleton
_engine: Optional[CandidateEngine] = None


def get_candidate_engine() -> CandidateEngine:
    global _engine
    if _engine is None:
        _engine = CandidateEngine()
    return _engine


__all__ = [
    "ClassificationProposal",
    "Resolution",
    "CandidateEngine",
    "get_candidate_engine",
]