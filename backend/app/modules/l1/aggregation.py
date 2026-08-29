"""L1 aggregate node - merge normalized per-dimension snapshots.

The L1 worker boundary is report body + structured observations. The L1
profile normalizes one dimension directly into a partial ``L1Snapshot``; this
node only merges, deduplicates, checks conflicts, persists provenance, and
runs the gate/review path.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.evidence.evidence_contracts import EvidenceSource
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
    from app.modules.evidence.requirements import requirements_from_l1

    snapshot.evidence_requirements = list(requirements_from_l1(snapshot))

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
    from app.infrastructure.reports.report_store import ReportStore

    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    require_frozen_context(state)

    store = ReportStore.get_instance()
    raw_reports = await store.get_layer_reports_with_sources(session_id, layer=1)

    from app.data.ingestion.compiler.core import compile_dimension_report

    partial_snapshots: list[L1Snapshot] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        content = rec.get("content", "")
        summary = rec.get("summary", "") or ""
        report_id = str(
            rec.get("report_id") or f"report:{session_id}:{dim_key}"
        ).strip()
        try:
            partial = compile_dimension_report(
            CompilationProfile.L1_OBSERVATION,
            dimension_key=dim_key,
            content=content,
            instruction=rec.get("instruction", "") or "",
            summary=summary,
            report_id=report_id,
            run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001 - one dimension must not break the aggregate
            logger.warning("[l1_aggregate] compile failed for dim=%s: %s", dim_key, exc)
            partial = None
        if isinstance(partial, L1Snapshot):
            partial_snapshots.append(partial)

    snapshot = merge_l1_snapshots(partial_snapshots, run_id=run_id)
    snapshot.context_version = context_version

    # Step reports are audit/display records, not semantic inputs. Dimension
    # scope is preserved by the typed partial snapshots above; current KG/GIS
    # evidence is promoted through the unified Evidence Runtime below.
    # Promote the canonical session-KG evidence into the L1Snapshot.  The
    # dimension compiler may legitimately produce no markdown facts when a
    # remote model returns prose without headings; that must not erase the
    # real GIS/KG facts that L1 observed and that L2 is required to consume.
    kg_fact_count = 0
    kg_facts: list[str] = []
    kg_source_refs: list[str] = []
    try:
        from app.modules.evidence.application import EvidenceApplication, EvidenceContext

        requirements = list(snapshot.evidence_requirements)
        if not requirements:
            from app.contracts.evidence.requirement_contracts import EvidenceRequirement

            requirements = [
                EvidenceRequirement(
                    requirement_id=f"{session_id}:l1:spatial-facts",
                    request_id=f"{session_id}:l1_snapshot",
                    requesting_artifact_ref=f"l1:{session_id}",
                    requesting_artifact_revision=str(
                        state.get("context_fingerprint") or ""
                    ),
                    producer_stage="L1",
                    statement="当前会话的空间实体、道路、设施和约束事实",
                    kind="spatial",
                    source_families=("kg", "bundle"),
                    scope=("parcels", "facilities", "roads", "annotations"),
                    spatial_granularity="feature",
                    allowed_inference="exact",
                    evidence_role="l1_snapshot_fact",
                    success_condition="返回带来源和空间定位的会话事实",
                )
            ]

        evidence = await EvidenceApplication().retrieve(
            requirements,
            EvidenceContext(
                session_id=session_id,
                village_name=state.get("config", {}).get("village_name", ""),
                run_id=f"{session_id}:l1_snapshot",
                stage="L1",
                dimension_key="l1_snapshot",
                purpose="snapshot_fact_production",
                request_type="spatial_lookup",
                context_refs=(str(state.get("context_fingerprint") or ""),),
            ),
        )
        kg_facts = [fact.statement for fact in evidence.evidence_bundle.facts]
        from app.modules.l1.facts import evidence_fact_to_l1_fact

        snapshot.fact_records = _dedup_fact_records([
            *snapshot.fact_records,
            *[
                record
                for fact in evidence.evidence_bundle.facts
                if (record := evidence_fact_to_l1_fact(
                    fact,
                    # Snapshot-wide KG/GIS facts have no single cognitive
                    # dimension; an empty key deliberately makes them
                    # available to any scoped L2/L3 consumer.
                    dimension_key="",
                    spatial_only=True,
                )) is not None
            ],
        ])
        kg_fact_count = len(kg_facts)
        kg_source_refs = [s.reference for s in evidence.evidence_bundle.sources]
        snapshot.facts = _dedup([*snapshot.facts, *kg_facts])
        snapshot.sources = _dedup_sources([
            *snapshot.sources,
            *evidence.evidence_bundle.sources,
        ])
    except Exception as exc:  # preserve L1 compiler output; gate remains fail-closed
        logger.warning("[l1_aggregate] session KG fact promotion failed: %s", exc)
    branch_id = str(state.get("branch_id") or "main")
    artifact_id = f"l1-{run_id}-{branch_id}-{semantic_checksum(snapshot)[:16]}"
    snapshot.artifact_id = artifact_id
    snapshot.context_fingerprint = str(state.get("context_fingerprint") or "")
    snapshot.evidence_requirements = list(requirements_from_l1(snapshot))
    snapshot.provenance = Provenance(
        source="l1_observe",
        run_id=run_id,
        module="l1_observe",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L1 OBSERVE aggregated normalized facts from dimension outputs.",
    )

    ref = ArtifactDescriptor.model_validate(
        store_artifact(
            state,
            "l1_snapshot",
            "l1_observe",
            "L1Snapshot",
            snapshot,
            base_dir=base_dir,
        )
    )
    logger.info("[l1_aggregate] L1Snapshot stored: %s", ref)

    gate_decision = evaluate_l1_gate(snapshot, run_id=run_id, context_version=context_version)

    from app.workflow.stage_adapter import persist_gate_decision

    gate_ref = persist_gate_decision(state, "l1", gate_decision)

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
