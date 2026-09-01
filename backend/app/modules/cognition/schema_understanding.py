"""Collection-scoped schema understanding with bounded table LLM pages.

DATA remains lossless and field-agnostic. This module profiles physical
collections, retrieves a closed semantic candidate set, and optionally asks
the shared structured runtime to rank or abstain. No proposal can rename a
source field, create an entity, or supply geometry.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from app.contracts.cognition.decision import (
    SchemaMappingDecision,
    SchemaMappingProposal,
    SchemaMappingProposalBatch,
    SourceCollectionProfile,
    SCHEMA_MAPPING_CODE_CONTRACT_VERSION,
    SourceFieldProfile,
    SourceSemanticMappingSnapshot,
)
from app.infrastructure.cognition_runtime.schema_matcher import (
    candidate_digest,
    collection_concept_candidates,
    property_candidates,
    representation_role_candidates,
    validate_proposals,
)


_CONCEPT_FIELD = "__concept__"
_REPRESENTATION_FIELD = "__representation__"
_LLM_PAGE_SIZE = 24
_SAMPLE_LIMIT = 6
_SAMPLE_CHAR_LIMIT = 96


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _text(value: Any) -> str:
    return str(value or "").strip()


def _collection_ref(dataset_ref: str, layer_ref: str) -> str:
    material = f"{dataset_ref}\n{layer_ref}"
    return "source-collection:" + hashlib.sha256(
        material.encode("utf-8")
    ).hexdigest()[:24]


def _representation_field(geometry_kind: str) -> str:
    return f"{_REPRESENTATION_FIELD}:{str(geometry_kind).casefold()}"


def build_collection_profiles(catalog: Any) -> tuple[SourceCollectionProfile, ...]:
    """Profile arbitrary DATA collections without promoting source fields."""

    snapshot = getattr(catalog, "snapshot", catalog)
    grouped: dict[tuple[str, str], list[Any]] = defaultdict(list)
    for feature in tuple(getattr(snapshot, "features", ()) or ()):
        grouped[(
            _text(getattr(feature, "dataset_ref", "")),
            _text(getattr(feature, "layer_ref", "")),
        )].append(feature)

    profiles: list[SourceCollectionProfile] = []
    for (dataset_ref, layer_ref), features in sorted(grouped.items()):
        type_sets: dict[str, set[str]] = defaultdict(set)
        non_null_counts: dict[str, int] = defaultdict(int)
        sample_values: dict[str, list[str]] = defaultdict(list)
        for feature in features:
            attributes = dict(getattr(feature, "raw_attributes", {}) or {})
            for raw_name, value in sorted(attributes.items(), key=lambda item: str(item[0])):
                field_name = str(raw_name)
                if value in (None, "", [], {}, ()):
                    continue
                type_sets[field_name].add(type(value).__name__)
                non_null_counts[field_name] += 1
                sample = _text(value)[:_SAMPLE_CHAR_LIMIT]
                if sample and sample not in sample_values[field_name]:
                    if len(sample_values[field_name]) < _SAMPLE_LIMIT:
                        sample_values[field_name].append(sample)
        field_names = sorted({
            str(key)
            for feature in features
            for key in dict(getattr(feature, "raw_attributes", {}) or {})
        })
        field_profiles = tuple(
            SourceFieldProfile(
                field_name=field_name,
                physical_types=tuple(sorted(type_sets.get(field_name, set()))),
                non_null_count=non_null_counts.get(field_name, 0),
                distinct_sample_count=len(sample_values.get(field_name, ())),
                sample_values=tuple(sample_values.get(field_name, ())),
            )
            for field_name in field_names
        )
        geometry_kinds = tuple(sorted({
            _text(getattr(feature, "geometry_kind", "unknown")) or "unknown"
            for feature in features
        }))
        source_feature_refs = tuple(sorted({
            _text(getattr(feature, "source_feature_ref", ""))
            for feature in features
            if _text(getattr(feature, "source_feature_ref", ""))
        }))
        source_record_refs = tuple(sorted({
            (
                f"resource:{getattr(feature, 'dataset_ref', '')}:"
                f"{getattr(feature, 'source_feature_ref', '')}"
            )
            for feature in features
            if _text(getattr(feature, "source_feature_ref", ""))
        }))
        schema_material = {
            "dataset_ref": dataset_ref,
            "layer_ref": layer_ref,
            "geometry_kinds": geometry_kinds,
            "fields": [
                {
                    "field_name": item.field_name,
                    "physical_types": item.physical_types,
                }
                for item in field_profiles
            ],
        }
        content_material = tuple(sorted(
            _text(getattr(feature, "source_feature_digest", ""))
            for feature in features
        ))
        profiles.append(SourceCollectionProfile(
            collection_ref=_collection_ref(dataset_ref, layer_ref),
            dataset_ref=dataset_ref,
            layer_ref=layer_ref,
            geometry_kinds=geometry_kinds,
            feature_count=len(features),
            source_record_refs=source_record_refs,
            source_feature_refs=source_feature_refs,
            field_profiles=field_profiles,
            schema_digest=_digest(schema_material),
            content_digest=_digest(content_material),
        ))
    return tuple(profiles)


def _mapping_rows(
    profiles: Sequence[SourceCollectionProfile],
) -> tuple[list[dict[str, Any]], dict[tuple[str, str], tuple[str, ...]]]:
    rows: list[dict[str, Any]] = []
    membership: dict[tuple[str, str], tuple[str, ...]] = {}
    for profile in profiles:
        samples = [
            value
            for field in profile.field_profiles
            for value in field.sample_values[:2]
        ][:_SAMPLE_LIMIT]
        concepts = tuple(collection_concept_candidates(
            layer_name=profile.layer_ref,
            geometry_kinds=profile.geometry_kinds,
            field_names=tuple(item.field_name for item in profile.field_profiles),
            sample_values=tuple(samples),
        ))
        membership[(profile.collection_ref, _CONCEPT_FIELD)] = concepts
        rows.append({
            "collection_ref": profile.collection_ref,
            "dataset_ref": profile.dataset_ref,
            "layer_ref": profile.layer_ref,
            "field_name": _CONCEPT_FIELD,
            "target_kind": "collection_concept",
            "physical_types": "",
            "geometry_kinds": ", ".join(profile.geometry_kinds),
            "sample_values": "",
            "candidate_refs": concepts,
            "feature_count": profile.feature_count,
        })
        for geometry_kind in profile.geometry_kinds:
            representation_field = _representation_field(geometry_kind)
            roles = tuple(representation_role_candidates((geometry_kind,)))
            membership[(profile.collection_ref, representation_field)] = roles
            rows.append({
                "collection_ref": profile.collection_ref,
                "dataset_ref": profile.dataset_ref,
                "layer_ref": profile.layer_ref,
                "field_name": representation_field,
                "target_kind": "representation_role",
                "physical_types": "",
                "geometry_kinds": geometry_kind,
                "sample_values": "",
                "candidate_refs": roles,
                "feature_count": profile.feature_count,
            })
        for field in profile.field_profiles:
            candidates = tuple(property_candidates(
                field.field_name,
                physical_type=field.physical_types[0] if len(field.physical_types) == 1 else "",
                samples=field.sample_values,
            ))
            membership[(profile.collection_ref, field.field_name)] = candidates
            rows.append({
                "collection_ref": profile.collection_ref,
                "dataset_ref": profile.dataset_ref,
                "layer_ref": profile.layer_ref,
                "field_name": field.field_name,
                "target_kind": "property",
                "physical_types": ", ".join(field.physical_types),
                "geometry_kinds": ", ".join(profile.geometry_kinds),
                "sample_values": " | ".join(field.sample_values),
                "candidate_refs": candidates,
                "feature_count": profile.feature_count,
            })
    return rows, membership


def _proposal_key(value: Mapping[str, Any] | SchemaMappingProposal) -> tuple[str, str]:
    if isinstance(value, Mapping):
        return _text(value.get("collection_ref")), _text(value.get("field_name"))
    return _text(value.collection_ref), _text(value.field_name)


def _finalize_snapshot(
    catalog: Any,
    *,
    profiles: Sequence[SourceCollectionProfile],
    rows: Sequence[Mapping[str, Any]],
    membership: Mapping[tuple[str, str], Sequence[str]],
    proposals: Sequence[Mapping[str, Any] | SchemaMappingProposal],
    source_snapshot_ref: str,
    prompt_version: str,
    model_id: str,
    extra_findings: Sequence[str] = (),
    raw_output_material: Sequence[Any] | None = None,
) -> SourceSemanticMappingSnapshot:
    snapshot = getattr(catalog, "snapshot", catalog)
    verified, verifier_findings = validate_proposals(proposals, membership)
    verified_by_key: dict[tuple[str, str], dict[str, Any]] = {}
    duplicate_keys: set[tuple[str, str]] = set()
    for item in verified:
        key = _proposal_key(item)
        if key in verified_by_key:
            duplicate_keys.add(key)
        verified_by_key[key] = item
    profile_by_ref = {item.collection_ref: item for item in profiles}
    decisions: list[SchemaMappingDecision] = []
    for row in rows:
        collection_ref = _text(row.get("collection_ref"))
        field_name = _text(row.get("field_name"))
        key = (collection_ref, field_name)
        candidates = tuple(sorted({str(item) for item in membership.get(key, ())}))
        profile = profile_by_ref[collection_ref]
        material = {
            "source_snapshot_digest": _text(getattr(snapshot, "digest", "")),
            "collection_ref": collection_ref,
            "field_name": field_name,
            "candidate_refs": candidates,
        }
        decision_ref = "schema-decision:" + _digest(material).removeprefix("sha256:")[:24]
        selected = verified_by_key.get(key)
        if key in duplicate_keys:
            selected = None
            status = "rejected"
            reason = "duplicate_provider_rows"
        elif selected is None:
            status = "unresolved"
            reason = "no_closed_set_candidate" if not candidates else "model_abstained_or_not_called"
        else:
            status = str(selected.get("status") or "unresolved")
            reason = str(selected.get("reason") or "")
        source_record_refs = tuple(profile.source_record_refs or ())
        decisions.append(SchemaMappingDecision(
            decision_ref=decision_ref,
            collection_ref=collection_ref,
            field_name=field_name,
            candidate_property_ref=(
                str(selected.get("candidate_property_ref") or "") if selected else ""
            ),
            candidate_concept_ref=(
                str(selected.get("candidate_concept_ref") or "") if selected else ""
            ),
            representation_role_ref=(
                str(selected.get("representation_role_ref") or "") if selected else ""
            ),
            status=status,
            confidence=float(selected.get("confidence") or 0.0) if selected else 0.0,
            candidate_refs=candidates,
            reason=reason,
            source_feature_count=len(source_record_refs),
            source_feature_digest=_digest(source_record_refs),
        ))
    profile_digest = _digest([
        item.model_dump(mode="json") for item in profiles
    ])
    normalized_proposals = [
        item.model_dump(mode="json")
        if isinstance(item, SchemaMappingProposal)
        else dict(item)
        for item in proposals
    ]
    decision_payload = [item.model_dump(mode="json") for item in decisions]
    resolved_source_snapshot_ref = (
        source_snapshot_ref
        or _text(getattr(snapshot, "snapshot_id", ""))
    )
    source_snapshot_digest = _text(getattr(snapshot, "digest", ""))
    input_digest = _digest(list(rows))
    resolved_candidate_digest = candidate_digest({
        f"{collection}:{field}": refs
        for (collection, field), refs in membership.items()
    })
    raw_output_digest = _digest(
        list(raw_output_material)
        if raw_output_material is not None
        else normalized_proposals
    )
    resolved_findings = tuple(dict.fromkeys([
        *extra_findings,
        *verifier_findings,
        *(
            f"duplicate proposal row:{collection}:{field}"
            for collection, field in sorted(duplicate_keys)
        ),
    ]))
    decision_fingerprint = _digest(decision_payload)
    mapping_fingerprint = _digest({
        "source_snapshot_ref": resolved_source_snapshot_ref,
        "source_snapshot_digest": source_snapshot_digest,
        "profile_digest": profile_digest,
        "input_digest": input_digest,
        "candidate_digest": resolved_candidate_digest,
        "prompt_version": prompt_version,
        "code_contract_version": SCHEMA_MAPPING_CODE_CONTRACT_VERSION,
        "model_id": model_id,
        "raw_output_digest": raw_output_digest,
        "decision_fingerprint": decision_fingerprint,
        "verifier_findings": resolved_findings,
    })
    return SourceSemanticMappingSnapshot(
        source_snapshot_ref=resolved_source_snapshot_ref,
        source_snapshot_digest=source_snapshot_digest,
        profile_digest=profile_digest,
        input_digest=input_digest,
        candidate_digest=resolved_candidate_digest,
        prompt_version=prompt_version,
        code_contract_version=SCHEMA_MAPPING_CODE_CONTRACT_VERSION,
        model_id=model_id,
        raw_output_digest=raw_output_digest,
        verifier_findings=resolved_findings,
        collection_profiles=tuple(profiles),
        decisions=tuple(decisions),
        decision_fingerprint=decision_fingerprint,
        mapping_fingerprint=mapping_fingerprint,
    )


def build_schema_mapping_snapshot(
    catalog: Any,
    *,
    proposal_provider: Callable[[list[dict[str, Any]]], list[Mapping[str, Any]]] | None = None,
    source_snapshot_ref: str = "",
    prompt_version: str = "schema-mapping-v2",
    model_id: str = "deterministic",
) -> SourceSemanticMappingSnapshot:
    """Build deterministic profiles and verify an optional proposal provider."""

    profiles = build_collection_profiles(catalog)
    rows, membership = _mapping_rows(profiles)
    proposals = proposal_provider(list(rows)) if proposal_provider is not None else []
    return _finalize_snapshot(
        catalog,
        profiles=profiles,
        rows=rows,
        membership=membership,
        proposals=proposals,
        source_snapshot_ref=source_snapshot_ref,
        prompt_version=prompt_version,
        model_id=model_id,
    )


def _page_prompt(rows: Sequence[Mapping[str, Any]]) -> str:
    from app.infrastructure.context_runtime import build_bounded_table

    table_rows = [
        {
            "collection_ref": row["collection_ref"],
            "layer": row["layer_ref"],
            "target": row["target_kind"],
            "field": row["field_name"],
            "physical_types": row["physical_types"],
            "geometry": row["geometry_kinds"],
            "samples": row["sample_values"],
            "candidate_refs": ", ".join(row["candidate_refs"]),
        }
        for row in rows
    ]
    _, table = build_bounded_table(
        (
            "collection_ref",
            "layer",
            "target",
            "field",
            "physical_types",
            "geometry",
            "samples",
            "candidate_refs",
        ),
        table_rows,
        max_rows=_LLM_PAGE_SIZE,
        max_chars=12_000,
    )
    return (
        "### 当前 Source Collection schema rows\n"
        f"{table}\n\n"
        "每行独立判断。只能逐字选择该行 candidate_refs 中的一个候选，或明确弃权；"
        "不得创建字段、候选、实体、坐标或几何。collection_concept 只填写 "
        "candidate_concept_ref，representation_role 只填写 representation_role_ref，"
        "property 只填写 candidate_property_ref；其余候选列必须为 null。"
    )


def _proposal_signature(batch: SchemaMappingProposalBatch) -> str:
    return _digest([
        {
            "collection_ref": item.collection_ref,
            "field_name": item.field_name,
            "candidate_property_ref": item.candidate_property_ref,
            "candidate_concept_ref": item.candidate_concept_ref,
            "representation_role_ref": item.representation_role_ref,
        }
        for item in sorted(batch.proposals, key=lambda value: (
            value.collection_ref,
            value.field_name,
        ))
    ])


def _consensus_proposals(
    left: SchemaMappingProposalBatch,
    right: SchemaMappingProposalBatch,
) -> tuple[tuple[SchemaMappingProposal, ...], tuple[tuple[str, str], ...]]:
    """Keep exact row choices agreed by both passes; lower confidence wins."""

    left_by_key = {_proposal_key(item): item for item in left.proposals}
    right_by_key = {_proposal_key(item): item for item in right.proposals}
    agreed: list[SchemaMappingProposal] = []
    disagreements: list[tuple[str, str]] = []
    for key in sorted(left_by_key):
        first = left_by_key[key]
        second = right_by_key[key]
        first_choice = (
            first.candidate_property_ref,
            first.candidate_concept_ref,
            first.representation_role_ref,
        )
        second_choice = (
            second.candidate_property_ref,
            second.candidate_concept_ref,
            second.representation_role_ref,
        )
        if first_choice != second_choice:
            disagreements.append(key)
            continue
        agreed.append(SchemaMappingProposal(
            collection_ref=first.collection_ref,
            field_name=first.field_name,
            candidate_property_ref=first.candidate_property_ref,
            candidate_concept_ref=first.candidate_concept_ref,
            representation_role_ref=first.representation_role_ref,
            confidence=min(first.confidence, second.confidence),
        ))
    return tuple(agreed), tuple(disagreements)


def _page_membership_valid(
    batch: SchemaMappingProposalBatch,
    rows: Sequence[Mapping[str, Any]],
) -> tuple[bool, str]:
    expected = sorted(
        (str(item["collection_ref"]), str(item["field_name"]))
        for item in rows
    )
    actual = sorted(_proposal_key(item) for item in batch.proposals)
    if len(actual) != len(set(actual)):
        return False, "duplicate proposal keys"
    if actual != expected:
        return False, "proposal page membership mismatch"
    return True, ""


async def build_schema_mapping_snapshot_async(
    catalog: Any,
    *,
    source_snapshot_ref: str = "",
    enabled: bool | None = None,
    llm: Any = None,
    prompt_version: str = "schema-mapping-v2",
    model_id: str = "",
) -> SourceSemanticMappingSnapshot:
    """Run verified, two-pass, bounded schema decisions through one LLM boundary."""

    profiles = build_collection_profiles(catalog)
    rows, membership = _mapping_rows(profiles)
    if enabled is None:
        from app.core.settings import SOURCE_SEMANTIC_LLM_ENABLED

        enabled = bool(SOURCE_SEMANTIC_LLM_ENABLED)
    if not enabled:
        return _finalize_snapshot(
            catalog,
            profiles=profiles,
            rows=rows,
            membership=membership,
            proposals=(),
            source_snapshot_ref=source_snapshot_ref,
            prompt_version=prompt_version,
            model_id="disabled",
            extra_findings=("schema mapping LLM disabled",),
        )

    from app.core.settings import LLM_MODEL
    from app.infrastructure.structured_runtime.facade import LLMCallSpec, run_structured

    resolved_model = model_id or str(LLM_MODEL or "configured-default")
    proposed_rows = [row for row in rows if row["candidate_refs"]]
    proposals: list[SchemaMappingProposal] = []
    findings: list[str] = []
    raw_output_material: list[dict[str, Any]] = []

    pages = [
        proposed_rows[start : start + _LLM_PAGE_SIZE]
        for start in range(0, len(proposed_rows), _LLM_PAGE_SIZE)
    ]

    async def run_pass(
        page_index: int,
        pass_number: int,
        page: list[dict[str, Any]],
    ) -> tuple[
        SchemaMappingProposalBatch | None,
        dict[str, Any] | None,
        str,
    ]:
        messages = [
            {
                "role": "system",
                "content": (
                    "你是 GIS Source Collection 的闭集 schema 认知器。输出必须是声明的平坦表格行契约；"
                    "每个输入 collection_ref+field 必须恰好返回一行。只能选择输入候选或弃权，"
                    "不能生成业务实体、权威身份、坐标、几何、规划结论或自由文本候选。"
                ),
            },
            {"role": "user", "content": _page_prompt(page)},
        ]
        try:
            result = await run_structured(
                LLMCallSpec(
                    stage="cognition",
                    contract_key="cognition.schema_mapping",
                    response_model=SchemaMappingProposalBatch,
                    call_type="closed_set",
                    max_retries=1,
                    timeout_s=90.0,
                    # A 24-row flat proposal table regularly exceeds 2,600
                    # tokens.  Starting at the bounded recovery ceiling avoids
                    # replaying the whole provider call after a predictable
                    # truncation; row count and closed candidate set still cap
                    # the output independently.
                    max_tokens=4200,
                    incomplete_output_max_tokens=4200,
                    temperature=0.01,
                    allow_content_json=True,
                    input_char_limit=16_000,
                ),
                messages,
                llm=llm,
                context={
                    "page_index": page_index,
                    "pass_number": pass_number,
                    "source_snapshot_ref": source_snapshot_ref,
                },
            )
            raw_output = {
                "page_index": page_index,
                "pass_number": pass_number,
                "proposals": [
                    item.model_dump(mode="json")
                    for item in result.proposals
                ],
            }
            valid, reason = _page_membership_valid(result, page)
            if not valid:
                return (
                    None,
                    raw_output,
                    f"page {page_index} pass {pass_number}: {reason}",
                )
            return result, raw_output, ""
        except Exception as exc:
            return (
                None,
                None,
                f"page {page_index} pass {pass_number} failed:{type(exc).__name__}",
            )

    pass_results = await asyncio.gather(*(
        run_pass(page_index, pass_number, page)
        for page_index, page in enumerate(pages)
        for pass_number in (1, 2)
    ))
    for page_index, _page in enumerate(pages):
        passes: list[SchemaMappingProposalBatch] = []
        for result, raw_output, finding in pass_results[
            page_index * 2 : page_index * 2 + 2
        ]:
            if raw_output is not None:
                raw_output_material.append(raw_output)
            if finding:
                findings.append(finding)
            if result is not None:
                passes.append(result)
        if len(passes) != 2:
            findings.append(f"page {page_index}: incomplete verified passes")
            continue
        consensus, disagreements = _consensus_proposals(passes[0], passes[1])
        proposals.extend(consensus)
        for collection_ref, field_name in disagreements:
            findings.append(
                f"page {page_index} row {collection_ref}:{field_name}: "
                "two-pass disagreement"
            )

    return _finalize_snapshot(
        catalog,
        profiles=profiles,
        rows=rows,
        membership=membership,
        proposals=proposals,
        source_snapshot_ref=source_snapshot_ref,
        prompt_version=prompt_version,
        model_id=resolved_model,
        extra_findings=tuple(findings),
        raw_output_material=tuple(raw_output_material),
    )


__all__ = [
    "build_collection_profiles",
    "build_schema_mapping_snapshot",
    "build_schema_mapping_snapshot_async",
]
