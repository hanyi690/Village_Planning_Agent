"""EXPLORE orchestration: local place evidence first, optional external second."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from app.contracts.workflow.repair import ExternalSearchRequest, ExternalSearchResult
from app.evidence.model.external_search import ExternalClaimDraft, ExternalSearchEvidence

from .external_search_policy import ExternalSearchDecision, ExternalSearchPolicy


class ExploreOutcome(StrEnum):
    """Typed outcome for a single EXPLORE resolve call."""

    SUCCESS = "success"
    NOT_FOUND = "not_found"
    STALE = "stale"
    STALE_SNAPSHOT = "stale_snapshot"
    QUERY_ERROR = "query_error"
    AMBIGUOUS = "ambiguous"
    INSUFFICIENT_GEOMETRY = "insufficient_geometry"
    EXTERNAL_DENIED = "external_denied"
    EXTERNAL_FAILED = "external_failed"


_OUTCOME_TRACE_TAG = "outcome:"


class ExploreService:
    """Resolve one dimension; local place evidence wins, external is optional.

    External claims only ever become ``EvidenceFact`` records; they never
    create entities, BSMs, geometry, or classification.
    """

    def __init__(
        self,
        session_id: str = "",
        village_name: str = "",
        place_evidence_index: Any | None = None,
        external_port: Any | None = None,
        external_policy: ExternalSearchPolicy | None = None,
    ) -> None:
        self.session_id = session_id
        self.village_name = village_name
        self.place_evidence_index = place_evidence_index
        self.external_port = external_port
        self.external_policy = external_policy or ExternalSearchPolicy()

    async def resolve(
        self,
        dimension_key: str,
        query_purpose: str,
        entity_scope: list[str],
        required_facts: list[str],
        parent_ref: str = "",
    ) -> Any:
        """Return a reused ``EvidenceBundle`` with a typed ``ExploreOutcome``.

        The outcome is stored in the bundle provenance trace and can be read
        back with :func:`outcome_of`.
        """
        from app.modules.schema.contracts.evidence_contracts import EvidenceBundle
        from app.modules.schema.contracts.provenance import Provenance

        bundle = EvidenceBundle(
            request=query_purpose,
            provenance=Provenance(
                source="explore",
                run_id=self.session_id,
                module="evidence",
                trace=[],
            ),
        )
        try:
            local = await self._resolve_local(dimension_key, query_purpose, entity_scope)
        except Exception as exc:
            return self._bundle_with_outcome(
                EvidenceBundle,
                request=query_purpose,
                outcome=ExploreOutcome.QUERY_ERROR,
                message=str(exc),
            )

        self._populate_local(bundle, local, query_purpose)
        local_outcome = self._outcome_of_local(local)
        if local_outcome == ExploreOutcome.SUCCESS:
            return self._with_outcome(bundle, local_outcome)

        external = await self._try_external(
            dimension_key,
            query_purpose,
            entity_scope,
            required_facts,
            parent_ref,
        )
        if external is None:
            return self._with_outcome(bundle, local_outcome)
        decision, evidence = external
        if not decision.allowed:
            return self._with_outcome(bundle, ExploreOutcome.EXTERNAL_DENIED)
        if evidence.retrieval_status != "success" or not evidence.claims:
            return self._with_outcome(bundle, ExploreOutcome.EXTERNAL_FAILED)

        from app.modules.schema.contracts.evidence_contracts import EvidenceFact, EvidenceSource

        bundle.sources.append(
            EvidenceSource(
                source_type="external",
                reference=evidence.provider,
                confidence=0.6,
                retrieved_at="",
            )
        )
        bundle.facts.extend(
            EvidenceFact(
                statement=claim.claim_text,
                confidence=claim.confidence,
                source_refs=[claim.source, claim.url],
                fact_type="external_claim",
                status="needs_review",
            )
            for claim in evidence.claims
        )
        return self._with_outcome(bundle, ExploreOutcome.SUCCESS)

    async def _resolve_local(
        self,
        dimension_key: str,
        query_purpose: str,
        entity_scope: list[str],
    ) -> Any | None:
        if self.place_evidence_index is None:
            return None
        from app.evidence.model.l1_location_fact import L1LocationFact

        mention = (entity_scope[0] if entity_scope else "") or query_purpose
        request = L1LocationFact(
            entity_ref=mention,
            entity_type="location",
            canonical_name=mention,
            source_refs=[dimension_key] if dimension_key else [],
            evidence_refs=[],
            confidence=0.0,
            geometry_ref=None,
        )
        return await self.place_evidence_index.resolve(request)

    def _outcome_of_local(self, local: Any) -> ExploreOutcome:
        if local is None:
            return ExploreOutcome.NOT_FOUND
        reason = str(getattr(local, "unresolved_reason", "") or "")
        status = str(getattr(local, "status", "") or "")
        if status == "resolved":
            return ExploreOutcome.SUCCESS
        if status == "ambiguous":
            return ExploreOutcome.AMBIGUOUS
        if "insufficient_geometry" in reason:
            return ExploreOutcome.INSUFFICIENT_GEOMETRY
        if "stale" in reason:
            return ExploreOutcome.STALE_SNAPSHOT
        if "empty mention" in reason:
            return ExploreOutcome.QUERY_ERROR
        return ExploreOutcome.NOT_FOUND

    def _populate_local(self, bundle: Any, local: Any, query_purpose: str) -> None:
        from app.modules.schema.contracts.evidence_contracts import EvidenceFact, EvidenceSource

        if local is None:
            bundle.unresolved = [query_purpose, ExploreOutcome.NOT_FOUND.value]
            return
        candidates = list(getattr(local, "candidates", None) or [])
        status = str(getattr(local, "status", "") or "")
        mention = str(getattr(local, "mention", "") or query_purpose)
        if status == "resolved" and candidates:
            selected = getattr(local, "selected_entity_ref", "") or str(candidates[0].entity_ref)
            score = float(getattr(candidates[0], "score", 1.0) or 1.0)
            bundle.sources.append(
                EvidenceSource(
                    source_type="local_index",
                    reference=selected,
                    confidence=score,
                    retrieved_at="",
                )
            )
            bundle.facts.append(
                EvidenceFact(
                    statement=f"{mention} resolved to local index entry {selected}",
                    confidence=score,
                    source_refs=[selected],
                    spatial_refs=[selected],
                    fact_type="local_index",
                    status="verified",
                )
            )
        elif status == "ambiguous" and candidates:
            for candidate in candidates:
                bundle.sources.append(
                    EvidenceSource(
                        source_type="local_index",
                        reference=str(getattr(candidate, "entity_ref", "")),
                        confidence=float(getattr(candidate, "score", 0.5) or 0.5),
                        retrieved_at="",
                    )
                )
            bundle.unresolved = [mention, ExploreOutcome.AMBIGUOUS.value]
        else:
            bundle.unresolved = [
                mention,
                str(getattr(local, "unresolved_reason", "") or ExploreOutcome.NOT_FOUND.value),
            ]

    async def _try_external(
        self,
        dimension_key: str,
        query_purpose: str,
        entity_scope: list[str],
        required_facts: list[str],
        parent_ref: str,
    ) -> tuple[ExternalSearchDecision, ExternalSearchEvidence] | None:
        if self.external_port is None:
            return None
        decision = self.external_policy.evaluate(dimension_key, query_purpose)
        evidence = ExternalSearchEvidence(query_purpose=query_purpose)
        if not decision.allowed:
            evidence.retrieval_status = "unresolved"
            evidence.cost = {"decision": str(decision.code)}
            return decision, evidence
        request = ExternalSearchRequest(
            query_purpose=query_purpose,
            entity_scope=list(entity_scope),
            search_mode="light",
            result_limit=5,
            content_mode="summary",
            parent_refs=[parent_ref] if parent_ref else [],
            idempotency_key=f"{self.session_id}:{dimension_key}:{query_purpose}",
        )
        result = await self.external_port.search(request)
        evidence = self._result_to_evidence(result, query_purpose)
        return decision, evidence

    def _result_to_evidence(
        self,
        result: ExternalSearchResult,
        query_purpose: str,
    ) -> ExternalSearchEvidence:
        claims = [
            ExternalClaimDraft(
                claim_text=str(record.get("text", record.get("content", ""))),
                source=str(record.get("source", "")),
                url=str(record.get("url", "")),
                published_at=str(record.get("published_at", "")),
                confidence=float(record.get("confidence", 0.5) or 0.5),
            )
            for record in result.result_records
            if record.get("text") or record.get("content")
        ]
        return ExternalSearchEvidence(
            claims=claims,
            provider=result.provider,
            request_id=result.request_id,
            query_purpose=query_purpose,
            retrieval_status=result.retrieval_status,
            latency_ms=result.latency_ms,
            cost=result.cost,
        )

    def _with_outcome(self, bundle: Any, outcome: ExploreOutcome) -> Any:
        trace = list(getattr(bundle.provenance, "trace", None) or []) or []
        trace.append(f"{_OUTCOME_TRACE_TAG}{outcome.value}")
        if bundle.provenance is not None:
            bundle.provenance.trace = trace
        elif hasattr(bundle, "unresolved"):
            bundle.unresolved = list(bundle.unresolved or []) + [outcome.value]
        return bundle

    def _bundle_with_outcome(
        self,
        bundle_cls: Any,
        *,
        request: str,
        outcome: ExploreOutcome,
        message: str,
    ) -> Any:
        from app.modules.schema.contracts.provenance import Provenance

        bundle = bundle_cls(request=request)
        bundle.unresolved = [message, outcome.value]
        bundle.provenance = Provenance(
            source="explore",
            run_id=self.session_id,
            module="evidence",
            trace=[f"{_OUTCOME_TRACE_TAG}{outcome.value}"],
        )
        return bundle


def outcome_of(bundle: Any) -> ExploreOutcome:
    """Read the typed outcome back from an EvidenceBundle provenance trace."""
    if bundle is None:
        return ExploreOutcome.QUERY_ERROR
    trace = list(getattr(bundle.provenance, "trace", None) or []) or []
    for tag in reversed(trace):
        if isinstance(tag, str) and tag.startswith(_OUTCOME_TRACE_TAG):
            return ExploreOutcome(tag[len(_OUTCOME_TRACE_TAG):])
    if getattr(bundle, "facts", None):
        return ExploreOutcome.SUCCESS
    return ExploreOutcome.NOT_FOUND


__all__ = ["ExploreOutcome", "ExploreService", "outcome_of"]
