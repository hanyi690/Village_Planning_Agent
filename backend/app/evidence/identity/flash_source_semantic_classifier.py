"""L1-constrained, closed-set source-label semantic classification.

The model may choose among materialized candidates, but it cannot create a
meaning, feature ID, fact reference, geometry, or coordinate.  Ambiguous raw
labels therefore remain unresolved instead of entering source binding.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from app.contracts.domain.l1_contracts import L1Fact
from app.contracts.evidence.source_semantic_contracts import (
    SourceFeatureDescriptor,
    SourceFeatureSemanticDecision,
    SourceFeatureSemanticProposal,
    SourceFeatureSemanticProposalBatch,
    SourceSemanticCandidate,
    SourceSemanticClassificationSnapshot,
)
from app.evidence.identity.source_semantic_store import SourceSemanticStore
from app.infrastructure.llm.structured import run_structured_output
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

PROMPT_VERSION = "source-semantic-v1"
MAX_BATCH_SIZE = 32

_ENTITY_TYPES = {
    "facility", "设施", "service", "服务点", "road", "道路", "axis", "轴线",
    "water", "水体", "village", "自然村", "settlement", "landmark", "地标",
    "area", "区域", "place", "地点",
}
_LAYER_BY_TYPE = {
    "facility": ("annotations_current", "facilities_current"),
    "设施": ("annotations_current", "facilities_current"),
    "service": ("annotations_current", "facilities_current"),
    "服务点": ("annotations_current", "facilities_current"),
    "road": ("roads_current", "current_road"),
    "道路": ("roads_current", "current_road"),
    "axis": ("roads_current", "current_road"),
    "轴线": ("roads_current", "current_road"),
}
_GEOMETRY_BY_TYPE = {
    "facility": ("Point", "MultiPoint"),
    "设施": ("Point", "MultiPoint"),
    "service": ("Point", "MultiPoint"),
    "服务点": ("Point", "MultiPoint"),
    "road": ("LineString", "MultiLineString"),
    "道路": ("LineString", "MultiLineString"),
    "axis": ("LineString", "MultiLineString"),
    "轴线": ("LineString", "MultiLineString"),
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _fold(value: Any) -> str:
    return "".join(_text(value).split()).casefold()


def _digest(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _as_descriptor(value: SourceFeatureDescriptor | Mapping[str, Any]) -> SourceFeatureDescriptor:
    return value if isinstance(value, SourceFeatureDescriptor) else SourceFeatureDescriptor.model_validate(value)


def _fact_phrase(fact: L1Fact) -> str:
    attrs = dict(fact.attributes or {})
    for key in ("canonical_name", "normalized_name", "mention", "entity_name"):
        phrase = _text(attrs.get(key))
        if phrase:
            return phrase
    return _text(fact.subject_scope)


def _fact_type(fact: L1Fact) -> str:
    return _text(fact.semantic_type).casefold()


def _candidate_from_l1(fact: L1Fact) -> SourceSemanticCandidate | None:
    semantic_type = _fact_type(fact)
    phrase = _fact_phrase(fact)
    if not phrase or semantic_type not in _ENTITY_TYPES:
        return None
    return SourceSemanticCandidate(
        candidate_ref=f"l1:{fact.fact_id}:entity",
        display_phrase=phrase,
        origin="l1_fact",
        supporting_fact_refs=[fact.fact_id],
        compatible_layers=list(_LAYER_BY_TYPE.get(semantic_type, ())),
        compatible_geometry_kinds=list(_GEOMETRY_BY_TYPE.get(semantic_type, ())),
    )


def materialize_candidate_vocabulary(
    l1_facts: Iterable[L1Fact],
    kg_candidates: Iterable[SourceSemanticCandidate | Mapping[str, Any]] = (),
) -> list[SourceSemanticCandidate]:
    """Build a snapshot-local closed set; no global semantic table is read."""
    candidates: dict[str, SourceSemanticCandidate] = {}
    for fact in l1_facts:
        candidate = _candidate_from_l1(fact)
        if candidate is not None:
            candidates[candidate.candidate_ref] = candidate
    for raw in kg_candidates:
        candidate = (
            raw
            if isinstance(raw, SourceSemanticCandidate)
            else SourceSemanticCandidate.model_validate(raw)
        )
        candidates[candidate.candidate_ref] = candidate

    # A KG concept that exactly supports one L1 candidate enriches that
    # candidate with canonical provenance.  It must not create a second
    # same-label choice, otherwise an audited exact source label would become
    # ambiguous merely because the KG also knows the concept.  If multiple
    # L1 facts share the label, retain the ambiguity and do not merge.
    values = list(candidates.values())
    merged: dict[str, SourceSemanticCandidate] = {}
    for candidate in values:
        if candidate.origin != "kg_snapshot":
            merged[candidate.candidate_ref] = candidate
            continue
        matching_l1 = [
            item
            for item in values
            if item.origin == "l1_fact"
            and _fold(item.display_phrase) == _fold(candidate.display_phrase)
            and item.compatible_layers == candidate.compatible_layers
            and item.compatible_geometry_kinds == candidate.compatible_geometry_kinds
        ]
        if len(matching_l1) != 1:
            merged[candidate.candidate_ref] = candidate
            continue
        item = matching_l1[0]
        merged[item.candidate_ref] = item.model_copy(update={
            "supporting_fact_refs": list(dict.fromkeys([
                *item.supporting_fact_refs,
                *candidate.supporting_fact_refs,
            ])),
            "optional_kg_concept_ref": candidate.optional_kg_concept_ref,
        })
    return sorted(merged.values(), key=lambda item: item.candidate_ref)


def _candidate_allowed(
    candidate: SourceSemanticCandidate,
    item: SourceFeatureDescriptor,
) -> bool:
    if candidate.compatible_layers and item.layer_key not in candidate.compatible_layers:
        return False
    if candidate.compatible_geometry_kinds and item.geometry_kind not in candidate.compatible_geometry_kinds:
        return False
    return True


def _candidate_fact_refs(candidate: SourceSemanticCandidate) -> set[str]:
    return {str(value).strip() for value in candidate.supporting_fact_refs if str(value).strip()}


def _source_fingerprint(
    *,
    source_snapshot_ref: str,
    source_snapshot_digest: str,
    items: Sequence[SourceFeatureDescriptor],
    l1_facts: Sequence[L1Fact],
    candidates: Sequence[SourceSemanticCandidate],
    model_id: str,
    effective_temperature: float,
) -> tuple[str, str, str, str]:
    normalized_items = [item.model_dump(mode="json") for item in sorted(items, key=lambda value: value.source_feature_id)]
    normalized_facts = [fact.model_dump(mode="json") for fact in sorted(l1_facts, key=lambda value: value.fact_id)]
    normalized_candidates = [item.model_dump(mode="json") for item in candidates]
    input_digest = _digest({"items": normalized_items, "facts": normalized_facts, "candidates": normalized_candidates})
    l1_fingerprint = _digest(normalized_facts)
    vocabulary_fingerprint = _digest(normalized_candidates)
    fingerprint = _digest({
        "source_snapshot_ref": source_snapshot_ref,
        "source_snapshot_digest": source_snapshot_digest,
        "input_digest": input_digest,
        "l1_fingerprint": l1_fingerprint,
        "vocabulary_fingerprint": vocabulary_fingerprint,
        "prompt_version": PROMPT_VERSION,
        "model_id": model_id,
        "effective_temperature": effective_temperature,
        "schema_version": "1.0",
    })
    return fingerprint, input_digest, l1_fingerprint, vocabulary_fingerprint


def _exact_decisions(
    items: Sequence[SourceFeatureDescriptor],
    candidates: Sequence[SourceSemanticCandidate],
) -> tuple[dict[str, SourceFeatureSemanticDecision], list[SourceFeatureDescriptor]]:
    by_label: dict[str, list[SourceSemanticCandidate]] = {}
    for candidate in candidates:
        by_label.setdefault(_fold(candidate.display_phrase), []).append(candidate)
    decisions: dict[str, SourceFeatureSemanticDecision] = {}
    unresolved: list[SourceFeatureDescriptor] = []
    for item in items:
        matches = [candidate for candidate in by_label.get(_fold(item.raw_label), []) if _candidate_allowed(candidate, item)]
        if len(matches) == 1 and _fold(item.raw_label):
            candidate = matches[0]
            decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                source_feature_id=item.source_feature_id,
                raw_label=item.raw_label,
                semantic_type=candidate.display_phrase,
                status="accepted",
                authority="canonical_exact",
                candidate_ref=candidate.candidate_ref,
                optional_kg_concept_ref=candidate.optional_kg_concept_ref,
                supporting_fact_refs=list(candidate.supporting_fact_refs),
                reason="normalized exact equality with current snapshot vocabulary",
            )
        else:
            unresolved.append(item)
    return decisions, unresolved


def _proposal_payload(batch: Sequence[SourceFeatureDescriptor], candidates: Sequence[SourceSemanticCandidate]) -> dict[str, Any]:
    return {
        "source_items": [item.model_dump(mode="json") for item in sorted(batch, key=lambda value: value.source_feature_id)],
        "l1_candidates": [candidate.model_dump(mode="json") for candidate in candidates],
        "instruction": "每个 source_feature_id 必须出现一次；只能选择 candidate_ref 或明确 abstain；不得创建任何新 ID、语义、坐标或几何。",
    }


def _proposal_digest(proposals: Sequence[SourceFeatureSemanticProposal]) -> str:
    return _digest([item.model_dump(mode="json") for item in sorted(proposals, key=lambda value: value.source_feature_id)])


def _verify_proposals(
    proposals: SourceFeatureSemanticProposalBatch,
    items: Sequence[SourceFeatureDescriptor],
    candidates_by_ref: Mapping[str, SourceSemanticCandidate],
) -> tuple[bool, list[str]]:
    findings: list[str] = []
    expected_ids = [item.source_feature_id for item in items]
    actual_ids = [proposal.source_feature_id for proposal in proposals.proposals]
    if len(actual_ids) != len(set(actual_ids)):
        findings.append("duplicate source feature IDs")
    if sorted(actual_ids) != sorted(expected_ids):
        findings.append("proposal member set does not exactly match source batch")
    item_by_id = {item.source_feature_id: item for item in items}
    for proposal in proposals.proposals:
        candidate_ref = _text(proposal.candidate_ref)
        if not candidate_ref:
            if proposal.supporting_fact_refs:
                findings.append(f"abstention has supporting refs:{proposal.source_feature_id}")
            continue
        candidate = candidates_by_ref.get(candidate_ref)
        if candidate is None:
            findings.append(f"foreign candidate ref:{candidate_ref}")
            continue
        if not _candidate_allowed(candidate, item_by_id.get(proposal.source_feature_id, SourceFeatureDescriptor(
            source_feature_id="missing", layer_key="", geometry_kind=""
        ))):
            findings.append(f"candidate geometry/layer mismatch:{proposal.source_feature_id}")
        refs = set(proposal.supporting_fact_refs)
        if not refs or not refs.issubset(_candidate_fact_refs(candidate)):
            findings.append(f"foreign or missing supporting fact refs:{proposal.source_feature_id}")
    return not findings, findings


def _expected_counts(l1_facts: Sequence[L1Fact], candidate: SourceSemanticCandidate) -> int | None:
    expected: list[int] = []
    for fact in l1_facts:
        if fact.fact_id not in candidate.supporting_fact_refs or fact.value is None:
            continue
        try:
            value = int(fact.value)
        except (TypeError, ValueError):
            continue
        if value >= 0 and fact.unit:
            expected.append(value)
    return expected[0] if len(set(expected)) == 1 else None


def _check_cardinality(
    proposals: Sequence[SourceFeatureSemanticProposal],
    candidates: Sequence[SourceSemanticCandidate],
    l1_facts: Sequence[L1Fact],
) -> list[str]:
    findings: list[str] = []
    by_ref = {candidate.candidate_ref: candidate for candidate in candidates}
    for candidate in candidates:
        expected = _expected_counts(l1_facts, candidate)
        if expected is None:
            continue
        actual = sum(1 for proposal in proposals if proposal.candidate_ref == candidate.candidate_ref)
        if actual != expected:
            findings.append(
                f"cardinality mismatch:{candidate.candidate_ref}:expected={expected}:actual={actual}"
            )
    return findings


@dataclass
class SourceSemanticClassifier:
    """Bounded classifier with two-pass agreement and resumable cache."""

    llm: Any | None = None
    store: SourceSemanticStore | None = None
    model_id: str = "flash-source-semantic"
    effective_temperature: float = 0.0
    timeout: float = 20.0

    async def classify(
        self,
        *,
        source_snapshot_ref: str,
        source_snapshot_digest: str,
        source_items: Sequence[SourceFeatureDescriptor | Mapping[str, Any]],
        l1_facts: Sequence[L1Fact],
        kg_candidates: Iterable[SourceSemanticCandidate | Mapping[str, Any]] = (),
        store: SourceSemanticStore | None = None,
    ) -> SourceSemanticClassificationSnapshot:
        items = sorted([_as_descriptor(item) for item in source_items], key=lambda value: value.source_feature_id)
        facts = sorted(list(l1_facts), key=lambda value: value.fact_id)
        candidates = materialize_candidate_vocabulary(facts, kg_candidates)
        fingerprint, input_digest, l1_fingerprint, vocabulary_fingerprint = _source_fingerprint(
            source_snapshot_ref=source_snapshot_ref,
            source_snapshot_digest=source_snapshot_digest,
            items=items,
            l1_facts=facts,
            candidates=candidates,
            model_id=self.model_id,
            effective_temperature=self.effective_temperature,
        )
        cache = store or self.store
        cached = cache.get(fingerprint) if cache is not None else None
        if cached is not None:
            return cached

        decisions, unresolved = _exact_decisions(items, candidates)
        # Do not spend a provider call on a source item for which the closed
        # vocabulary has no layer/geometry-compatible candidate.  This is
        # especially important for a normal village snapshot: an L1 facility
        # fact must not cause every unnamed current road to be sent to
        # MiniMax, and an L1 road fact must not cause every point annotation
        # to be classified against an impossible candidate.  The item still
        # receives an explicit unresolved decision, so this is not a fallback
        # or a silent omission.
        classifiable: list[SourceFeatureDescriptor] = []
        for item in unresolved:
            if any(_candidate_allowed(candidate, item) for candidate in candidates):
                classifiable.append(item)
                continue
            decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                source_feature_id=item.source_feature_id,
                raw_label=item.raw_label,
                status="unresolved",
                authority="inferred_current",
                reason="no layer/geometry-compatible closed-set candidate",
            )
        unresolved = classifiable
        raw_digests: list[str] = []
        findings: list[str] = []
        for start in range(0, len(unresolved), MAX_BATCH_SIZE):
            batch = unresolved[start : start + MAX_BATCH_SIZE]
            if self.llm is None or not candidates:
                for item in batch:
                    decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                        source_feature_id=item.source_feature_id,
                        raw_label=item.raw_label,
                        status="unresolved",
                        authority="inferred_current",
                        reason="semantic classifier unavailable or vocabulary empty",
                    )
                continue
            messages = [
                {
                    "role": "system",
                    "content": (
                        "你是当前 GIS 快照的闭集语义分类器。只返回根对象 "
                        "{\"proposals\":[...]}，根对象不得有其他字段；每个输入 source_feature_id "
                        "必须恰好返回一个 proposal，不能缺失、重复或新增。proposal 只能包含 "
                        "source_feature_id、candidate_ref、supporting_fact_refs 三个字段。candidate_ref "
                        "只能逐字选择给定 candidates 中的 candidate_ref；无法由当前 L1/KG 证据证明时必须为 null。"
                        "candidate_ref 非 null 时 supporting_fact_refs 只能逐字选择给定事实引用，且至少一个；"
                        "abstain 时 supporting_fact_refs 返回空数组。不得输出 semantic_type、status、BSM、"
                        "坐标、几何或任何未提供的候选。"
                    ),
                },
                {"role": "user", "content": json.dumps(_proposal_payload(batch, candidates), ensure_ascii=False, sort_keys=True)},
            ]
            passes: list[SourceFeatureSemanticProposalBatch] = []
            for pass_number in range(2):
                try:
                    proposal = await run_structured_output(
                        SourceFeatureSemanticProposalBatch,
                        messages,
                        max_retries=1,
                        timeout=self.timeout,
                        temperature=self.effective_temperature,
                        max_tokens=1800,
                        allow_content_json_fallback=False,
                        llm=self.llm,
                        context={"pass": pass_number + 1, "fingerprint": fingerprint},
                    )
                    passes.append(proposal)
                    raw_digests.append(_proposal_digest(proposal.proposals))
                except Exception as exc:  # noqa: BLE001 - unresolved is the safe result
                    findings.append(f"structured proposal failed:{type(exc).__name__}")
            if len(passes) != 2:
                for item in batch:
                    decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                        source_feature_id=item.source_feature_id,
                        raw_label=item.raw_label,
                        status="unresolved",
                        authority="inferred_current",
                        reason="proposal pass failed",
                    )
                continue
            verified = []
            for proposal in passes:
                valid, verifier_findings = _verify_proposals(proposal, batch, {item.candidate_ref: item for item in candidates})
                if not valid:
                    findings.extend(verifier_findings)
                else:
                    cardinality_findings = _check_cardinality(proposal.proposals, candidates, facts)
                    if cardinality_findings:
                        findings.extend(cardinality_findings)
                    else:
                        verified.append(proposal)
            if len(verified) != 2 or _proposal_digest(verified[0].proposals) != _proposal_digest(verified[1].proposals):
                reason = "two typed proposal passes disagree" if len(verified) == 2 else "proposal verification failed"
                for item in batch:
                    decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                        source_feature_id=item.source_feature_id,
                        raw_label=item.raw_label,
                        status="ambiguous" if len(verified) == 2 else "unresolved",
                        authority="inferred_current",
                        reason=reason,
                        proposal_digests=list(raw_digests[-2:]),
                    )
                continue
            selected = {proposal.source_feature_id: proposal for proposal in verified[0].proposals}
            by_ref = {candidate.candidate_ref: candidate for candidate in candidates}
            for item in batch:
                proposal = selected[item.source_feature_id]
                candidate = by_ref.get(_text(proposal.candidate_ref))
                if candidate is None:
                    decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                        source_feature_id=item.source_feature_id,
                        raw_label=item.raw_label,
                        status="unresolved",
                        authority="inferred_current",
                        reason="model abstained",
                        proposal_digests=list(raw_digests[-2:]),
                    )
                else:
                    decisions[item.source_feature_id] = SourceFeatureSemanticDecision(
                        source_feature_id=item.source_feature_id,
                        raw_label=item.raw_label,
                        semantic_type=candidate.display_phrase,
                        status="accepted",
                        authority="inferred_current",
                        candidate_ref=candidate.candidate_ref,
                        optional_kg_concept_ref=candidate.optional_kg_concept_ref,
                        supporting_fact_refs=list(proposal.supporting_fact_refs),
                        proposal_digests=list(raw_digests[-2:]),
                    )

        snapshot = SourceSemanticClassificationSnapshot(
            source_snapshot_ref=source_snapshot_ref,
            source_snapshot_digest=source_snapshot_digest,
            l1_fact_fingerprint=l1_fingerprint,
            vocabulary_fingerprint=vocabulary_fingerprint,
            prompt_version=PROMPT_VERSION,
            model_id=self.model_id,
            effective_temperature=self.effective_temperature,
            normalized_input_digest=input_digest,
            raw_output_digests=list(dict.fromkeys(raw_digests)),
            verifier_findings=list(dict.fromkeys(findings)),
            decisions=[decisions[key] for key in sorted(decisions)],
            fingerprint=fingerprint,
        )
        if cache is not None:
            cache.put(snapshot)
        return snapshot


def accepted_semantic_decisions(
    snapshot: SourceSemanticClassificationSnapshot,
) -> dict[str, Any]:
    """Expose only accepted decisions to the binding boundary."""
    return {
        decision.source_feature_id: decision
        for decision in snapshot.decisions
        if decision.status == "accepted"
    }


def create_minimax_source_semantic_classifier(
    *,
    timeout: float = 20.0,
) -> SourceSemanticClassifier:
    """Construct the production classifier with an explicit MiniMax client.

    Provider construction errors are intentionally raised to the caller.  The
    workflow records that failure as an unresolved semantic stage; it does not
    switch to another provider or a text heuristic.
    """
    from app.core.settings import MINIMAX_MODEL
    from app.infrastructure.llm.factory import get_minimax_llm

    effective_temperature = 0.01
    llm = get_minimax_llm(
        model=MINIMAX_MODEL,
        temperature=effective_temperature,
        max_tokens=1800,
    )
    return SourceSemanticClassifier(
        llm=llm,
        model_id=MINIMAX_MODEL,
        effective_temperature=effective_temperature,
        timeout=timeout,
    )


__all__ = [
    "MAX_BATCH_SIZE",
    "PROMPT_VERSION",
    "SourceSemanticClassifier",
    "accepted_semantic_decisions",
    "create_minimax_source_semantic_classifier",
    "materialize_candidate_vocabulary",
]
