"""L1 aggregate node - merge normalized per-dimension snapshots.

The L1 worker boundary is report body + structured observations. The L1
profile normalizes one dimension directly into a partial ``L1Snapshot``; this
node only merges, deduplicates, checks conflicts, persists provenance, and
runs the gate/review path.
"""
from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import json
from typing import Any

from app.core.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.evidence.evidence_contracts import (
    EvidenceGapResolution,
    EvidenceSource,
)
from app.contracts.l1.l1_contracts import (
    EvidenceGap,
    L1Fact,
    L1Snapshot,
)
from app.contracts.target_projection.parsing_contracts import CompilationProfile
from app.contracts.artifacts.provenance import Provenance
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.reports.review_package import write_review_package
from app.infrastructure.logging import get_logger
from app.modules.evidence.requirements import requirements_from_l1

from .gate import evaluate_l1_gate
from .review import build_l1_review_package

logger = get_logger(__name__)


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dedup_sources(sources: list[EvidenceSource]) -> list[EvidenceSource]:
    seen: set[str] = set()
    result: list[EvidenceSource] = []
    for source in sources:
        if source.reference not in seen:
            seen.add(source.reference)
            result.append(source)
    return result


def _dedup_location_mentions(mentions: list[Any]) -> list[Any]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[Any] = []
    for fact in mentions:
        key = (
            str(getattr(fact, "normalized_name", "")),
            str(getattr(fact, "role", "")),
            str(getattr(fact, "dimension_key", "")),
            str(getattr(fact, "source_report_ref", "")),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(fact)
    return result


def _dedup_location_facts(facts: list[Any]) -> list[Any]:
    """Compatibility wrapper for the retired location-fact helper name."""

    return _dedup_location_mentions(facts)


def _dedup_fact_records(records: list[L1Fact]) -> list[L1Fact]:
    """Deduplicate typed facts by stable identity, not statement text."""
    seen: set[str] = set()
    result: list[L1Fact] = []
    for record in records:
        fact_id = str(getattr(record, "fact_id", "") or "")
        if not fact_id or fact_id in seen:
            continue
        seen.add(fact_id)
        result.append(record)
    return result


_FACT_IDENTITY_TOKENS = frozenset(
    {
        "category",
        "classification",
        "class",
        "code",
        "kind",
        "landuse",
        "metric",
        "subtype",
        "type",
    }
)
_FACT_IDENTITY_NAME_KEYS = frozenset(
    {"entity_name", "label", "name", "normalized_label", "normalized_name"}
)
_FACT_IDENTITY_RELATION_TOKENS = frozenset(
    {
        "applies",
        "destination",
        "direction",
        "endpoint",
        "from",
        "object",
        "origin",
        "predicate",
        "scope",
        "subject",
        "target",
        "to",
    }
)


def _fact_comparable_identity(fact: L1Fact) -> str:
    """Build a typed identity without treating prose or provenance as meaning.

    L1 models are allowed to introduce domain-specific attribute names.  The
    identity therefore comes from the semantic type plus attributes whose
    *shape* declares a classification (``*_type``, ``*_code``, ``metric``,
    etc.) or a stable entity name.  Descriptions, locations, source fields,
    and other narrative attributes stay out of the identity, so a second
    source can still corroborate the same fact.
    """

    semantic_type = str(fact.semantic_type or "").strip()
    discriminators: dict[str, str] = {}
    for raw_key, raw_value in (fact.attributes or {}).items():
        key = str(raw_key or "").strip().casefold()
        value = " ".join(str(raw_value or "").strip().split())
        if not key or not value:
            continue
        tokens = {
            token for token in key.replace("-", "_").split("_") if token
        }
        if (
            tokens & _FACT_IDENTITY_TOKENS
            or tokens & _FACT_IDENTITY_RELATION_TOKENS
            or key in _FACT_IDENTITY_NAME_KEYS
        ):
            discriminators[key] = value

    suffix = ":".join(
        f"{key}={discriminators[key]}"
        for key in sorted(discriminators)
    )
    return f"{semantic_type}:{suffix}" if suffix else semantic_type


def _typed_numeric_value(value: object) -> Decimal | None:
    """Return a number only when the producer supplied typed numeric data.

    Constraint/category prose is intentionally not coerced into a number.  A
    model may describe the same hazard as “易发生区” and “中易发生区”; that is
    a variant requiring traceability, not a quantitative contradiction that
    should send the whole L1 layer back to rework.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip().replace(",", "")
        if not text:
            return None
        try:
            return Decimal(text)
        except (InvalidOperation, ValueError):
            return None
    return None


def merge_l1_snapshots(
    snapshots: list[L1Snapshot],
    run_id: str,
) -> L1Snapshot:
    facts: list[str] = []
    fact_records: list[L1Fact] = []
    constraints: list[str] = []
    issues: list[StageIssue] = []
    opportunities: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    evidence_resolutions: list[EvidenceGapResolution] = []
    evidence_artifact_refs: list[ArtifactDescriptor] = []
    classification_refs: list[ClassificationRef] = []
    location_mentions: list[Any] = []
    dimension_provenance: list[Provenance] = []
    source_refs: list[str] = []
    facts_by_dimension: dict[str, list[str]] = {}
    spatial_facts_by_dimension: dict[str, list[str]] = {}
    diagnostics_by_dimension: dict[str, list[Any]] = {}
    traces_by_dimension: dict[str, Any] = {}

    for partial in snapshots:
        facts.extend(partial.facts)
        fact_records.extend(partial.fact_records)
        constraints.extend(partial.constraints)
        issues.extend(partial.issues)
        opportunities.extend(partial.opportunities)
        evidence_gaps.extend(partial.evidence_gaps)
        evidence_resolutions.extend(partial.evidence_resolutions)
        evidence_artifact_refs.extend(partial.evidence_artifact_refs)
        classification_refs.extend(partial.classification_refs)
        location_mentions.extend(partial.location_mentions)
        for dimension, values in partial.facts_by_dimension.items():
            facts_by_dimension.setdefault(dimension, []).extend(values)
        for dimension, values in partial.spatial_facts_by_dimension.items():
            spatial_facts_by_dimension.setdefault(dimension, []).extend(values)
        for dimension, values in partial.diagnostics_by_dimension.items():
            diagnostics_by_dimension.setdefault(dimension, []).extend(values)
        traces_by_dimension.update(partial.traces_by_dimension)
        dimension_provenance.extend(partial.dimension_provenance)
        if not partial.dimension_provenance and partial.provenance is not None:
            dimension_provenance.append(partial.provenance)
        source_refs.extend(source.reference for source in partial.sources)

    snapshot = L1Snapshot(
        context_version="",
        artifact_id="",
        fact_records=_dedup_fact_records(fact_records),
        facts=_dedup(facts),
        facts_by_dimension={
            dimension: _dedup(values)
            for dimension, values in facts_by_dimension.items()
        },
        location_mentions=_dedup_location_mentions(location_mentions),
        constraints=_dedup(constraints),
        issues=issues,
        opportunities=_dedup(opportunities),
        evidence_gaps=evidence_gaps,
        evidence_resolutions=evidence_resolutions,
        evidence_artifact_refs=sorted(
            {
                ref.descriptor_digest: ref
                for ref in evidence_artifact_refs
            }.values(),
            key=lambda ref: ref.descriptor_digest,
        ),
        sources=[
            EvidenceSource(source_type="report", reference=ref)
            for ref in _dedup(source_refs)
        ],
        classification_refs=classification_refs,
        dimension_provenance=dimension_provenance,
        spatial_facts_by_dimension={
            dimension: _dedup(values)
            for dimension, values in spatial_facts_by_dimension.items()
        },
        diagnostics_by_dimension=diagnostics_by_dimension,
        traces_by_dimension=traces_by_dimension,
    )
    comparable: dict[tuple[str, str, str, str, str], list[L1Fact]] = {}
    for fact in snapshot.fact_records:
        if fact.value is None or not fact.semantic_type:
            continue
        comparable_identity = _fact_comparable_identity(fact)
        key = (
            fact.dimension_key,
            fact.subject_scope,
            comparable_identity,
            fact.unit,
            fact.counting_basis,
        )
        comparable.setdefault(key, []).append(fact)
    for key, variants in comparable.items():
        typed_values = {
            _typed_numeric_value(fact.value)
            for fact in variants
        }
        typed_values.discard(None)
        if len(typed_values) > 1:
            dimension, scope, semantic_type, unit, basis = key
            snapshot.issues.append(
                StageIssue(
                    stage="l1",
                    severity="error",
                    code="fact_contradiction",
                    message=(
                        f"维度事实冲突: {dimension}/{scope}/{semantic_type}"
                    ),
                    detail="; ".join(
                        f"{fact.fact_id}={fact.value}{unit}"
                        f" (counting_basis={basis})"
                        for fact in variants
                    ),
                )
            )

    return snapshot


async def l1_aggregate(
    state: dict[str, Any],
    *,
    base_dir: str = ".run-tmp",
) -> dict[str, Any]:
    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    require_frozen_context(state)

    retry_counts = dict(state.get("retry_counts") or {})
    recovery_generation = max(
        0,
        int(state.get("l1_evidence_recovery_generation") or 0),
        int(retry_counts.get("l1_explore") or 0),
    )
    previous_snapshot: L1Snapshot | None = None
    if recovery_generation > 0 and dict(
        state.get("artifact_refs") or {}
    ).get("l1_snapshot"):
        try:
            from app.infrastructure.artifacts.runtime import load_artifact

            candidate = load_artifact(
                state,
                "l1_snapshot",
                L1Snapshot,
                base_dir=base_dir,
            )
            if (
                candidate is not None
                and candidate.context_version == context_version
                and candidate.context_fingerprint
                == str(state.get("context_fingerprint") or "")
            ):
                previous_snapshot = candidate
        except Exception as exc:
            logger.warning(
                "[l1_aggregate] previous L1 Evidence history is not reloadable: %s",
                exc,
            )

    from app.data.ingestion.compiler.core import compile_dimension_report
    from app.infrastructure.artifacts.dimension_runtime import (
        load_layer_dimension_products,
    )
    from app.modules.l1.observation_draft import L1DimensionOutput

    partial_snapshots: list[L1Snapshot] = []
    dimension_products, dimension_errors = load_layer_dimension_products(
        state,
        layer=1,
        model_type=L1DimensionOutput,
    )
    raw_reports = dimension_products
    for dim_key, output in dimension_products.items():
        artifact_key = f"l1_dimension__{dim_key}"
        raw_ref = dict(state.get("artifact_refs") or {}).get(artifact_key)
        report_id = (
            ArtifactDescriptor.model_validate(raw_ref).digest
            if raw_ref
            else artifact_key
        )
        try:
            partial = compile_dimension_report(
                CompilationProfile.L1_OBSERVATION,
                dimension_key=dim_key,
                content=output.display.report_body,
                instruction=json.dumps(
                    output.semantic.model_dump(mode="json"),
                    ensure_ascii=False,
                ),
                summary="",
                report_id=report_id,
                run_id=run_id,
            )
        except Exception as exc:
            dimension_errors[dim_key] = f"{type(exc).__name__}: {exc}"
            continue
        if isinstance(partial, L1Snapshot):
            partial_snapshots.append(partial)

    snapshot = merge_l1_snapshots(partial_snapshots, run_id=run_id)
    for dim_key, detail in sorted(dimension_errors.items()):
        snapshot.issues.append(StageIssue(
            stage="l1",
            severity="error",
            code="dimension_product_incomplete",
            message=f"L1 dimension product is not consumable: {dim_key}",
            detail=detail,
        ))
        snapshot.evidence_gaps.append(EvidenceGap(
            gap_id=f"l1:dimension:{dim_key}:product",
            dimension=dim_key,
            description="typed L1 dimension product is missing, pending, or invalid",
            required_fact="rerun the exact L1 dimension product or request HUMAN review",
            severity="error",
        ))
    snapshot.context_version = context_version
    snapshot.context_fingerprint = str(state.get("context_fingerprint") or "")
    from app.modules.evidence.requirements import l1_location_work_item_key

    snapshot.location_mentions = [
        location.model_copy(update={
            "work_item_ref": l1_location_work_item_key(location),
        })
        for location in snapshot.location_mentions
    ]
    branch_id = str(state.get("branch_id") or "main")
    # Freeze the observation identity before replaying Evidence history.  A
    # recovery wave must reuse the same requirement IDs and only version the
    # failed retrieval, not make every already-sufficient request look new.
    snapshot.artifact_id = (
        f"l1-{run_id}-{branch_id}-{semantic_checksum(snapshot)[:16]}"
    )
    if previous_snapshot is not None:
        previous_by_work_item: dict[str, list[Any]] = {}
        for location in previous_snapshot.location_mentions:
            previous_by_work_item.setdefault(
                l1_location_work_item_key(location),
                [],
            ).append(location)
        current_work_items = {
            l1_location_work_item_key(location)
            for location in snapshot.location_mentions
        }
        for index, location in enumerate(snapshot.location_mentions):
            prior_locations = previous_by_work_item.get(
                l1_location_work_item_key(location),
                (),
            )
            prior_artifacts = {
                ref.descriptor_digest: ref
                for prior in prior_locations
                for ref in prior.evidence_artifact_refs
            }
            prior_refs = [
                ref
                for prior in prior_locations
                for ref in prior.evidence_refs
            ]
            snapshot.location_mentions[index] = location.model_copy(update={
                "evidence_refs": _dedup([
                    *location.evidence_refs,
                    *prior_refs,
                ]),
                "evidence_artifact_refs": sorted(
                    {
                        **{
                            ref.descriptor_digest: ref
                            for ref in location.evidence_artifact_refs
                        },
                        **prior_artifacts,
                    }.values(),
                    key=lambda ref: ref.descriptor_digest,
                ),
            })

        current_gaps = {
            gap.gap_id: index
            for index, gap in enumerate(snapshot.evidence_gaps)
        }
        for prior_gap in previous_snapshot.evidence_gaps:
            if prior_gap.outcome_status == "open":
                continue
            if prior_gap.gap_id in current_gaps:
                snapshot.evidence_gaps[current_gaps[prior_gap.gap_id]] = prior_gap
                continue
            if (
                prior_gap.subject_ref in current_work_items
                and prior_gap.requirement_id
            ):
                current_gaps[prior_gap.gap_id] = len(snapshot.evidence_gaps)
                snapshot.evidence_gaps.append(prior_gap)

        resolution_by_gap = {
            item.gap_id: item
            for item in [
                *snapshot.evidence_resolutions,
                *previous_snapshot.evidence_resolutions,
            ]
        }
        snapshot.evidence_resolutions = [
            resolution_by_gap[key]
            for key in sorted(resolution_by_gap)
        ]
        previous_refs = {
            ref.descriptor_digest: ref
            for ref in previous_snapshot.evidence_artifact_refs
        }
        used_descriptors = {
            ref.descriptor_digest
            for location in snapshot.location_mentions
            for ref in location.evidence_artifact_refs
        }
        used_descriptors.update(
            gap.evidence_artifact_ref.descriptor_digest
            for gap in snapshot.evidence_gaps
            if gap.evidence_artifact_ref is not None
        )
        used_descriptors.update(
            item.evidence_ref
            for item in snapshot.evidence_resolutions
            if item.evidence_ref
        )
        snapshot.evidence_artifact_refs = sorted(
            [
                previous_refs[digest]
                for digest in used_descriptors
                if digest in previous_refs
            ],
            key=lambda ref: ref.descriptor_digest,
        )
    generated_requirements = list(requirements_from_l1(snapshot))
    prior_gap_by_subject = {
        gap.subject_ref: gap
        for gap in snapshot.evidence_gaps
        if gap.subject_ref and gap.outcome_status != "open"
    }
    prior_gap_by_id = {
        gap.gap_id: gap
        for gap in snapshot.evidence_gaps
        if gap.outcome_status != "open"
    }
    snapshot.evidence_requirements = []
    for requirement in generated_requirements:
        metadata = dict(requirement.metadata or {})
        prior_gap = None
        work_item_key = str(
            metadata.get("location_work_item_key") or ""
        )
        gap_id = str(metadata.get("gap_id") or "")
        if work_item_key:
            prior_gap = prior_gap_by_subject.get(work_item_key)
        elif gap_id:
            prior_gap = prior_gap_by_id.get(gap_id)
        requirement_generation = int(
            metadata.get("recovery_generation") or 0
        )
        if (
            prior_gap is not None
            and prior_gap.recoverable
            and recovery_generation > prior_gap.recovery_generation
        ):
            requirement_generation = max(
                recovery_generation,
                prior_gap.recovery_generation + 1,
            )
        metadata["recovery_generation"] = requirement_generation
        snapshot.evidence_requirements.append(requirement.model_copy(update={
            "request_id": (
                f"{requirement.request_id or snapshot.artifact_id}:"
                f"recovery:{requirement_generation}"
            ),
            "metadata": metadata,
        }))

    # Step reports are audit/display records, not semantic inputs. Dimension
    # scope is preserved by the typed partial snapshots above; current KG/GIS
    # evidence is promoted through the unified Evidence Runtime below.
    # Promote the canonical session-KG evidence into the L1Snapshot.  The
    # dimension compiler may legitimately produce no markdown facts when a
    # remote model returns prose without headings; that must not erase the
    # real GIS/KG facts that L1 observed and that L2 is required to consume.
    cached_context = None
    kg_fact_count = 0
    kg_facts: list[str] = []
    kg_source_refs: list[str] = []
    evidence_retrieval_count = 0
    evidence_candidate_total = 0
    evidence_outcome_counts: dict[str, int] = {}
    try:
        from app.modules.evidence.application import EvidenceApplication, EvidenceContext

        requirements = list(snapshot.evidence_requirements)
        try:
            from app.infrastructure.context_runtime.manager import get_cached_context

            cached_context = get_cached_context(session_id)
        except Exception:
            cached_context = None
        evidence_context = EvidenceContext.from_state(
            state,
            stage="L1",
            purpose="snapshot_fact_production",
            request_type="spatial_lookup",
        ).model_copy(update={
            "run_id": f"{session_id}:l1_snapshot",
            "dimension_key": "l1_snapshot",
            "context_refs": (
                str(state.get("context_fingerprint") or ""),
            ),
            "world_model_mode": str(
                state.get("world_model_mode")
                or getattr(cached_context, "world_model_mode", "off")
                or "off"
            ),
            "data_catalog": (
                state.get("data_catalog")
                or getattr(cached_context, "data_resource_catalog", None)
            ),
        })
        semaphore = asyncio.Semaphore(4)

        async def retrieve_one(requirement: Any) -> Any:
            async with semaphore:
                return await EvidenceApplication().retrieve(
                    (requirement,),
                    evidence_context,
                    candidate_limit=8,
                )

        retrievals = await asyncio.gather(
            *(retrieve_one(requirement) for requirement in requirements),
            return_exceptions=True,
        )
        from app.modules.l1.facts import evidence_fact_to_l1_fact

        local_source_kinds = {
            "kg",
            "kg_canonical",
            "canonical_kg",
            "gis",
            "gis_layer",
            "data_resource_catalog",
        }

        def mark_existing_gap_attempt(
            gap_id: str,
            *,
            status: str,
            reason: str,
            updates: dict[str, Any] | None = None,
        ) -> bool:
            for index, gap in enumerate(snapshot.evidence_gaps):
                if gap.gap_id != gap_id:
                    continue
                detail = reason or gap.required_fact or gap.description
                snapshot.evidence_gaps[index] = gap.model_copy(update={
                    "description": (
                        f"{gap.description}; Evidence outcome={status}"
                    ),
                    "required_fact": detail,
                    **dict(updates or {}),
                })
                return True
            return False

        for requirement, retrieval in zip(requirements, retrievals):
            is_location_identity = (
                requirement.evidence_role == "l1_location_identity"
            )
            if isinstance(retrieval, Exception):
                metadata = dict(requirement.metadata or {})
                failed_reason = (
                    f"{requirement.statement}; "
                    f"error={type(retrieval).__name__}"
                )
                source_gap_id = str(
                    metadata.get("gap_id") or ""
                )
                subject_ref = str(
                    metadata.get("location_work_item_key")
                    or source_gap_id
                    or requirement.requirement_id
                )
                failure_fields = {
                    "subject_ref": subject_ref,
                    "requirement_id": requirement.requirement_id,
                    "outcome_status": "failed",
                    "reason_codes": ["retrieval_exception_before_commit"],
                    "allowed_sources": list(requirement.source_families),
                    "retrieval_capability": str(
                        requirement.retrieval_capability
                        or metadata.get("retrieval_capability")
                        or "identity_evidence"
                    ),
                    "recovery_action": (
                        "retry the same bounded requirement with a new "
                        "recovery_generation"
                    ),
                    "recoverable": True,
                    "recovery_generation": int(
                        metadata.get("recovery_generation") or 0
                    ),
                }
                updated_existing = bool(source_gap_id) and mark_existing_gap_attempt(
                    source_gap_id,
                    status="failed",
                    reason=failed_reason,
                    updates=failure_fields,
                )
                if not updated_existing:
                    snapshot.evidence_gaps.append(EvidenceGap(
                        gap_id=f"{requirement.requirement_id}:failed",
                        dimension=(
                            "location" if is_location_identity else "shared"
                        ),
                        description=(
                            "L1 evidence retrieval failed before CAS commit"
                        ),
                        required_fact=failed_reason,
                        severity="error",
                        **failure_fields,
                    ))
                evidence_outcome_counts["failed"] = (
                    evidence_outcome_counts.get("failed", 0) + 1
                )
                continue

            bundle = retrieval.evidence_bundle
            packet = getattr(retrieval, "evidence_packet", None)
            coverage = getattr(retrieval, "coverage", None)
            outcome = getattr(retrieval, "outcome", None)
            receipt = getattr(retrieval, "receipt", None)
            status = str(getattr(outcome, "status", "") or "failed")
            reason = str(getattr(outcome, "reason", "") or "")
            if receipt is None:
                status = "failed"
                reason = "retrieval result has no persisted Evidence receipt"
            if packet is None or coverage is None or outcome is None:
                status = "failed"
                reason = "retrieval result is missing packet, coverage, or outcome"
            if is_location_identity:
                exact_candidate = bool(
                    packet is not None
                    and packet.sufficiency == "sufficient"
                    and packet.ambiguity_status == "resolved"
                    and packet.candidate_identity_total == 1
                    and len(packet.candidate_entity_refs) == 1
                    and packet.identity_grouping == "world_entity"
                    and len(packet.candidate_refs) >= 1
                )
                if status == "sufficient" and not exact_candidate:
                    status = (
                        "partial"
                        if packet is not None and packet.candidate_total
                        else "insufficient"
                    )
                    reason = (
                        "location identity evidence did not resolve to exactly "
                        "one local DATA/KG candidate"
                    )

            if receipt is not None:
                snapshot.evidence_artifact_refs = sorted(
                    {
                        ref.descriptor_digest: ref
                        for ref in [
                            *snapshot.evidence_artifact_refs,
                            receipt.retrieval_ref,
                        ]
                    }.values(),
                    key=lambda ref: ref.descriptor_digest,
                )

            evidence_retrieval_count += 1
            evidence_candidate_total += int(
                getattr(packet, "candidate_total", 0) or 0
            )
            kg_source_refs.extend(
                source.reference for source in bundle.sources
            )
            snapshot.sources = _dedup_sources([
                *snapshot.sources,
                *bundle.sources,
            ])

            attached_count = 0
            if is_location_identity and receipt is not None:
                from app.modules.evidence.requirements import (
                    l1_location_work_item_key,
                )

                metadata = dict(requirement.metadata or {})
                work_item_key = str(
                    metadata.get("location_work_item_key") or ""
                ).strip()
                raw_indexes = metadata.get("location_mention_indexes") or []
                candidate_indexes = sorted({
                    int(index)
                    for index in raw_indexes
                    if isinstance(index, int)
                    and 0 <= index < len(snapshot.location_mentions)
                    and l1_location_work_item_key(
                        snapshot.location_mentions[index]
                    ) == work_item_key
                })

                for index in candidate_indexes:
                    location = snapshot.location_mentions[index]
                    refs = list(location.evidence_refs)
                    refs.extend([
                        f"evidence-retrieval:{receipt.retrieval_ref.descriptor_digest}",
                        f"evidence-fingerprint:{receipt.fingerprint}",
                    ])
                    refs.extend(
                        str(source.reference)
                        for source in bundle.sources
                        if str(source.reference)
                    )
                    for fact in bundle.facts:
                        refs.extend(
                            str(ref) for ref in fact.source_refs if str(ref)
                        )
                        if str(getattr(fact, "source_locator", "") or ""):
                            refs.append(str(fact.source_locator))
                    if packet is not None:
                        refs.extend(
                            str(ref) for ref in packet.external_refs if str(ref)
                        )
                    artifact_refs = list(location.evidence_artifact_refs)
                    if not any(
                        ref.descriptor_digest
                        == receipt.retrieval_ref.descriptor_digest
                        for ref in artifact_refs
                    ):
                        artifact_refs.append(receipt.retrieval_ref)
                    artifact_refs = sorted(
                        artifact_refs,
                        key=lambda ref: ref.descriptor_digest,
                    )
                    snapshot.location_mentions[index] = location.model_copy(
                        update={
                            "evidence_refs": list(dict.fromkeys(refs)),
                            "evidence_artifact_refs": artifact_refs,
                        }
                    )
                    attached_count += 1
                if attached_count == 0:
                    status = "failed"
                    reason = (
                        "Evidence receipt could not be attached to its exact "
                        "LocationMention"
                    )

            evidence_outcome_counts[status] = (
                evidence_outcome_counts.get(status, 0) + 1
            )
            source_gap_id = str(
                (requirement.metadata or {}).get("gap_id") or ""
            )
            if status == "sufficient" and source_gap_id and receipt is not None:
                snapshot.evidence_gaps = [
                    gap
                    for gap in snapshot.evidence_gaps
                    if gap.gap_id != source_gap_id
                ]
                snapshot.evidence_resolutions = sorted(
                    [
                        *[
                            item
                            for item in snapshot.evidence_resolutions
                            if item.gap_id != source_gap_id
                        ],
                        EvidenceGapResolution(
                            gap_id=source_gap_id,
                            resolution="sufficient",
                            resolved_by=(
                                f"evidence-retrieval:{receipt.fingerprint}"
                            ),
                            evidence_ref=(
                                receipt.retrieval_ref.descriptor_digest
                            ),
                        ),
                    ],
                    key=lambda item: item.gap_id,
                )
            if status == "sufficient" and is_location_identity and receipt is not None:
                work_item_key = str(
                    (requirement.metadata or {}).get(
                        "location_work_item_key"
                    )
                    or ""
                )
                resolved_location_gaps = [
                    gap
                    for gap in snapshot.evidence_gaps
                    if gap.subject_ref == work_item_key
                    and gap.outcome_status != "open"
                ]
                if resolved_location_gaps:
                    resolved_ids = {
                        gap.gap_id for gap in resolved_location_gaps
                    }
                    snapshot.evidence_gaps = [
                        gap
                        for gap in snapshot.evidence_gaps
                        if gap.gap_id not in resolved_ids
                    ]
                    resolution_by_gap = {
                        item.gap_id: item
                        for item in snapshot.evidence_resolutions
                    }
                    for gap_id in resolved_ids:
                        resolution_by_gap[gap_id] = EvidenceGapResolution(
                            gap_id=gap_id,
                            resolution="sufficient_after_recovery",
                            resolved_by=(
                                f"evidence-retrieval:{receipt.fingerprint}"
                            ),
                            evidence_ref=(
                                receipt.retrieval_ref.descriptor_digest
                            ),
                        )
                    snapshot.evidence_resolutions = [
                        resolution_by_gap[key]
                        for key in sorted(resolution_by_gap)
                    ]
            if status != "sufficient":
                metadata = dict(requirement.metadata or {})
                missing = list(
                    getattr(packet, "missing_evidence", None) or ()
                )
                required_fact = "; ".join([
                    reason or requirement.statement,
                    *missing,
                ])
                coverage_stop_reason = str(
                    getattr(coverage, "stop_reason", "") or ""
                )
                reason_codes = [
                    str(value)
                    for value in (
                        getattr(outcome, "reason_codes", None) or ()
                    )
                    if str(value)
                ]
                recoverable = bool(
                    status == "failed"
                    or coverage_stop_reason == "budget_exhausted"
                )
                subject_ref = str(
                    metadata.get("location_work_item_key")
                    or source_gap_id
                    or requirement.requirement_id
                )
                recovery_action = (
                    "retry the bounded Evidence request with a new generation"
                    if recoverable
                    else (
                        "request HUMAN confirmation of the bounded identity set"
                        if status == "human_required"
                        or coverage_stop_reason == "human_required"
                        else "create an explicit source/collection recovery plan"
                    )
                )
                gap_fields = {
                    "subject_ref": subject_ref,
                    "requirement_id": requirement.requirement_id,
                    "outcome_status": status,
                    "reason_codes": reason_codes,
                    "candidate_total": int(
                        getattr(packet, "candidate_total", 0) or 0
                    ),
                    "candidate_identity_total": int(
                        getattr(packet, "candidate_identity_total", 0) or 0
                    ),
                    "ambiguity_status": str(
                        getattr(packet, "ambiguity_status", "unresolved")
                        or "unresolved"
                    ),
                    "coverage_stop_reason": coverage_stop_reason,
                    "evidence_artifact_ref": (
                        receipt.retrieval_ref if receipt is not None else None
                    ),
                    "allowed_sources": list(requirement.source_families),
                    "retrieval_capability": str(
                        requirement.retrieval_capability
                        or metadata.get("retrieval_capability")
                        or (
                            "identity_evidence"
                            if is_location_identity
                            else "source_evidence"
                        )
                    ),
                    "recovery_action": recovery_action,
                    "recoverable": recoverable,
                    "recovery_generation": int(
                        metadata.get("recovery_generation") or 0
                    ),
                }
                updated_existing = bool(source_gap_id) and mark_existing_gap_attempt(
                    source_gap_id,
                    status=status,
                    reason=required_fact,
                    updates=gap_fields,
                )
                if not updated_existing:
                    snapshot.evidence_gaps.append(EvidenceGap(
                        gap_id=f"{requirement.requirement_id}:{status}",
                        dimension=(
                            "location" if is_location_identity else "shared"
                        ),
                        description=(
                            f"L1 evidence retrieval outcome: {status}; "
                            "candidate_total="
                            f"{getattr(packet, 'candidate_total', 0) or 0}"
                        ),
                        required_fact=required_fact,
                        severity="error",
                        **gap_fields,
                    ))

            # A local feature returned for a location identity request is
            # still only a candidate.  It stays inside the Evidence retrieval
            # artifact until GROUND binds an entity/representation.  Only a
            # sufficient non-identity requirement may promote local DATA/KG
            # facts into the authoritative L1 fact table.
            if status == "sufficient" and not is_location_identity:
                local_facts = [
                    fact for fact in bundle.facts
                    if str(
                        getattr(fact, "source_kind", "")
                        or (getattr(fact, "fields", None) or {}).get(
                            "source_kind", ""
                        )
                    ).casefold() in local_source_kinds
                ]
                snapshot.fact_records = _dedup_fact_records([
                    *snapshot.fact_records,
                    *[
                        record
                        for fact in local_facts
                        if (record := evidence_fact_to_l1_fact(
                            fact,
                            dimension_key="",
                            spatial_only=True,
                        )) is not None
                    ],
                ])
                kg_facts.extend(fact.statement for fact in local_facts)
                snapshot.facts = _dedup([
                    *snapshot.facts,
                    *(fact.statement for fact in local_facts),
                ])
        kg_facts = _dedup(kg_facts)
        kg_source_refs = _dedup(kg_source_refs)
        kg_fact_count = len(kg_facts)
    except Exception as exc:  # preserve compiler output, but never swallow the gap
        logger.warning("[l1_aggregate] session KG fact promotion failed: %s", exc)
        snapshot.evidence_gaps.append(EvidenceGap(
            gap_id=f"{session_id}:l1:world-model-evidence",
            dimension="shared",
            description=f"World Model evidence promotion failed: {type(exc).__name__}",
            required_fact="reload DATA/KG/EVIDENCE inputs and retry L1",
            severity="error",
        ))

    data_catalog = (
        state.get("data_catalog")
        or getattr(cached_context, "data_resource_catalog", None)
        if cached_context is not None
        else state.get("data_catalog")
    )
    catalog_snapshot = getattr(data_catalog, "snapshot", data_catalog)
    catalog_features = tuple(
        getattr(catalog_snapshot, "features", ()) or ()
    )
    bare_ref_counts: dict[str, int] = {}
    qualified_to_bare: dict[str, str] = {}
    for feature in catalog_features:
        bare_ref = str(getattr(feature, "source_feature_ref", "") or "")
        dataset_ref = str(getattr(feature, "dataset_ref", "") or "")
        if not bare_ref or not dataset_ref:
            continue
        bare_ref_counts[bare_ref] = bare_ref_counts.get(bare_ref, 0) + 1
        qualified_to_bare[f"resource:{dataset_ref}:{bare_ref}"] = bare_ref

    def lineage_aliases(values: Any) -> set[str]:
        aliases: set[str] = set()
        for raw_value in values or ():
            value = str(raw_value or "").strip()
            if not value:
                continue
            bare_ref = qualified_to_bare.get(value)
            if bare_ref is not None:
                aliases.add(value)
                if bare_ref_counts.get(bare_ref) == 1:
                    aliases.add(bare_ref)
            elif bare_ref_counts.get(value) == 1:
                aliases.add(value)
        return aliases

    for gap_index, raw_gap in enumerate(state.get("evidence_gap_rows") or ()):
        if not isinstance(raw_gap, dict):
            snapshot.issues.append(StageIssue(
                stage="l1",
                severity="error",
                code="invalid_evidence_gap_row",
                message="Upstream evidence gap row is not a typed object",
                detail=f"row_index={gap_index}; type={type(raw_gap).__name__}",
            ))
            snapshot.evidence_gaps.append(EvidenceGap(
                gap_id=f"l1:upstream-gap-row:{gap_index}",
                dimension="shared",
                description="Malformed upstream evidence gap row requires review",
                required_fact="restore a typed evidence gap row with a durable gap_ref",
                severity="error",
            ))
            continue
        gap = dict(raw_gap)
        gap_ref = str(gap.get("gap_ref") or "").strip()
        if not gap_ref:
            snapshot.issues.append(StageIssue(
                stage="l1",
                severity="error",
                code="evidence_gap_ref_missing",
                message="Upstream evidence gap row has no durable gap_ref",
                detail=f"row_index={gap_index}",
            ))
            snapshot.evidence_gaps.append(EvidenceGap(
                gap_id=f"l1:upstream-gap-ref:{gap_index}",
                dimension="shared",
                description="Upstream evidence gap identity is missing",
                required_fact="supply a durable gap_ref and retry evidence resolution",
                severity="error",
            ))
            continue
        if str(gap.get("status") or "") == "resolved":
            continue
        subject_feature_refs = lineage_aliases(gap.get("subject_refs") or ())
        resolving_facts = [
            fact for fact in snapshot.fact_records
            if subject_feature_refs.intersection(
                lineage_aliases(fact.source_feature_ids)
            )
            and fact.inference_level not in {"pending", "conflicted"}
            and fact.semantic_type not in {"", "source_feature_identity"}
        ]
        if resolving_facts:
            continue
        status = str(gap.get("status") or "open")
        snapshot.evidence_gaps.append(EvidenceGap(
            gap_id=gap_ref,
            dimension="shared",
            description=str(
                gap.get("failure_reason")
                or "Upstream cognition/evidence gap remains unresolved at L1"
            ),
            required_fact=", ".join(
                str(item) for item in gap.get("missing_fields") or ()
            ),
            severity=(
                "error"
                if status in {"not_available", "requires_human_confirmation"}
                else "warning"
            ),
        ))
    snapshot.provenance = Provenance(
        source="l1_observe",
        run_id=run_id,
        module="l1_observe",
        trace=[f"aggregate:{snapshot.artifact_id}"],
        natural_language_description="L1 OBSERVE aggregated normalized facts from dimension outputs.",
    )

    persisted_state = dict(state)
    persisted_refs = dict(state.get("artifact_refs") or {})
    dynamic_parent_keys: list[str] = []
    for evidence_ref in snapshot.evidence_artifact_refs:
        fingerprint = str(
            evidence_ref.provenance.get("fingerprint") or ""
        ).strip()
        if len(fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in fingerprint
        ):
            raise RuntimeError(
                "L1 Evidence artifact ref has no canonical retrieval fingerprint"
            )
        dynamic_key = f"evidence_retrieval__{fingerprint}"
        persisted_refs[dynamic_key] = evidence_ref.model_dump(mode="json")
        dynamic_parent_keys.append(dynamic_key)
    persisted_state["artifact_refs"] = persisted_refs
    upstream_parent_keys = [
        "data_catalog",
        "data_snapshot",
        "data_stage",
        "data_gate",
        "schema_mapping_snapshot",
        "world_model_snapshot",
        "kg_stage",
        "kg_gate",
        "evidence_snapshot",
        "evidence_external_observations",
        "evidence_gap_ledger",
        "evidence_gate",
    ]
    dimension_parent_keys = [
        f"l1_dimension__{dimension_key}"
        for dimension_key in sorted(dimension_products)
    ]
    ref = ArtifactDescriptor.model_validate(
        store_artifact(
            persisted_state,
            "l1_snapshot",
            "l1_observe",
            "L1Snapshot",
            snapshot,
            base_dir=base_dir,
            parent_keys=[
                *upstream_parent_keys,
                *dimension_parent_keys,
                *sorted(dynamic_parent_keys),
            ],
        )
    )
    logger.info("[l1_aggregate] L1Snapshot stored: %s", ref)

    gate_decision = evaluate_l1_gate(snapshot, run_id=run_id, context_version=context_version)

    from app.workflow.stage_adapter import persist_gate_decision

    gate_ref = persist_gate_decision(
        state,
        "l1",
        gate_decision,
        output_refs={"l1_snapshot": ref},
    )

    pkg = build_l1_review_package(
        snapshot=snapshot,
        artifact_ref=ref,
        gate_decision=gate_decision,
        run_id=run_id,
    )
    review_id = write_review_package(pkg, base_dir=base_dir)
    logger.info("[l1_aggregate] review package written: review_id=%s", review_id)

    try:
        from app.infrastructure.reports.step_report import save_step_report
        from app.workflow.stage_audit import build_input_audit

        await save_step_report(
            session_id,
            "L1",
            step_name="l1_aggregate",
            layer=1,
            inputs=build_input_audit(
                state,
                stage="L1",
                source_refs=[f"L1:{key}" for key in sorted(raw_reports)],
            ),
            outputs={
                "fact_count": len(snapshot.facts),
                "fact_record_count": len(snapshot.fact_records),
                "facts_produced": snapshot.facts,
                "facts_by_dimension": snapshot.facts_by_dimension,
                "location_mentions": [fact.model_dump(mode="json") for fact in snapshot.location_mentions],
                "kg_evidence_produced": {
                    "fact_count": kg_fact_count,
                    "fact_statements": kg_facts,
                    "source_refs": kg_source_refs,
                },
                "constraint_count": len(snapshot.constraints),
                "source_refs": [s.reference for s in snapshot.sources],
                "gate_route": gate_decision.feedback_route or ("PASS" if gate_decision.passed else "FAIL"),
            },
            artifacts=[{"key": "l1_snapshot", **ref.model_dump(mode="json")}],
            diagnostics={
                "fact_producer": "L1 report compiler + session KG evidence promotion",
                "kg_fact_count": kg_fact_count,
            },
        )
    except Exception as exc:
        logger.debug("[l1_aggregate] step report failed: %s", exc)

    return {
        "artifact_refs": {
            "l1_snapshot": ref.model_dump(mode="json"),
            "l1_gate": gate_ref.model_dump(mode="json"),
        },
        "l1_review_id": review_id,
    }


__all__ = ["l1_aggregate", "merge_l1_snapshots"]
