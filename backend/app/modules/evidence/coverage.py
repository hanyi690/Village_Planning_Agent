"""Project retrieval results into bounded requirement coverage."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping
from typing import Any

from app.contracts.evidence.evidence_contracts import (
    EvidenceFact,
    ExplorationRequest,
    ExplorationResult,
)
from app.contracts.evidence.requirement_contracts import (
    EvidenceClaim,
    EvidenceCoverage,
    EvidenceRequirement,
    RequirementCoverage,
)
from app.modules.evidence.requirements import (
    compile_requirements,
    requirement_set_fingerprint,
)
from app.modules.evidence.sufficiency import SufficiencyDecision


def _claim_id(fact: EvidenceFact) -> str:
    payload = {
        "statement": " ".join(fact.statement.split()),
        "source_refs": sorted(fact.source_refs),
        "fact_type": fact.fact_type,
        "source_locator": fact.source_locator,
        "evidence_span": fact.evidence_span,
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"evidence-claim-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:20]}"


def _claim_status(fact: EvidenceFact) -> str:
    status = str(fact.status or "").casefold()
    relation = " ".join([fact.support_relation, *fact.support_relations]).casefold()
    if status in {"contradicted", "conflict", "conflicted"} or "contradict" in relation:
        return "contradicted"
    if status in {"ambiguous", "multiple"}:
        return "ambiguous"
    if status in {"unavailable", "missing", "unresolved"}:
        return "unavailable"
    return "supported"


def _source_family_map(result: ExplorationResult) -> dict[str, str]:
    return {
        str(source.reference): str(source.source_type)
        for source in result.evidence_bundle.sources
        if str(source.reference).strip()
    }


def _claims(result: ExplorationResult) -> tuple[EvidenceClaim, ...]:
    source_families = _source_family_map(result)
    sources_by_ref = {
        str(source.reference): source
        for source in result.evidence_bundle.sources
        if str(source.reference).strip()
    }
    claims: list[EvidenceClaim] = []
    seen: set[str] = set()
    for fact in result.evidence_bundle.facts:
        claim_id = _claim_id(fact)
        if claim_id in seen:
            continue
        seen.add(claim_id)
        locators = tuple(
            dict.fromkeys(
                value.strip()
                for value in (fact.source_locator, fact.evidence_span)
                if str(value or "").strip()
            )
        )
        families = tuple(
            dict.fromkeys(
                source_families[reference]
                for reference in fact.source_refs
                if reference in source_families
            )
        )
        matched_sources = [
            sources_by_ref[reference]
            for reference in fact.source_refs
            if reference in sources_by_ref
        ]
        claims.append(
            EvidenceClaim(
                claim_id=claim_id,
                statement=fact.statement,
                status=_claim_status(fact),
                source_refs=tuple(dict.fromkeys(fact.source_refs)),
                source_families=families,
                locators=locators,
                spatial_refs=tuple(dict.fromkeys(fact.spatial_refs)),
                authority=(matched_sources[0].authority if matched_sources else "advisory"),
                snapshot_refs=tuple(
                    dict.fromkeys(source.snapshot_ref for source in matched_sources if source.snapshot_ref)
                ),
                confidence=max(0.0, min(1.0, float(fact.confidence))),
                support_relation=fact.support_relation or "supports",
                derived_from=tuple(dict.fromkeys(fact.related_fact_refs)),
                metadata={
                    "fact_type": fact.fact_type,
                    "source_kind": fact.source_kind,
                    "spatial_granularity": fact.spatial_granularity,
                },
            )
        )
    packet = result.evidence_packet
    if packet is not None:
        for candidate in packet.candidate_refs:
            identity = candidate.identity
            packet_ref = str(
                candidate.geometry_ref
                or candidate.resource_ref
                or identity.source_feature_id
                or ""
            ).strip()
            if not packet_ref:
                continue
            claim_id = f"evidence-claim-feature-{hashlib.sha256(packet_ref.encode('utf-8')).hexdigest()[:20]}"
            if claim_id in seen:
                continue
            seen.add(claim_id)
            name = str(identity.canonical_name or identity.entity_type or "空间要素").strip()
            source_refs = tuple(dict.fromkeys(
                value
                for value in (
                    candidate.resource_ref,
                    *candidate.provenance_refs,
                    *candidate.l1_fact_refs,
                )
                if str(value or "").strip()
            ))
            spatial_refs = tuple(dict.fromkeys(
                value
                for value in (candidate.geometry_ref, candidate.resource_ref)
                if str(value or "").strip()
            ))
            snapshot_refs = tuple(dict.fromkeys(
                value
                for value in (
                    packet.data_snapshot_ref,
                    packet.data_snapshot_digest,
                    candidate.source_snapshot_ref,
                )
                if str(value or "").strip()
            ))
            claims.append(
                EvidenceClaim(
                    claim_id=claim_id,
                    statement=f"{name} 的 DATA source feature 为 {packet_ref}",
                    status="supported",
                    source_refs=source_refs,
                    source_families=("data",),
                    locators=tuple(
                        dict.fromkeys(
                            value
                            for value in (
                                packet_ref,
                                candidate.geometry_ref,
                                candidate.resource_ref,
                                *candidate.provenance_refs,
                            )
                            if str(value or "").strip()
                        )
                    ),
                    spatial_refs=spatial_refs,
                    authority=(
                        "authoritative_geometry"
                        if candidate.geometry_authority == "data_resource_catalog"
                        else "advisory"
                    ),
                    snapshot_refs=snapshot_refs,
                    confidence=max(
                        0.0,
                        min(
                            1.0,
                            float(
                                candidate.selection_confidence
                                if candidate.selection_confidence is not None
                                else candidate.retrieval_score
                            ),
                        ),
                    ),
                    metadata={
                        "evidence_packet": True,
                        "canonical_name": identity.canonical_name,
                        "geometry_authority": candidate.geometry_authority,
                    },
                )
            )
    return tuple(claims)


def _stop_reason(
    decision: SufficiencyDecision,
    query_trace: Iterable[Mapping[str, Any]],
    *,
    unresolved: bool = False,
) -> str:
    statuses = {str(item.get("status") or "").casefold() for item in query_trace}
    if "budget_exhausted" in statuses:
        return "budget_exhausted"
    if decision.status.value == "sufficient":
        return "source_exhausted" if unresolved else "sufficient"
    if decision.status.value == "human_required":
        return "human_required"
    return "source_exhausted"


def build_evidence_coverage(
    request: ExplorationRequest,
    result: ExplorationResult,
    decision: SufficiencyDecision,
    *,
    requirements: tuple[EvidenceRequirement, ...] | None = None,
    source_families_queried: tuple[str, ...] | None = None,
    query_trace: tuple[dict[str, Any], ...] = (),
    source_scope: str | None = None,
) -> EvidenceCoverage:
    """Build a bounded, per-requirement coverage artifact from retrieval output."""

    compiled = requirements or compile_requirements(request)
    claims = _claims(result)
    policy_result = decision.policy_result
    policy_decisions = {
        item.requirement_ref: item
        for item in (policy_result.requirement_decisions if policy_result else ())
    }
    requirement_coverage: list[RequirementCoverage] = []
    for requirement in compiled:
        policy_decision = policy_decisions.get(requirement.requirement_ref)
        candidate_rows = tuple(
            candidate
            for candidate in (policy_result.candidates if policy_result else ())
            if candidate.requirement_ref == requirement.requirement_ref
            and (
                policy_decision is None
                or candidate.candidate_ref in policy_decision.candidate_refs
            )
        )
        candidate_claim_refs = tuple(
            dict.fromkeys(
                claim_ref
                for candidate in candidate_rows
                for claim_ref in candidate.claim_refs
            )
        )
        matched = tuple(
            claim
            for claim in claims
            if claim.claim_id in candidate_claim_refs
        )
        claim_refs = tuple(dict.fromkeys((*candidate_claim_refs, *(claim.claim_id for claim in matched))))
        families = tuple(dict.fromkeys(
            family
            for candidate in candidate_rows
            for family in candidate.source_families
        )) or tuple(dict.fromkeys(
            family for claim in matched for family in claim.source_families
        ))
        locator_complete = (
            bool(candidate_rows)
            and all(candidate.locator_refs for candidate in candidate_rows)
        ) or (bool(matched) and all(claim.locator_complete for claim in matched))
        if policy_decision and policy_decision.status == "sufficient":
            status = "supported"
            reason = (
                "authorized absence conclusion"
                if policy_decision.conclusion_kind == "absence"
                else "all requirement-specific policy gates passed"
            )
            if policy_decision.conclusion_kind == "absence":
                locator_complete = True
        elif not result.evidence_bundle.sources:
            status = "unavailable"
            reason = "no retriever returned an available source"
        elif policy_decision and policy_decision.status == "human_required":
            status = "ambiguous"
            reason = policy_decision.reason
        elif policy_decision and policy_decision.status == "contradicted":
            status = "contradicted"
            reason = policy_decision.reason
        elif policy_decision and policy_decision.status == "not_available":
            status = "unavailable"
            reason = policy_decision.reason
        elif policy_decision and policy_decision.status != "sufficient":
            status = "unresolved"
            reason = policy_decision.reason
        elif matched and all(claim.status == "contradicted" for claim in matched):
            status = "contradicted"
            reason = "all matched claims contradict the requirement"
        elif matched and any(claim.status == "supported" for claim in matched):
            status = "supported"
            reason = "at least one source-backed claim supports the requirement"
        else:
            status = "unresolved"
            reason = "retrieved sources did not provide a matching claim"
        requirement_coverage.append(
            RequirementCoverage(
                requirement_id=requirement.requirement_id,
                status=status,
                claim_refs=claim_refs,
                source_families_covered=families,
                locators_complete=locator_complete,
                unresolved_reason=reason if status != "supported" else "",
                policy_ref=policy_decision.policy_ref if policy_decision else requirement.policy_ref,
                policy_version=policy_decision.policy_version if policy_decision else "",
                candidate_refs=policy_decision.candidate_refs if policy_decision else (),
                sufficiency_status=policy_decision.status if policy_decision else None,
                sufficiency_checks=policy_decision.checks if policy_decision else (),
                conclusion_kind=policy_decision.conclusion_kind if policy_decision else "none",
            )
        )

    requirement_required = {item.requirement_id: item.required for item in compiled}
    unresolved = tuple(
        item.requirement_id
        for item in requirement_coverage
        if item.status != "supported" and requirement_required.get(item.requirement_id, True)
    )
    queried = tuple(
        dict.fromkeys(
            source_families_queried
            or [source.source_type for source in result.evidence_bundle.sources]
        )
    )
    unavailable = tuple(
        family
        for family in queried
        if not any(source.source_type == family for source in result.evidence_bundle.sources)
    )
    scope = source_scope or (
        "project_wide" if request.project_wide or not request.entity_scope else "scoped"
    )
    return EvidenceCoverage(
        run_id=request.run_id,
        request_id=request.run_id,
        requirement_set_fingerprint=requirement_set_fingerprint(compiled),
        source_scope=scope,
        source_families_queried=queried,
        requirements=compiled,
        requirement_coverage=tuple(requirement_coverage),
        claims=claims,
        unresolved_requirements=unresolved,
        unavailable_source_families=unavailable,
        stop_reason=_stop_reason(
            decision,
            query_trace,
            unresolved=bool(unresolved),
        ),
        query_trace=query_trace,
        candidate_evidence=policy_result.candidates if policy_result else (),
        conflict_sets=policy_result.conflicts if policy_result else (),
        conflict_refs=tuple(
            dict.fromkeys(
                item.conflict_ref
                for item in (policy_result.conflicts if policy_result else ())
            )
        ),
        sufficiency_decision=policy_result,
    )


__all__ = ["build_evidence_coverage"]
