"""Deterministic EV-02 Evidence reasoning and policy sufficiency gates."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any, Iterable

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    EvidenceSource,
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.evidence.policy_contracts import EvidencePolicy, resolve_policy
from app.contracts.evidence.provider_attempt import EvidenceObservationRecord
from app.contracts.evidence.reasoning_contracts import (
    CandidateEvidence,
    ConflictSet,
    EvidenceSufficiencyResult,
    RequirementSufficiencyDecision,
    SufficiencyCheck,
)
from app.contracts.evidence.requirement_contracts import EvidenceRequirement
from app.modules.evidence.requirements import compile_requirements


class SufficiencyStatus(StrEnum):
    """Application-facing projection of the EV-02 terminal states."""

    SUFFICIENT = "sufficient"
    PARTIAL = "partial"
    INSUFFICIENT = "insufficient"
    CONTRADICTED = "contradicted"
    NOT_AVAILABLE = "not_available"
    HUMAN_REQUIRED = "human_required"
    FAILED = "failed"


@dataclass(frozen=True)
class SufficiencyDecision:
    """Runtime result retaining the complete typed EV-02 reasoning artifact."""

    status: SufficiencyStatus
    missing_facts: tuple[str, ...] = ()
    ambiguous_facts: tuple[str, ...] = ()
    unavailable_sources: tuple[str, ...] = ()
    next_request: ExplorationRequest | None = None
    reason: str = ""
    policy_result: EvidenceSufficiencyResult | None = None

    @property
    def terminal(self) -> bool:
        return self.status in {
            SufficiencyStatus.SUFFICIENT,
            SufficiencyStatus.PARTIAL,
            SufficiencyStatus.INSUFFICIENT,
            SufficiencyStatus.CONTRADICTED,
            SufficiencyStatus.NOT_AVAILABLE,
            SufficiencyStatus.HUMAN_REQUIRED,
            SufficiencyStatus.FAILED,
        }

    @property
    def candidate_evidence(self) -> tuple[CandidateEvidence, ...]:
        return self.policy_result.candidates if self.policy_result is not None else ()

    @property
    def conflict_sets(self) -> tuple[ConflictSet, ...]:
        return self.policy_result.conflicts if self.policy_result is not None else ()


_AUTHORITY_RANK = {
    "none": 0,
    "advisory": 1,
    "semantic": 1,
    "source_backed": 2,
    "local_source": 3,
    "authoritative": 4,
    "authoritative_geometry": 4,
    "statutory": 5,
    "local_legal_source": 5,
    "data_resource_catalog": 5,
    "local_representation": 5,
}
_FAMILY_ALIASES = {
    "gis_layer": "gis",
    "data_catalog": "data",
    "current_world": "kg",
    "source_span": "report",
    "frozen_cache": "external",
}


def _normalize_family(value: Any) -> str:
    family = str(value or "").strip().casefold()
    return _FAMILY_ALIASES.get(family, family)


def _normalized(value: Any) -> str:
    return "".join(str(value or "").casefold().split())


def _text_matches(requirement: EvidenceRequirement, statement: str) -> bool:
    required = _normalized(requirement.statement)
    candidate = _normalized(statement)
    if not required:
        return False
    if required in candidate:
        return True
    tokens = [token for token in requirement.statement.casefold().split() if len(token) > 1]
    return bool(tokens) and all(token in candidate for token in tokens)


def _claim_ref(fact: EvidenceFact) -> str:
    payload = {
        "statement": " ".join(fact.statement.split()),
        "source_refs": sorted(fact.source_refs),
        "fact_type": fact.fact_type,
        "source_locator": fact.source_locator,
        "evidence_span": fact.evidence_span,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"evidence-claim-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _value_digest(fact: EvidenceFact) -> str:
    value = fact.fields.get("value")
    if value in (None, ""):
        value = fact.fields.get("observed_value")
    if value in (None, ""):
        value = fact.statement
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _observation_for_fact(
    fact: EvidenceFact,
    result: ExplorationResult,
) -> tuple[EvidenceObservationRecord, ...]:
    snapshot = result.observation_snapshot
    if snapshot is None:
        return ()
    fields = dict(fact.fields or {})
    explicit = {
        str(fields.get("observation_ref") or "").strip(),
        str(fields.get("observation_id") or "").strip(),
    }
    source_refs = {str(item) for item in fact.source_refs}
    return tuple(
        record
        for record in snapshot.records
        if record.observation_ref in explicit
        or record.source_ref in source_refs
        or source_refs.intersection(record.source_refs)
    )


def _fact_candidate(
    requirement: EvidenceRequirement,
    fact: EvidenceFact,
    result: ExplorationResult,
    source_by_ref: dict[str, EvidenceSource],
) -> CandidateEvidence:
    observations = _observation_for_fact(fact, result)
    matched_sources = tuple(
        source_by_ref[reference]
        for reference in fact.source_refs
        if reference in source_by_ref
    )
    source_families = tuple(dict.fromkeys(
        _normalize_family(source.source_type)
        for source in matched_sources
        if _normalize_family(source.source_type)
    ))
    if not source_families and fact.source_kind:
        source_families = (_normalize_family(fact.source_kind),)
    authorities = tuple(dict.fromkeys(
        str(value).strip()
        for value in (
            *(source.authority for source in matched_sources),
            *(record.source_authority for record in observations),
        )
        if str(value).strip()
    )) or ("advisory",)
    fields = dict(fact.fields or {})
    geometry_authorities = tuple(dict.fromkeys(
        value
        for value in (
            str(fields.get("geometry_authority") or "").strip(),
            *(record.geometry_authority for record in observations),
        )
        if value and value != "none"
    )) or ("none",)
    legal_authorities = tuple(dict.fromkeys(
        value
        for value in (
            str(fields.get("legal_authority") or "").strip(),
            *(record.legal_authority for record in observations),
        )
        if value and value != "none"
    )) or ("none",)
    origin_refs = tuple(dict.fromkeys(
        value
        for value in (
            *fact.source_refs,
            *(record.origin_provider for record in observations),
            *(record.origin_record_ref for record in observations),
        )
        if str(value).strip()
    ))
    valid_times = tuple(dict.fromkeys(
        value
        for value in (
            str(fields.get("valid_time") or "").strip(),
            *(record.valid_time for record in observations),
            *(record.observed_at.isoformat() for record in observations if record.observed_at),
        )
        if value
    ))
    if not valid_times:
        valid_times = tuple(dict.fromkeys(
            source.retrieved_at for source in matched_sources if source.retrieved_at
        ))
    inference = str(fields.get("inference_level") or "exact").strip() or "exact"
    status = str(fact.status or "").casefold()
    support_status = (
        "contradicted" if status in {"contradicted", "conflict", "conflicted"}
        else "ambiguous" if status in {"ambiguous", "multiple"}
        else "unavailable" if status in {"unavailable", "missing", "unresolved"}
        else "supported"
    )
    material = {
        "requirement": requirement.requirement_ref,
        "fact": fact.fact_id,
        "sources": sorted(fact.source_refs),
        "value": _value_digest(fact),
    }
    candidate_ref = "evidence.candidate." + hashlib.sha256(
        json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:24]
    return CandidateEvidence(
        candidate_ref=candidate_ref,
        requirement_ref=requirement.requirement_ref,
        observation_refs=tuple(record.observation_ref for record in observations),
        claim_refs=(_claim_ref(fact),),
        source_refs=tuple(dict.fromkeys(fact.source_refs)),
        source_families=source_families,
        source_authorities=authorities,
        geometry_authorities=geometry_authorities,
        legal_authorities=legal_authorities,
        spatial_refs=tuple(dict.fromkeys(fact.spatial_refs)),
        independent_source_refs=origin_refs,
        valid_times=valid_times,
        inference_levels=(inference,),
        statement=fact.statement,
        value_digest=_value_digest(fact),
        locator_refs=tuple(dict.fromkeys(
            value for value in (fact.source_locator, fact.evidence_span, *fact.spatial_refs) if value
        )),
        support_status=support_status,
        confidence=max(0.0, min(1.0, float(fact.confidence))),
    )


def _packet_candidates(
    requirement: EvidenceRequirement,
    result: ExplorationResult,
) -> tuple[CandidateEvidence, ...]:
    packet = result.evidence_packet
    if packet is None or not packet.candidate_refs or not _text_matches(requirement, packet.request):
        return ()
    output: list[CandidateEvidence] = []
    for item in packet.candidate_refs:
        identity = item.identity
        packet_ref = str(
            item.geometry_ref
            or item.resource_ref
            or identity.source_feature_id
            or ""
        ).strip()
        if not packet_ref:
            continue
        snapshot = result.observation_snapshot
        if snapshot is None or not any(
            record.candidate_ref in {
                packet_ref,
                str(identity.source_feature_id or ""),
            }
            or (
                item.geometry_ref
                and record.resource_ref == item.geometry_ref
            )
            for record in snapshot.records
        ):
            continue
        material = f"{requirement.requirement_ref}:{packet_ref}"
        packet_claim_ref = (
            "evidence-claim-feature-"
            + hashlib.sha256(packet_ref.encode()).hexdigest()[:20]
        )
        output.append(CandidateEvidence(
            candidate_ref="evidence.candidate.packet." + hashlib.sha256(material.encode()).hexdigest()[:24],
            requirement_ref=requirement.requirement_ref,
            claim_refs=tuple(dict.fromkeys((
                packet_claim_ref,
                *item.provenance_refs,
                *item.l1_fact_refs,
            ))),
            source_refs=tuple(dict.fromkeys(
                value
                for value in (
                    item.resource_ref,
                    *item.provenance_refs,
                    *item.l1_fact_refs,
                )
                if str(value or "").strip()
            )),
            source_families=("data",),
            source_authorities=(
                "authoritative_geometry"
                if item.geometry_authority == "data_resource_catalog"
                else "advisory",
            ),
            geometry_authorities=(str(item.geometry_authority or "none"),),
            spatial_refs=tuple(dict.fromkeys(
                value
                for value in (item.geometry_ref, item.resource_ref)
                if str(value or "").strip()
            )),
            independent_source_refs=tuple(dict.fromkeys(
                value
                for value in (
                    item.source_snapshot_ref,
                    *item.provenance_refs,
                )
                if str(value or "").strip()
            )),
            inference_levels=("exact",),
            statement=f"{identity.canonical_name or identity.entity_type or 'candidate'} {packet_ref}",
            value_digest=hashlib.sha256(packet_ref.encode()).hexdigest()[:24],
            locator_refs=tuple(dict.fromkeys(
                value
                for value in (
                    item.geometry_ref,
                    item.resource_ref,
                    *item.representation_refs,
                    *item.provenance_refs,
                )
                if str(value or "").strip()
            )),
            confidence=max(0.0, min(1.0, float(
                item.selection_confidence
                if item.selection_confidence is not None
                else item.retrieval_score
            ))),
        ))
    return tuple(output)


def _compile_candidates(
    requirement: EvidenceRequirement,
    result: ExplorationResult,
) -> tuple[CandidateEvidence, ...]:
    source_by_ref = {
        str(source.reference): source
        for source in result.evidence_bundle.sources
        if str(source.reference).strip()
    }
    candidates = [
        _fact_candidate(requirement, fact, result, source_by_ref)
        for fact in result.evidence_bundle.facts
        if _text_matches(requirement, fact.statement)
        and _observation_for_fact(fact, result)
    ]
    candidates.extend(_packet_candidates(requirement, result))
    by_ref = {candidate.candidate_ref: candidate for candidate in candidates}
    return tuple(by_ref[key] for key in sorted(by_ref))


def _conflicts(
    requirement: EvidenceRequirement,
    candidates: tuple[CandidateEvidence, ...],
    result: ExplorationResult,
    policy: EvidencePolicy,
) -> tuple[ConflictSet, ...]:
    groups: dict[str, list[CandidateEvidence]] = {}
    for candidate in candidates:
        groups.setdefault(candidate.value_digest or candidate.statement, []).append(candidate)
    conflicts: list[ConflictSet] = []
    if len(groups) > 1:
        values = [candidate for group in groups.values() for candidate in group]
        refs = tuple(sorted(candidate.candidate_ref for candidate in values))
        material = f"{requirement.requirement_ref}:value:{','.join(refs)}"
        conflicts.append(ConflictSet(
            conflict_ref="evidence.conflict." + hashlib.sha256(material.encode()).hexdigest()[:24],
            requirement_ref=requirement.requirement_ref,
            candidate_refs=refs,
            conflict_kind="value",
            policy=policy.conflict_policy,
            reason="multiple requirement candidates have different observed values",
        ))
    fact_ids = {
        fact.fact_id
        for fact in result.evidence_bundle.facts
        if _text_matches(requirement, fact.statement)
        and str(fact.status or "").casefold() in {"contradicted", "conflict", "conflicted"}
    }
    if fact_ids and candidates:
        refs = tuple(sorted(candidate.candidate_ref for candidate in candidates))
        material = f"{requirement.requirement_ref}:status:{','.join(refs)}"
        conflict_ref = "evidence.conflict." + hashlib.sha256(material.encode()).hexdigest()[:24]
        if not any(item.conflict_ref == conflict_ref for item in conflicts):
            conflicts.append(ConflictSet(
                conflict_ref=conflict_ref,
                requirement_ref=requirement.requirement_ref,
                candidate_refs=refs,
                conflict_kind="provider_status",
                policy=policy.conflict_policy,
                reason="at least one matched observation is explicitly contradicted",
            ))
    matched_fact_ids = {
        fact.fact_id
        for fact in result.evidence_bundle.facts
        if _text_matches(requirement, fact.statement)
    }
    for bundle_conflict in result.evidence_bundle.conflicts:
        if not matched_fact_ids.intersection(bundle_conflict.fact_refs) or not candidates:
            continue
        refs = tuple(sorted(candidate.candidate_ref for candidate in candidates))
        material = f"{requirement.requirement_ref}:bundle:{bundle_conflict.relation}:{','.join(refs)}"
        conflict_ref = "evidence.conflict." + hashlib.sha256(material.encode()).hexdigest()[:24]
        if any(item.conflict_ref == conflict_ref for item in conflicts):
            continue
        conflicts.append(ConflictSet(
            conflict_ref=conflict_ref,
            requirement_ref=requirement.requirement_ref,
            candidate_refs=refs,
            conflict_kind="value" if bundle_conflict.relation == "contradicts" else "scope",
            policy=policy.conflict_policy,
            reason=bundle_conflict.reason,
        ))
    return tuple(sorted(conflicts, key=lambda item: item.conflict_ref))


def _source_pool(
    requirement: EvidenceRequirement,
    policy: EvidencePolicy,
    result: ExplorationResult,
) -> tuple[EvidenceSource, ...]:
    allowed = set(policy.allowed_source_families)
    declared = {_normalize_family(item) for item in requirement.source_families}
    return tuple(
        source
        for source in result.evidence_bundle.sources
        if _normalize_family(source.source_type) in allowed
        and (not declared or _normalize_family(source.source_type) in declared)
    )


def _authority_passes(actual: Iterable[str], required: str) -> bool:
    values = tuple(str(item).casefold() for item in actual if str(item).strip())
    if required in {"", "none", "advisory"}:
        return bool(values) if required == "advisory" else True
    if required in _AUTHORITY_RANK:
        threshold = _AUTHORITY_RANK[required]
        return any(_AUTHORITY_RANK.get(value, 0) >= threshold for value in values)
    return required.casefold() in values


def _parse_datetime(value: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _temporal_passes(
    requirement: EvidenceRequirement,
    policy: EvidencePolicy,
    candidates: tuple[CandidateEvidence, ...],
    sources: tuple[EvidenceSource, ...],
) -> bool:
    valid_times = tuple(value for candidate in candidates for value in candidate.valid_times)
    if not valid_times:
        valid_times = tuple(source.retrieved_at for source in sources if source.retrieved_at)
    if requirement.valid_time:
        required_time = _parse_datetime(requirement.valid_time)
        if required_time is None:
            return any(requirement.valid_time in value for value in valid_times)
        parsed = [_parse_datetime(value) for value in valid_times]
        parsed = [value for value in parsed if value is not None]
        if not parsed or not any(value.date() == required_time.date() for value in parsed):
            return False
    else:
        parsed = [_parse_datetime(value) for value in valid_times]
        parsed = [value for value in parsed if value is not None]
    if policy.legal_effective_time:
        effective = _parse_datetime(policy.legal_effective_time)
        if effective is None or not parsed or not any(value >= effective for value in parsed):
            return False
    if requirement.valid_time:
        return True
    if policy.max_age_days is None:
        return True
    now = datetime.now(timezone.utc)
    return bool(parsed) and any((now - value).days <= policy.max_age_days for value in parsed)


def _independent_refs(
    candidates: tuple[CandidateEvidence, ...],
    sources: tuple[EvidenceSource, ...],
) -> tuple[str, ...]:
    refs = tuple(dict.fromkeys(
        reference
        for candidate in candidates
        for reference in candidate.independent_source_refs
        if reference
    ))
    if refs:
        return refs
    return tuple(dict.fromkeys(str(source.reference) for source in sources if source.reference))


def _receipt_complete(
    policy: EvidencePolicy,
    result: ExplorationResult,
) -> bool:
    receipt = result.acquisition_receipt
    if receipt is None or receipt.completion != "complete" or receipt.incomplete_required_routes:
        return False
    if result.provider_attempts:
        attempts_by_route = {
            attempt.route_ref: attempt
            for attempt in result.provider_attempts
        }
        if any(
            attempts_by_route.get(route_ref) is None
            or attempts_by_route[route_ref].status not in {"SUCCESS_NONEMPTY", "SUCCESS_EMPTY"}
            for route_ref in receipt.required_route_refs
        ):
            return False
    if policy.completion_requirement == "provider_exhausted":
        return "provider_exhausted" in receipt.termination_reasons
    return True


def _origin_complete(result: ExplorationResult) -> bool:
    receipt = result.acquisition_receipt
    if receipt is None:
        return False
    frozen = any(item.attempt_kind == "frozen_cache" for item in result.provider_attempts)
    if not frozen:
        return receipt.origin_completeness in {"not_applicable", "complete"}
    return receipt.origin_completeness == "complete"


def _absence_complete(
    policy: EvidencePolicy,
    result: ExplorationResult,
    sources: tuple[EvidenceSource, ...],
    candidates: tuple[CandidateEvidence, ...],
    conflicts: tuple[ConflictSet, ...],
) -> tuple[bool, str]:
    if policy.absence_policy == "never":
        return False, "policy does not permit an absence conclusion"
    if candidates:
        return False, "absence requires no positive candidate evidence"
    if conflicts:
        return False, "absence requires no unresolved conflict"
    if not _authority_passes((source.authority for source in sources), policy.required_source_authority):
        return False, "required source authority is not satisfied"
    if len(_independent_refs(candidates, sources)) < policy.min_independent_sources:
        return False, "independent-source rule is not satisfied"
    if not _receipt_complete(policy, result):
        return False, "acquisition or provider pagination is incomplete"
    if not _origin_complete(result):
        return False, "provider origin completeness is not satisfied"
    return True, "absence policy is satisfied after complete acquisition and conflict closure"


def _check(
    gate: str,
    passed: bool | None,
    *,
    reason: str,
    observed: Iterable[str] = (),
    expected: Iterable[str] = (),
    evidence_refs: Iterable[str] = (),
) -> SufficiencyCheck:
    return SufficiencyCheck(
        gate=gate,
        status="not_applicable" if passed is None else "pass" if passed else "fail",
        reason=reason,
        observed=tuple(dict.fromkeys(str(item) for item in observed if str(item))),
        expected=tuple(dict.fromkeys(str(item) for item in expected if str(item))),
        evidence_refs=tuple(dict.fromkeys(str(item) for item in evidence_refs if str(item))),
    )


def _evaluate_requirement(
    requirement: EvidenceRequirement,
    result: ExplorationResult,
) -> tuple[RequirementSufficiencyDecision, tuple[CandidateEvidence, ...], tuple[ConflictSet, ...]]:
    policy = resolve_policy(requirement.policy_ref)
    candidates = _compile_candidates(requirement, result)
    sources = _source_pool(requirement, policy, result)
    conflicts = _conflicts(requirement, candidates, result, policy)
    source_families = tuple(dict.fromkeys(
        family for candidate in candidates for family in candidate.source_families
    )) or tuple(dict.fromkeys(_normalize_family(source.source_type) for source in sources))
    source_family_pass = bool(source_families) and all(
        family in set(policy.allowed_source_families)
        and (
            not requirement.source_families
            or family in {_normalize_family(item) for item in requirement.source_families}
        )
        for family in source_families
    )
    authorities = tuple(
        authority for candidate in candidates for authority in candidate.source_authorities
    ) or tuple(source.authority for source in sources)
    independent = _independent_refs(candidates, sources)
    temporal_pass = _temporal_passes(requirement, policy, candidates, sources)
    geometry_required = policy.geometry_authority not in {"", "none"}
    geometry_values = tuple(
        value
        for candidate in candidates
        for value in candidate.geometry_authorities
        if value != "none"
    )
    legal_required = policy.legal_authority not in {"", "none"}
    legal_values = tuple(
        value
        for candidate in candidates
        for value in candidate.legal_authorities
        if value != "none"
    )
    geometry_legal_pass = (
        bool(geometry_values)
        and any(candidate.spatial_refs for candidate in candidates)
        and _authority_passes(geometry_values, policy.geometry_authority)
        if geometry_required
        else True
    ) and (
        _authority_passes(legal_values, policy.legal_authority)
        if legal_required
        else True
    )
    if not candidates and (geometry_required or legal_required):
        geometry_legal_pass = False
    conflict_pass = not conflicts
    if conflicts and policy.conflict_policy == "resolve":
        best = sorted(candidates, key=lambda item: item.confidence, reverse=True)
        conflict_pass = len(best) >= 2 and best[0].confidence > best[1].confidence
        if conflict_pass:
            winner = best[0].candidate_ref
            conflicts = tuple(
                item.model_copy(update={
                    "resolution_status": "resolved",
                    "resolution_ref": winner,
                })
                for item in conflicts
            )
    allowed = set(policy.allowed_inference).intersection({requirement.allowed_inference})
    inference_values = tuple(
        value for candidate in candidates for value in candidate.inference_levels
    ) or ((requirement.allowed_inference,) if not candidates else ())
    inference_pass = bool(allowed) and all(value in allowed for value in inference_values)
    acquisition_pass = _receipt_complete(policy, result)
    origin_pass = _origin_complete(result)
    absence_pass, absence_reason = _absence_complete(
        policy,
        result,
        sources,
        candidates,
        conflicts,
    )
    checks = (
        _check(
            "source_family",
            source_family_pass,
            reason="source family is allowed" if source_family_pass else "no candidate/source in the policy source family",
            observed=source_families,
            expected=policy.allowed_source_families,
        ),
        _check(
            "source_authority",
            _authority_passes(authorities, policy.required_source_authority),
            reason="required source authority is present" if _authority_passes(authorities, policy.required_source_authority) else "required source authority is missing",
            observed=authorities,
            expected=(policy.required_source_authority,),
        ),
        _check(
            "independent_sources",
            len(independent) >= policy.min_independent_sources,
            reason="independent-source rule is satisfied" if len(independent) >= policy.min_independent_sources else "not enough independent sources",
            observed=independent,
            expected=(str(policy.min_independent_sources),),
        ),
        _check(
            "temporal_fit",
            temporal_pass,
            reason="temporal fit is satisfied" if temporal_pass else "evidence has no valid temporal fit",
            observed=tuple(value for candidate in candidates for value in candidate.valid_times),
            expected=((requirement.valid_time,) if requirement.valid_time else (str(policy.max_age_days) if policy.max_age_days is not None else "unbounded",)),
        ),
        _check(
            "geometry_legal_authority",
            geometry_legal_pass,
            reason="geometry/legal authority is satisfied" if geometry_legal_pass else "geometry or legal authority is missing",
            observed=(*geometry_values, *legal_values),
            expected=(policy.geometry_authority, policy.legal_authority),
        ),
        _check(
            "conflict_policy",
            conflict_pass,
            reason="no unresolved conflict remains" if conflict_pass else "conflict policy leaves an unresolved conflict",
            observed=(item.conflict_ref for item in conflicts),
            expected=(policy.conflict_policy,),
        ),
        _check(
            "allowed_inference",
            inference_pass,
            reason="inference level is allowed" if inference_pass else "candidate inference exceeds the policy allowance",
            observed=inference_values,
            expected=policy.allowed_inference,
        ),
        _check(
            "acquisition_completeness",
            acquisition_pass,
            reason="required acquisition is complete" if acquisition_pass else "acquisition receipt is incomplete or unavailable",
            observed=((result.acquisition_receipt.completion,) if result.acquisition_receipt else ()),
            expected=(policy.completion_requirement,),
        ),
        _check(
            "provider_origin_completeness",
            origin_pass,
            reason="provider origin is complete" if origin_pass else "provider/cache origin is incomplete",
            observed=((result.acquisition_receipt.origin_completeness,) if result.acquisition_receipt else ()),
            expected=("complete", "not_applicable"),
        ),
        _check("absence_policy", absence_pass, reason=absence_reason),
    )
    passed_before_absence = all(item.status == "pass" for item in checks[:-1])
    if absence_pass:
        status = "sufficient"
        conclusion_kind = "absence"
        reason = absence_reason
    elif candidates and passed_before_absence:
        status = "sufficient"
        conclusion_kind = "presence"
        reason = "all ten EV-02 policy gates passed for positive evidence"
    elif conflicts and policy.conflict_policy in {"human", "defer"}:
        status = "human_required"
        conclusion_kind = "none"
        reason = "unresolved conflict requires the policy-defined human/deferred path"
    elif candidates and all(candidate.support_status == "contradicted" for candidate in candidates):
        status = "contradicted"
        conclusion_kind = "none"
        reason = "all matching candidate evidence is contradicted"
    elif not sources and not candidates:
        status = "not_available"
        conclusion_kind = "none"
        reason = "required source is not available for sufficiency"
    else:
        status = "insufficient"
        conclusion_kind = "none"
        reason = next((item.reason for item in checks if item.status == "fail"), "policy gates are not satisfied")
    decision = RequirementSufficiencyDecision(
        requirement_ref=requirement.requirement_ref,
        policy_ref=requirement.policy_ref,
        policy_version=policy.policy_version,
        status=status,
        candidate_refs=tuple(item.candidate_ref for item in candidates),
        conflict_refs=tuple(item.conflict_ref for item in conflicts),
        checks=checks,
        conclusion_kind=conclusion_kind,
        absence_authorized=absence_pass,
        reason=reason,
    )
    return decision, candidates, conflicts


def evaluate_sufficiency(
    request: ExplorationRequest,
    response: ExplorationResult,
) -> SufficiencyDecision:
    """Run EV-02 after acquisition audit and return the complete reasoning chain."""

    requirements = compile_requirements(request)
    decisions: list[RequirementSufficiencyDecision] = []
    candidates: list[CandidateEvidence] = []
    conflicts: list[ConflictSet] = []
    for requirement in requirements:
        decision, requirement_candidates, requirement_conflicts = _evaluate_requirement(
            requirement,
            response,
        )
        decisions.append(decision)
        candidates.extend(requirement_candidates)
        conflicts.extend(requirement_conflicts)
    required_decisions = [
        decision
        for requirement, decision in zip(requirements, decisions)
        if requirement.required
    ]
    if not required_decisions:
        status = "insufficient"
        reason = "no required Evidence requirements were declared"
    elif any(item.status == "human_required" for item in required_decisions):
        status = "human_required"
        reason = "one or more requirements require human resolution"
    elif any(item.status == "contradicted" for item in required_decisions):
        status = "contradicted"
        reason = "one or more requirements are contradicted"
    elif all(item.status == "sufficient" for item in required_decisions):
        status = "sufficient"
        reason = "all required Evidence requirements passed EV-02"
    elif any(item.status == "not_available" for item in required_decisions):
        status = "not_available"
        reason = "one or more required sources or acquisition routes are unavailable"
    else:
        status = "insufficient"
        reason = "one or more EV-02 policy gates failed"
    policy_result = EvidenceSufficiencyResult(
        status=status,
        candidates=tuple(candidates),
        conflicts=tuple(conflicts),
        requirement_decisions=tuple(decisions),
        absence_authorized=any(item.absence_authorized for item in decisions),
        reason=reason,
    )
    missing = tuple(
        requirement.statement
        for requirement, decision in zip(requirements, decisions)
        if requirement.required and not decision.candidate_refs
    )
    ambiguous = tuple(
        requirement.statement
        for requirement, decision in zip(requirements, decisions)
        if requirement.required and decision.status == "human_required"
    )
    unavailable = tuple(
        requirement.requirement_ref
        for requirement, decision in zip(requirements, decisions)
        if requirement.required and decision.status == "not_available"
    )
    next_request = None
    if missing or ambiguous:
        next_request = request.model_copy(update={
            "required_facts": list(dict.fromkeys((*request.required_facts, *missing))),
            "questions": list(dict.fromkeys((*request.questions, *ambiguous))),
            "query_purpose": "gap_resolution",
        })
    return SufficiencyDecision(
        status=SufficiencyStatus(status),
        missing_facts=missing,
        ambiguous_facts=ambiguous,
        unavailable_sources=unavailable,
        next_request=next_request,
        reason=reason,
        policy_result=policy_result,
    )


__all__ = ["SufficiencyDecision", "SufficiencyStatus", "evaluate_sufficiency"]
