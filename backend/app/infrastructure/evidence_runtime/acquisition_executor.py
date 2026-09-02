"""Runtime-owned acquisition lineage for the Evidence vertical slice.

The executor is deliberately below ``EvidenceApplication``.  A retriever
reports its terminal outcome here; the application may validate and aggregate
the resulting immutable records, but it does not derive an attempt from a
query trace after the fact.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Literal

from app.contracts.evidence.acquisition_contracts import (
    EvidenceAcquisitionReceipt,
    EvidenceObservationSnapshot,
)
from app.contracts.evidence.evidence_contracts import EvidenceFact, EvidenceSource
from app.contracts.evidence.provider_attempt import (
    EvidenceObservationRecord,
    ProviderAttempt,
    ProviderAttemptStatus,
)
from app.contracts.evidence.query_plan_contracts import (
    EvidenceProviderRoute,
    EvidenceQueryPlanV1,
)
from app.contracts.evidence.acquisition_contracts import ProviderPageRecord


_LOCAL_KINDS = {
    "data_catalog": "local_data",
    "current_world": "current_world",
    "local_text": "source_span",
    "report": "source_span",
    "rag": "source_span",
    "artifact": "frozen_cache",
    "integrity": "local_data",
    "frozen_cache": "frozen_cache",
}
AcquisitionAttemptKind = Literal[
    "local_data",
    "current_world",
    "source_span",
    "frozen_cache",
    "external_provider",
]


@dataclass(frozen=True)
class AcquisitionRouteResult:
    """Terminal output of one executed route."""

    route_ref: str
    attempt: ProviderAttempt
    page_records: tuple[ProviderPageRecord, ...] = ()
    observations: tuple[EvidenceObservationRecord, ...] = ()
    raw_response_refs: tuple[str, ...] = ()


def attempt_kind_for_route(route: EvidenceProviderRoute) -> str:
    """Map route authority to the acquisition kind used in the audit spine."""

    if route.provider in _LOCAL_KINDS:
        return _LOCAL_KINDS[route.provider]
    if route.source_family in _LOCAL_KINDS:
        return _LOCAL_KINDS[route.source_family]
    if route.retriever == "external":
        return "external_provider"
    return "external_provider"


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _string_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(item) for item in value if str(item))
    if not isinstance(value, str) or not value.strip():
        return ()
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return ()
    return _string_tuple(parsed)


def _attempt_ref(plan: EvidenceQueryPlanV1, route: EvidenceProviderRoute) -> str:
    return "evidence.attempt." + _digest({
        "plan": plan.plan_fingerprint,
        "route": route.route_ref,
    })[:24]


def _source_for(fact: EvidenceFact, source_by_ref: dict[str, EvidenceSource]) -> EvidenceSource | None:
    for source_ref in fact.source_refs:
        source = source_by_ref.get(str(source_ref))
        if source is not None:
            return source
    return None


def _observation_kind(
    route: EvidenceProviderRoute,
    fact: EvidenceFact,
    kind: str | None = None,
) -> str:
    kind = kind or attempt_kind_for_route(route)
    if kind == "local_data":
        return "DATA_SOURCE_RECORD"
    if kind == "current_world":
        if fact.fact_type == "world_representation" or fact.fields.get("representation_ref"):
            return "CURRENT_WORLD_REPRESENTATION"
        return "CURRENT_WORLD_ENTITY"
    if kind == "source_span":
        return "SOURCE_SPAN"
    if kind == "frozen_cache":
        return "EXTERNAL_OBSERVATION"
    return "EXTERNAL_OBSERVATION"


def _observation(
    plan: EvidenceQueryPlanV1,
    route: EvidenceProviderRoute,
    attempt: ProviderAttempt,
    fact: EvidenceFact,
    source: EvidenceSource | None,
    *,
    candidate_ref: str = "",
    representation_ref: str = "",
    resource_ref: str = "",
    attempt_kind: str | None = None,
    provider: str | None = None,
) -> EvidenceObservationRecord:
    fields = dict(fact.fields or {})
    source_ref = str(fact.source_refs[0]) if fact.source_refs else ""
    statement = str(fact.statement or "")
    content_digest = _digest({
        "statement": statement,
        "fields": fields,
        "source_refs": list(fact.source_refs),
        "spatial_refs": list(fact.spatial_refs),
    })
    observation_ref = "evidence.observation." + _digest({
        "plan": plan.plan_fingerprint,
        "route": route.route_ref,
        "fact": fact.fact_id,
        "source": source_ref,
        "candidate": candidate_ref,
    })[:24]
    authority = str(getattr(source, "authority", "advisory") or "advisory")
    geometry_authority = str(
        fields.get("geometry_authority")
        or getattr(source, "authority", "none")
        if attempt_kind_for_route(route) == "local_data"
        else "none"
    )
    external_kind = attempt_kind_for_route(route) in {
        "frozen_cache",
        "external_provider",
    }
    world_entity_ref = str(fields.get("entity_ref") or fields.get("world_entity_ref") or "")
    return EvidenceObservationRecord(
        observation_ref=observation_ref,
        query_plan_ref=plan.query_plan_ref,
        query_ref=route.route_ref,
        attempt_ref=attempt.attempt_ref,
        route_ref=route.route_ref,
        provider=provider or route.provider,
        page_ref=attempt.page_record_refs[0] if attempt.page_record_refs else "",
        observation_kind=_observation_kind(route, fact, attempt_kind),
        source_family=route.source_family,
        subject_refs=route.entity_scope,
        source_ref=source_ref,
        source_refs=tuple(dict.fromkeys(str(item) for item in fact.source_refs if str(item))),
        source_record_ref=(source_ref if attempt_kind == "local_data" else ""),
        world_entity_ref=world_entity_ref,
        representation_ref=(
            ""
            if external_kind
            else representation_ref or str(fields.get("representation_ref") or "")
        ),
        resource_ref=(
            ""
            if external_kind
            else resource_ref or (str(fact.spatial_refs[0]) if fact.spatial_refs else "")
        ),
        locator=str(fact.source_locator or fact.evidence_span or ""),
        statement=statement,
        predicate=str(fields.get("predicate") or fact.fact_type or "statement"),
        value=fields.get("value", statement),
        candidate_ref=candidate_ref,
        valid_time=str(fields.get("valid_time") or ""),
        source_authority=authority,
        geometry_authority=geometry_authority,
        legal_authority=str(fields.get("legal_authority") or "none"),
        raw_payload_ref=str(fields.get("raw_payload_ref") or ""),
        content_digest=content_digest,
        origin_provider=str(fields.get("origin_provider") or fields.get("provider") or ""),
        origin_record_ref=str(fields.get("origin_record_ref") or fields.get("observation_id") or ""),
        origin_attempt_ref=str(fields.get("origin_attempt_ref") or ""),
        origin_status=str(fields.get("origin_status") or ""),
        origin_query_fingerprint=str(fields.get("origin_query_fingerprint") or ""),
        origin_page_refs=_string_tuple(fields.get("origin_page_refs")),
        cache_snapshot_ref=str(fields.get("cache_snapshot_ref") or ""),
        cache_digest=str(fields.get("cache_digest") or ""),
        locator_crs=str(
            fields.get("locator_crs")
            or fields.get("coordinate_target_crs")
            or ""
        ),
        observed_name=statement[:200],
        observed_value=statement,
        source_digest=str(getattr(source, "snapshot_ref", "") or content_digest),
    )


class AcquisitionRouteExecutor:
    """Build typed route results from explicit retriever terminal outcomes."""

    def __init__(self, plan: EvidenceQueryPlanV1, *, stage: str = "EVIDENCE") -> None:
        self.plan = plan
        self.stage = stage or "EVIDENCE"

    def complete_route(
        self,
        route: EvidenceProviderRoute,
        *,
        status: ProviderAttemptStatus,
        facts: Iterable[EvidenceFact] = (),
        sources: Iterable[EvidenceSource] = (),
        reason_code: str = "",
        response_digest: str = "",
        raw_response_ref: str = "",
        latency_ms: float = 0.0,
        retryable: bool = False,
        page_records: Iterable[ProviderPageRecord] = (),
        candidate_refs: Iterable[Any] = (),
        attempt_kind: AcquisitionAttemptKind | None = None,
        metadata: dict[str, Any] | None = None,
        provider_override: str | None = None,
    ) -> AcquisitionRouteResult:
        facts = tuple(facts)
        sources = tuple(sources)
        source_by_ref = {str(item.reference): item for item in sources}
        item_count = len(facts) or len(sources)
        kind = attempt_kind or attempt_kind_for_route(route)
        provider = provider_override or route.provider
        pages = tuple(page_records)
        if pages and kind != "external_provider":
            raise ValueError("local and frozen-cache acquisition cannot contain page records")
        if (
            not pages
            and kind == "external_provider"
            and status not in {"NOT_ATTEMPTED", "RUNNING"}
        ):
            page_ref = "evidence.page." + _digest({
                "attempt": _attempt_ref(self.plan, route),
                "response": response_digest,
            })[:24]
            pages = (ProviderPageRecord(
                page_ref=page_ref,
                attempt_ref=_attempt_ref(self.plan, route),
                query_fingerprint=self.plan.plan_fingerprint,
                provider=route.provider,
                item_count=item_count,
                response_digest=response_digest,
                raw_response_ref=raw_response_ref,
                attempt_status=status,
                termination_reason=(
                    "provider_exhausted"
                    if status in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}
                    else "failed"
                ),
            ),)
        attempt = ProviderAttempt(
            attempt_ref=_attempt_ref(self.plan, route),
            attempt_kind=kind,
            query_plan_ref=self.plan.query_plan_ref,
            query_ref=route.route_ref,
            route_ref=route.route_ref,
            provider=provider,
            provider_name=(route.provider if kind == "external_provider" else ""),
            stage=self.stage,
            query_fingerprint=self.plan.plan_fingerprint,
            requirement_refs=self.plan.requirement_refs,
            status=status,
            reason_code=reason_code or (
                "bounded_query_complete"
                if kind in _LOCAL_KINDS.values()
                and status in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}
                else status.lower()
            ),
            retryable=retryable,
            item_count=item_count,
            response_digest=response_digest or _digest({
                "route": route.route_ref,
                "status": status,
                "facts": [item.fact_id for item in facts],
                "sources": [item.reference for item in sources],
            }),
            raw_response_ref=raw_response_ref,
            raw_response_refs=((raw_response_ref,) if raw_response_ref else ()),
            latency_ms=latency_ms,
            page_record_refs=tuple(item.page_ref for item in pages),
            pages_completed=len(pages),
            acquisition_digest=_digest({
                "attempt": _attempt_ref(self.plan, route),
                "facts": [item.fact_id for item in facts],
                "sources": [item.reference for item in sources],
            }),
            metadata={
                "completion": (
                    "bounded_query_complete"
                    if kind in _LOCAL_KINDS.values()
                    else "provider_page_complete"
                ),
                **dict(metadata or {}),
            },
        )
        observations = [
            _observation(
                self.plan,
                route,
                attempt,
                fact,
                _source_for(fact, source_by_ref),
                attempt_kind=kind,
                provider=provider,
            )
            for fact in facts
            if fact.source_refs
        ]
        for candidate in candidate_refs:
            identity = getattr(candidate, "identity", None)
            source_feature_ref = str(getattr(identity, "source_feature_id", "") or "")
            source_dataset_ref = str(getattr(identity, "source_dataset_ref", "") or "")
            source_ref = (
                f"data:{source_dataset_ref}:{source_feature_ref}"
                if source_dataset_ref and source_feature_ref
                else source_feature_ref
            )
            if not source_feature_ref:
                continue
            synthetic = EvidenceFact(
                statement=f"DATA representation {source_feature_ref} is available",
                fact_type="data_representation",
                source_refs=[source_ref],
                spatial_refs=[str(getattr(candidate, "resource_ref", "") or "")],
                fields={"representation_ref": str((getattr(candidate, "representation_refs", ()) or ())[0] if getattr(candidate, "representation_refs", ()) else "")},
            )
            observations.append(_observation(
                self.plan,
                route,
                attempt,
                synthetic,
                source_by_ref.get(source_ref),
                candidate_ref=source_feature_ref,
                representation_ref=str((getattr(candidate, "representation_refs", ()) or ())[0] if getattr(candidate, "representation_refs", ()) else ""),
                resource_ref=str(getattr(candidate, "resource_ref", "") or ""),
                attempt_kind=kind,
                provider=provider,
            ))
        return AcquisitionRouteResult(
            route_ref=route.route_ref,
            attempt=attempt,
            page_records=pages,
            observations=tuple(observations),
            raw_response_refs=((raw_response_ref,) if raw_response_ref else ()),
        )

    def finalize(
        self,
        route_results: Iterable[AcquisitionRouteResult],
    ) -> tuple[
        tuple[ProviderAttempt, ...],
        tuple[ProviderPageRecord, ...],
        EvidenceObservationSnapshot,
        EvidenceAcquisitionReceipt,
    ]:
        results = tuple(route_results)
        attempts = tuple(item.attempt for item in results)
        pages = tuple(page for item in results for page in item.page_records)
        observations = tuple(obs for item in results for obs in item.observations)
        required = tuple(item.route_ref for item in self.plan.provider_routes if item.required_for_acquisition)
        completed = tuple(
            item.route_ref for item in self.plan.provider_routes
            if item.required_for_acquisition
            and next((row.attempt.status for row in results if row.route_ref == item.route_ref), "NOT_ATTEMPTED")
            in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}
        )
        incomplete = tuple(item for item in required if item not in completed)
        optional_unattempted = tuple(
            item.route_ref for item in self.plan.provider_routes
            if not item.required_for_acquisition
            and next((row.attempt.status for row in results if row.route_ref == item.route_ref), "NOT_ATTEMPTED")
            == "NOT_ATTEMPTED"
        )
        complete = bool(required) and not incomplete
        if not required:
            completion = "not_available"
            basis = "no_required_routes"
        elif complete:
            completion = "complete"
            basis = "required_routes_complete"
        elif any(item.status in {"FAILED_PERMANENT", "AUTH_FAILED"} for item in attempts):
            completion = "failed"
            basis = "acquisition_failed"
        else:
            completion = "partial"
            basis = "required_route_incomplete"
        observation_refs = tuple(item.observation_ref for item in observations)
        snapshot = EvidenceObservationSnapshot(
            snapshot_ref="evidence.observation-snapshot." + _digest({
                "plan": self.plan.plan_fingerprint,
                "observations": observation_refs,
            })[:24],
            query_plan_ref=self.plan.query_plan_ref,
            query_plan_fingerprint=self.plan.plan_fingerprint,
            attempt_refs=tuple(item.attempt_ref for item in attempts),
            observation_refs=observation_refs,
            source_refs=tuple(dict.fromkeys(
                source_ref for item in observations for source_ref in [item.source_ref] if source_ref
            )),
            records=observations,
            complete=complete,
        )
        frozen_attempts = [
            item for item in attempts if item.attempt_kind == "frozen_cache"
        ]
        cache_read_complete = bool(frozen_attempts) and all(
            item.status in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}
            for item in frozen_attempts
        )
        origin_values = {
            str(item.metadata.get("origin_completeness") or "unknown")
            for item in frozen_attempts
        }
        if not frozen_attempts:
            origin_completeness = "not_applicable"
        elif "incomplete" in origin_values:
            origin_completeness = "incomplete"
        elif origin_values == {"complete"}:
            origin_completeness = "complete"
        else:
            origin_completeness = "unknown"
        termination_reasons: list[str] = [
            page.termination_reason
            for page in pages
            if page.termination_reason
        ]
        if any(item.status == "QUOTA_EXHAUSTED" for item in attempts):
            termination_reasons.append("quota_exhausted")
        if any(item.status in {"FAILED_PERMANENT", "AUTH_FAILED", "TIMEOUT"} for item in attempts):
            termination_reasons.append("failed")
        receipt = EvidenceAcquisitionReceipt(
            receipt_ref=f"evidence.receipt.{self.plan.plan_fingerprint[:24]}",
            query_plan_ref=self.plan.query_plan_ref,
            query_plan_fingerprint=self.plan.plan_fingerprint,
            attempt_refs=tuple(item.attempt_ref for item in attempts),
            page_refs=tuple(item.page_ref for item in pages),
            required_route_refs=required,
            completed_required_routes=completed,
            incomplete_required_routes=incomplete,
            optional_unattempted_routes=optional_unattempted,
            completion_basis=basis,
            cache_read_complete=cache_read_complete,
            origin_completeness=origin_completeness,
            observation_snapshot_ref=snapshot.snapshot_ref,
            observation_snapshot_digest=snapshot.digest,
            completion=completion,
            termination_reasons=tuple(dict.fromkeys(termination_reasons)),
        )
        return attempts, pages, snapshot, receipt


def build_uniform_route_audit(
    plan: EvidenceQueryPlanV1,
    *,
    status: ProviderAttemptStatus,
    stage: str = "EVIDENCE",
    reason_code: str = "",
) -> tuple[
    tuple[ProviderAttempt, ...],
    tuple[ProviderPageRecord, ...],
    EvidenceObservationSnapshot,
    EvidenceAcquisitionReceipt,
]:
    """Create an explicit terminal result for a uniformly stopped plan."""

    executor = AcquisitionRouteExecutor(plan, stage=stage)
    route_results = [
        executor.complete_route(
            route,
            status=status,
            reason_code=reason_code,
        )
        for route in plan.provider_routes
    ]
    return executor.finalize(route_results)


__all__ = [
    "AcquisitionAttemptKind",
    "AcquisitionRouteExecutor",
    "AcquisitionRouteResult",
    "attempt_kind_for_route",
    "build_uniform_route_audit",
]
