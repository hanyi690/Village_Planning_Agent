"""Candidate Proposal Engine — propose classification candidates, never auto-decide.

This engine replaces the old "resolve_mapping" concept. The key semantic difference:
  - "mapping" implies automatic destination selection
  - "proposal" implies returning candidates for human decision

Decision ladder (L0/L1/L3):
  L0: runtime candidate set has one unconditional entry → auto
  L1: Condition.evaluate() uniquely hits → rule_based
  L3: decision: manual → manual (all candidates returned)
"""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from .expr_eval import Condition, MappingContext, condition_from_yaml
from .loader import MappingTable
from app.contracts.llm.closed_set_contracts import CandidateDescriptor, candidate_set_digest
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


class ClassificationProposal(BaseModel):
    """Candidate proposal for cross-system code classification.

    NOT a mapping result — a list of suggestions for the planner to choose from.
    """

    model_config = ConfigDict(extra="forbid")

    source_code: str = ""
    source_domain: str = ""
    target_domain: str = ""
    suggested_code: str = ""
    confidence: str = "exact"  # "exact" | "conditional" | "ambiguous"
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    needs_human_decision: bool = False
    rationale: str = ""
    candidate_set_digest: str = ""

    def __str__(self) -> str:
        if self.confidence == "exact":
            return f"{self.source_code} → {self.suggested_code} (exact)"
        if self.needs_human_decision:
            codes = [a.get("candidate", "?") for a in self.alternatives]
            return f"{self.source_code} → candidates: {codes} (NEEDS DECISION)"
        return f"{self.source_code} → {self.suggested_code} ({self.confidence})"


class Resolution(BaseModel):
    """Decision ladder result — L0/L1/L2/L3."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["auto", "rule", "llm", "manual", "unmapped"] = "unmapped"
    chosen_code: str = ""
    candidates: list[dict[str, Any]] = Field(default_factory=list)
    confidence: str = "exact"
    rationale: str = ""
    disambiguation_ctx: Optional[Dict[str, Any]] = None
    candidate_set_digest: str = ""

    @classmethod
    def needs_llm(cls, ctx: "DisambiguationContext") -> "Resolution":
        from .disambiguation import DisambiguationContext
        candidates_list = [
            {"code": c.code, "when": c.when, "surviving_evidence": c.surviving_evidence}
            for c in ctx.candidates
        ]
        return cls(
            kind="llm",
            candidates=candidates_list,
            confidence="conditional",
            rationale=f"Multiple survivors ({len(ctx.candidates)}), LLM disambiguation required",
            disambiguation_ctx=ctx.model_dump(mode="json"),
            candidate_set_digest=ctx.candidate_set_digest,
        )


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

        decision = str(entry.get("decision") or "").strip()
        targets = [
            dict(target)
            for target in (entry.get("targets") or [])
            if isinstance(target, dict)
        ]
        candidates = [
            {"code": str(target.get("code") or "").strip(), "when": target.get("when")}
            for target in targets
        ]
        candidate_codes = [item["code"] for item in candidates]
        if not decision:
            return Resolution(
                kind="unmapped",
                candidates=candidates,
                confidence="low",
                rationale="Mapping decision mode is missing",
            )
        if (
            not candidates
            or any(not code for code in candidate_codes)
            or len(set(candidate_codes)) != len(candidate_codes)
        ):
            return Resolution(
                kind="unmapped",
                candidates=candidates,
                confidence="low",
                rationale="Mapping candidate set is empty, duplicated, or contains an invalid code",
            )

        candidate_digest = candidate_set_digest(
            [
                CandidateDescriptor(
                    candidate_id=item["code"],
                    kind="classification_code",
                    label=item["code"],
                    metadata={"when": item["when"]},
                )
                for item in candidates
            ]
        )

        if len(candidates) == 1 and candidates[0]["when"] is None:
            return Resolution(
                kind="auto",
                chosen_code=candidates[0]["code"],
                candidates=candidates,
                confidence="exact",
                rationale="Runtime candidate set contains one unconditional candidate",
                candidate_set_digest=candidate_digest,
            )

        if ctx is None:
            return Resolution(
                kind="manual",
                chosen_code="",
                candidates=candidates,
                confidence="conditional",
                rationale="No context provided, cannot disambiguate",
                candidate_set_digest=candidate_digest,
            )

        hits = []
        for t in candidates:
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
                kind="manual",
                chosen_code="",
                candidates=candidates,
                confidence="conditional",
                rationale="No runtime condition matched; explicit decision required",
                candidate_set_digest=candidate_digest,
            )

        if len(hits) == 1:
            return Resolution(
                kind="rule",
                chosen_code=str(hits[0]["code"]),
                candidates=candidates,
                confidence="conditional",
                rationale="Context uniquely matched",
                candidate_set_digest=candidate_digest,
            )

        if decision == "manual":
            return Resolution(
                kind="manual",
                chosen_code="",
                candidates=hits,
                confidence="conditional",
                rationale=f"Multiple candidates ({len(hits)}), manual decision required",
                candidate_set_digest=candidate_digest,
            )

        from .disambiguation import Candidate, DisambiguationContext
        candidates = [
            Candidate(
                code=str(t.get("code", "")),
                when=t.get("when"),
                surviving_evidence=[],
            )
            for t in hits
        ]
        ctx_obj = DisambiguationContext(
            source_system=source_system,
            source_code=source_code,
            parcel_attrs=ctx.parcel_attrs if ctx else {},
            candidates=candidates,
        )
        return Resolution.needs_llm(ctx_obj)

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
                "when": c.get("when"),
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
            candidate_set_digest=resolution.candidate_set_digest,
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
