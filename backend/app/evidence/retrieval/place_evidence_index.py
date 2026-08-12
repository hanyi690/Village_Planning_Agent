"""PlaceEvidenceIndex adapter over the existing SpatialResolver.

The resolution contract is ``PlaceResolutionResult`` from
``app.contracts.ports.place_resolution_contracts``; this service only
maps the SpatialResolver output onto that contract. It never auto-picks the
first candidate, and a fuzzy short-name match can only ever yield ``ambiguous``.
"""

from __future__ import annotations

from typing import Any

from app.evidence.model.base import JsonObject
from app.evidence.model.place_resolution import (
    PlaceResolutionCandidate,
    PlaceResolutionResult,
    PlaceResolutionStatus,
)


class PlaceEvidenceIndexService:
    """Thin typed adapter implementing ``app.contracts.ports.place_evidence``."""

    def __init__(self, context: Any) -> None:
        self.context = context

    async def resolve(self, request: object) -> PlaceResolutionResult:
        """Resolve one place mention to a typed, evidence-scored result."""
        from app.spatial.grounding.resolver import SpatialResolver

        mention = self._mention_of(request)
        if not mention:
            return self._unresolved(request, "empty mention")

        resolver = SpatialResolver(self.context)
        resolved = resolver.resolve_text(mention)
        return self._map(resolved, request, mention)

    def _mention_of(self, request: object) -> str:
        if request is None:
            return ""
        return str(
            getattr(request, "mention", "")
            or getattr(request, "name", "")
            or getattr(request, "canonical_name", "")
            or getattr(request, "entity_ref", "")
            or ""
        ).strip()

    def _map(
        self,
        resolved: Any,
        request: object,
        mention: str,
    ) -> PlaceResolutionResult:
        from app.spatial.grounding.grounding import ResolvedSpatialDescription

        if isinstance(resolved, ResolvedSpatialDescription):
            return self._map_description(resolved, request, mention)
        return self._unresolved(request, "unsupported resolver output")

    def _map_description(
        self,
        resolved: Any,
        request: object,
        mention: str,
    ) -> PlaceResolutionResult:
        bsms = list(resolved.candidate_bsms or [])
        query_path = resolved.query_path or ""
        trace: list[JsonObject] = [
            {
                "path": query_path,
                "confidence": resolved.confidence,
                "unresolved_reason": resolved.unresolved_reason or "",
            }
        ]

        if resolved.unresolved_reason:
            return PlaceResolutionResult(
                mention=mention,
                normalized_name=mention,
                status="unresolved",
                candidates=[],
                query_trace=trace,
                unresolved_reason=str(PlaceResolutionStatus.UNRESOLVED),
            )

        if len(bsms) > 1:
            return PlaceResolutionResult(
                mention=mention,
                normalized_name=mention,
                status="ambiguous",
                candidates=[self._candidate(bsm, query_path) for bsm in bsms],
                query_trace=trace,
                unresolved_reason=str(PlaceResolutionStatus.AMBIGUOUS),
            )

        if len(bsms) == 1:
            if "fuzzy" in query_path or "fuzzy" in (resolved.unresolved_reason or ""):
                # Short-name fuzzy match must never auto-resolve.
                return PlaceResolutionResult(
                    mention=mention,
                    normalized_name=mention,
                    status="ambiguous",
                    candidates=[self._candidate(bsms[0], query_path)],
                    query_trace=trace,
                    unresolved_reason=str(PlaceResolutionStatus.AMBIGUOUS),
                )
            if not resolved.candidate_bbox and not bsms[0]:
                return PlaceResolutionResult(
                    mention=mention,
                    normalized_name=mention,
                    status="unresolved",
                    candidates=[],
                    query_trace=trace,
                    unresolved_reason=str(PlaceResolutionStatus.INSUFFICIENT_GEOMETRY),
                )
            return PlaceResolutionResult(
                mention=mention,
                normalized_name=mention,
                status="resolved",
                selected_entity_ref=bsms[0],
                candidates=[self._candidate(bsms[0], query_path)],
                query_trace=trace,
            )

        return self._unresolved(request, str(PlaceResolutionStatus.UNRESOLVED))

    def _candidate(self, bsm: str, query_path: str) -> PlaceResolutionCandidate:
        return PlaceResolutionCandidate(
            entity_ref=bsm,
            entity_type="location",
            canonical_name=bsm,
            geometry_ref=bsm,
            score=1.0 if "fuzzy" not in query_path else 0.5,
            evidence={
                "exact_canonical_alias": 1.0 if "fuzzy" not in query_path else 0.0,
                "fuzzy_short_name": 1.0 if "fuzzy" in query_path else 0.0,
            },
        )

    def _unresolved(self, request: object, reason: str) -> PlaceResolutionResult:
        return PlaceResolutionResult(
            mention=self._mention_of(request),
            normalized_name=self._mention_of(request),
            status="unresolved",
            candidates=[],
            unresolved_reason=reason,
        )


__all__ = ["PlaceEvidenceIndexService"]
