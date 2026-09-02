"""Deterministic EV-03 Evidence-to-Cognition proposal compilation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.contracts.cognition.proposals import AssertionProposal
from app.contracts.evidence.evidence_contracts import EvidenceFact, ExplorationResult
from app.contracts.evidence.evidence_packet_contracts import SpatialRelationEvidence
from app.contracts.evidence.feature_identity_contracts import FeatureEvidenceRef
from app.contracts.evidence.proposal_contracts import (
    EntitySupportProposal,
    EvidenceProposal,
    EvidenceProposalBatch,
    EvidenceProposalBase,
    PropertyAssertionProposal,
    RelationSupportProposal,
    RepresentationSupportProposal,
)
from app.contracts.evidence.provider_attempt import EvidenceAuthority, EvidenceConfidence
from app.contracts.evidence.requirement_contracts import EvidenceClaim, EvidenceRequirement


def _digest(value: Any) -> str:
    payload = value.model_dump(mode="json") if hasattr(value, "model_dump") else value
    if isinstance(payload, dict):
        payload = dict(payload)
        payload.pop("created_at", None)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _refs(*groups: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    for group in groups:
        for value in group:
            if isinstance(value, (list, tuple, set, frozenset)):
                values.extend(_refs(value))
            elif str(value).strip():
                values.append(str(value).strip())
    return tuple(dict.fromkeys(values))


def _first(values: Iterable[str], default: str = "") -> str:
    return next((str(value).strip() for value in values if str(value).strip()), default)


def _feature_ref(value: FeatureEvidenceRef) -> str:
    if value.entity_refs:
        return value.entity_refs[0]
    if value.resource_ref:
        return value.resource_ref
    identity = value.identity
    return _first((identity.source_feature_id, identity.canonical_name))


def _subject_ref(requirement: EvidenceRequirement, candidate_refs: Iterable[str]) -> str:
    metadata = requirement.metadata or {}
    return _first((
        str(metadata.get("subject_ref") or ""),
        *requirement.subject_refs,
        *requirement.scope,
        *candidate_refs,
    ))


def _fact_by_claim(
    result: ExplorationResult,
    claims: dict[str, EvidenceClaim],
) -> dict[str, EvidenceFact]:
    return {
        claim_id: fact
        for fact in result.evidence_bundle.facts
        for claim_id in (str(getattr(fact, "fact_id", "") or ""),)
        if claim_id and claim_id in claims
    }


def _claim_value(
    requirement: EvidenceRequirement,
    claim: EvidenceClaim | None,
    fact: EvidenceFact | None,
) -> tuple[str, Any]:
    metadata = requirement.metadata or {}
    claim_metadata = claim.metadata if claim is not None else {}
    fact_fields = fact.fields if fact is not None else {}
    predicate = _first((
        str(metadata.get("predicate") or ""),
        str(metadata.get("property") or ""),
        str(claim_metadata.get("predicate") or ""),
        str(fact_fields.get("predicate") or ""),
        "supports_claim",
    ))
    value = fact_fields.get("value") if "value" in fact_fields else None
    if value is None:
        value = claim_metadata.get("value") if "value" in claim_metadata else None
    if value is None and claim is not None:
        value = claim.statement
    if value is None and fact is not None:
        value = fact.statement
    return predicate, value


def _authority(
    candidates: tuple[Any, ...],
    claims: tuple[EvidenceClaim, ...],
    sources: dict[str, Any],
) -> EvidenceAuthority:
    source_authority = _first(
        authority
        for candidate in candidates
        for authority in candidate.source_authorities
    )
    geometry_authority = _first(
        authority
        for candidate in candidates
        for authority in candidate.geometry_authorities
    )
    legal_authority = _first(
        authority
        for candidate in candidates
        for authority in candidate.legal_authorities
    )
    if not source_authority:
        source_authority = _first(
            [sources[ref].authority for claim in claims for ref in claim.source_refs if ref in sources],
            "advisory",
        )
    return EvidenceAuthority(
        source_authority=source_authority or "advisory",
        geometry_authority=geometry_authority or "none",
        legal_authority=legal_authority or "none",
    )


def _confidence(candidates: tuple[Any, ...], claims: tuple[EvidenceClaim, ...]) -> EvidenceConfidence:
    if candidates:
        semantic = sum(candidate.confidence for candidate in candidates) / len(candidates)
    elif claims:
        semantic = sum(claim.confidence for claim in claims) / len(claims)
    else:
        semantic = 0.0
    return EvidenceConfidence(
        acquisition=1.0,
        semantic=max(0.0, min(1.0, semantic)),
        binding=1.0 if candidates else 0.0,
        temporal_fit=1.0,
    )


def _common(
    *,
    requirement: EvidenceRequirement,
    candidates: tuple[Any, ...],
    claims: tuple[EvidenceClaim, ...],
    sources: dict[str, Any],
    observation_refs: tuple[str, ...],
    source_refs: tuple[str, ...],
    evidence_refs: tuple[str, ...],
    supporting_refs: tuple[str, ...],
    opposing_refs: tuple[str, ...],
    parent_world_model_digest: str,
    evidence_packet_digest: str,
    evidence_artifact_ref: str,
    policy_version: str,
    predicate: str,
    subject_ref: str,
    value: Any = None,
    object_ref: str = "",
    conclusion_kind: str = "presence",
    absence_authorized: bool = False,
) -> dict[str, Any]:
    candidate_refs = tuple(candidate.candidate_ref for candidate in candidates)
    valid_times = tuple(
        valid_time
        for candidate in candidates
        for valid_time in candidate.valid_times
    )
    if not valid_times:
        valid_times = (requirement.valid_time,) if requirement.valid_time else ()
    return {
        "proposal_ref": "",
        "requirement_ref": requirement.requirement_ref,
        "policy_ref": requirement.policy_ref,
        "policy_version": policy_version,
        "subject_ref": subject_ref,
        "predicate": predicate,
        "object_ref": object_ref,
        "value": value,
        "candidate_refs": candidate_refs,
        "claim_refs": _refs(claim.claim_id for claim in claims),
        "observation_refs": observation_refs,
        "source_refs": source_refs,
        "evidence_refs": evidence_refs,
        "supporting_evidence_refs": supporting_refs,
        "opposing_evidence_refs": opposing_refs,
        "confidence": _confidence(candidates, claims),
        "authority": _authority(candidates, claims, sources),
        "valid_time": _first(valid_times),
        "parent_world_model_digest": parent_world_model_digest,
        "evidence_packet_digest": evidence_packet_digest,
        "evidence_artifact_ref": evidence_artifact_ref,
        "conclusion_kind": conclusion_kind,
        "absence_authorized": absence_authorized,
    }


def _proposal_ref(kind: str, payload: dict[str, Any]) -> str:
    identity = {
        "kind": kind,
        "requirement_ref": payload["requirement_ref"],
        "subject_ref": payload["subject_ref"],
        "predicate": payload["predicate"],
        "object_ref": payload["object_ref"],
        "value": payload["value"],
        "candidate_refs": payload["candidate_refs"],
        "evidence_packet_digest": payload["evidence_packet_digest"],
        "parent_world_model_digest": payload["parent_world_model_digest"],
    }
    return "evidence.proposal." + kind + ":" + _digest(identity)[len("sha256:") : 40]


def _typed_proposal(
    kind: str,
    payload: dict[str, Any],
    *,
    representation_ref: str = "",
    geometry_authority: str = "",
) -> EvidenceProposal:
    payload = dict(payload)
    payload["proposal_ref"] = _proposal_ref(kind, payload)
    if kind == "entity_support":
        return EntitySupportProposal(proposal_kind=kind, **payload)
    if kind == "relation_support":
        return RelationSupportProposal(proposal_kind=kind, **payload)
    if kind == "property_assertion":
        return PropertyAssertionProposal(proposal_kind=kind, **payload)
    return RepresentationSupportProposal(
        proposal_kind=kind,
        representation_ref=representation_ref,
        geometry_authority=geometry_authority,
        **payload,
    )


def _proposal_for_relation(
    relation: SpatialRelationEvidence,
    *,
    payload: dict[str, Any],
) -> RelationSupportProposal | None:
    subject_ref = _feature_ref(relation.subject)
    object_ref = _feature_ref(relation.object)
    if not subject_ref or not object_ref or not relation.predicate:
        return None
    relation_sources = _refs(relation.provenance_refs, payload["source_refs"])
    if not relation_sources:
        return None
    relation_payload = dict(payload)
    relation_payload.update({
        "subject_ref": subject_ref,
        "predicate": relation.predicate,
        "object_ref": object_ref,
        "value": relation.metric_value,
        "source_refs": relation_sources,
        "evidence_refs": _refs(payload["evidence_refs"], relation.provenance_refs),
        "supporting_evidence_refs": _refs(payload["supporting_evidence_refs"], relation.provenance_refs),
    })
    relation_payload["proposal_ref"] = _proposal_ref("relation_support", relation_payload)
    return RelationSupportProposal(proposal_kind="relation_support", **relation_payload)


def _compile_requirement(
    result: ExplorationResult,
    requirement: EvidenceRequirement,
    decision: Any,
    *,
    parent_world_model_digest: str,
    evidence_packet_digest: str,
    evidence_artifact_ref: str,
) -> tuple[EvidenceProposal, ...]:
    if decision.status != "sufficient":
        return ()
    if decision.conclusion_kind == "absence" and not decision.absence_authorized:
        return ()
    coverage = result.coverage
    if coverage is None or coverage.sufficiency_decision is None:
        return ()
    candidate_rows = tuple(
        candidate
        for candidate in coverage.candidate_evidence
        if candidate.requirement_ref == requirement.requirement_ref
        and candidate.candidate_ref in decision.candidate_refs
    )
    claims_by_id = {claim.claim_id: claim for claim in coverage.claims}
    facts_by_claim = _fact_by_claim(result, claims_by_id)
    claims = tuple(
        claims_by_id[claim_ref]
        for candidate in candidate_rows
        for claim_ref in candidate.claim_refs
        if claim_ref in claims_by_id
    )
    claims = tuple(
        claims_by_id[claim_id]
        for claim_id in dict.fromkeys(claim.claim_id for claim in claims)
    )
    source_map = {
        source.reference: source
        for source in result.evidence_bundle.sources
        if source.reference
    }
    observation_refs = _refs(
        candidate.observation_refs for candidate in candidate_rows
    )
    source_refs = _refs(
        candidate.source_refs for candidate in candidate_rows
    )
    if not source_refs:
        source_refs = _refs(claim.source_refs for claim in claims)
    evidence_refs = _refs(
        candidate.claim_refs for candidate in candidate_rows
    )
    evidence_refs = _refs(evidence_refs, observation_refs)
    supporting_refs = _refs(
        candidate.claim_refs
        for candidate in candidate_rows
        if candidate.support_status == "supported"
    )
    supporting_refs = _refs(supporting_refs, observation_refs, source_refs)
    opposing_refs = _refs(
        candidate.claim_refs
        for candidate in candidate_rows
        if candidate.support_status == "contradicted"
    )
    if not source_refs:
        if decision.conclusion_kind != "absence":
            return ()
        source_refs = tuple(source.reference for source in source_map.values())
    if decision.conclusion_kind == "absence":
        subject_ref = _subject_ref(requirement, ())
        if not subject_ref or not source_refs:
            return ()
        absence_refs = _refs(
            evidence_refs,
            source_refs,
            decision.conflict_refs,
        )
        if not absence_refs:
            return ()
        payload = _common(
            requirement=requirement,
            candidates=(),
            claims=claims,
            sources=source_map,
            observation_refs=observation_refs,
            source_refs=source_refs,
            evidence_refs=absence_refs,
            supporting_refs=_refs(supporting_refs, source_refs),
            opposing_refs=opposing_refs,
            parent_world_model_digest=parent_world_model_digest,
            evidence_packet_digest=evidence_packet_digest,
            evidence_artifact_ref=evidence_artifact_ref,
            policy_version=decision.policy_version,
            predicate=_first((str(requirement.metadata.get("predicate") or ""), "exists")),
            subject_ref=subject_ref,
            value=None,
            conclusion_kind="absence",
            absence_authorized=True,
        )
        return (_typed_proposal("property_assertion", payload),)

    subject_ref = _subject_ref(requirement, decision.candidate_refs)
    if not subject_ref or not candidate_rows:
        return ()
    payload = _common(
        requirement=requirement,
        candidates=candidate_rows,
        claims=claims,
        sources=source_map,
        observation_refs=observation_refs,
        source_refs=source_refs,
        evidence_refs=evidence_refs,
        supporting_refs=supporting_refs,
        opposing_refs=opposing_refs,
        parent_world_model_digest=parent_world_model_digest,
        evidence_packet_digest=evidence_packet_digest,
        evidence_artifact_ref=evidence_artifact_ref,
        policy_version=decision.policy_version,
        predicate="supports_entity",
        subject_ref=subject_ref,
        value=_first(candidate.statement for candidate in candidate_rows),
    )

    relations = result.evidence_packet.relation_evidence if result.evidence_packet else ()
    if requirement.kind == "spatial" and relations:
        proposals = tuple(
            proposal
            for relation in relations
            if (proposal := _proposal_for_relation(relation, payload=payload)) is not None
        )
        if proposals:
            return proposals

    representation_refs = _refs(
        candidate.representation_refs
        for candidate in (result.evidence_packet.candidate_refs if result.evidence_packet else ())
        if candidate.entity_refs and subject_ref in candidate.entity_refs
    )
    geometry_authority = _first(
        authority
        for candidate in candidate_rows
        for authority in candidate.geometry_authorities
        if authority == "data_resource_catalog"
    )
    if representation_refs and geometry_authority:
        representation_ref = representation_refs[0]
        representation_payload = dict(payload)
        representation_payload.update({
            "subject_ref": subject_ref,
            "predicate": "has_representation",
            "object_ref": representation_ref,
            "value": None,
        })
        return (_typed_proposal(
            "representation_support",
            representation_payload,
            representation_ref=representation_ref,
            geometry_authority=geometry_authority,
        ),)

    claim = claims[0] if claims else None
    fact = facts_by_claim.get(claim.claim_id) if claim is not None else None
    predicate, value = _claim_value(requirement, claim, fact)
    property_payload = dict(payload)
    property_payload.update({
        "subject_ref": subject_ref,
        "predicate": predicate,
        "value": value,
    })
    if requirement.kind == "identity":
        return (_typed_proposal("entity_support", payload),)
    return (_typed_proposal("property_assertion", property_payload),)


def build_evidence_proposals(
    result: ExplorationResult,
    *,
    round_id: str,
    wm_epoch: str,
    parent_world_model_digest: str,
    evidence_artifact_ref: str = "",
) -> EvidenceProposalBatch:
    """Compile only EV-02-authorized conclusions into a frozen proposal batch."""

    packet = result.evidence_packet
    coverage = result.coverage
    packet_digest = _digest(packet) if packet is not None else "sha256:empty-evidence-packet"
    requirement_digest = (
        coverage.requirement_set_fingerprint
        if coverage is not None
        else "sha256:empty-requirement-set"
    )
    if coverage is None or coverage.sufficiency_decision is None:
        return EvidenceProposalBatch(
            round_id=round_id,
            wm_epoch=wm_epoch,
            parent_world_model_digest=parent_world_model_digest,
            requirement_set_digest=requirement_digest,
            evidence_packet_digest=packet_digest,
        )
    requirements = {item.requirement_ref: item for item in coverage.requirements}
    proposals: list[EvidenceProposal] = []
    for decision in coverage.sufficiency_decision.requirement_decisions:
        requirement = requirements.get(decision.requirement_ref)
        if requirement is None:
            continue
        proposals.extend(_compile_requirement(
            result,
            requirement,
            decision,
            parent_world_model_digest=parent_world_model_digest,
            evidence_packet_digest=packet_digest,
            evidence_artifact_ref=evidence_artifact_ref,
        ))
    return EvidenceProposalBatch(
        round_id=round_id,
        wm_epoch=wm_epoch,
        parent_world_model_digest=parent_world_model_digest,
        requirement_set_digest=requirement_digest,
        evidence_packet_digest=packet_digest,
        proposals=tuple(proposals),
    )


def to_cognition_assertion_proposals(
    batch: EvidenceProposalBatch,
) -> tuple[AssertionProposal, ...]:
    """Convert Evidence proposals to Cognition inputs without evaluating or committing."""

    return batch.to_assertion_proposals()


__all__ = [
    "build_evidence_proposals",
    "to_cognition_assertion_proposals",
]
