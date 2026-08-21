"""L1 aggregate node - merge normalized per-dimension snapshots.

The L1 worker boundary is report body + structured observations. The L1
profile normalizes one dimension directly into a partial ``L1Snapshot``; this
node only merges, deduplicates, checks conflicts, persists provenance, and
runs the gate/review path.
"""
from __future__ import annotations

from typing import Any

from app.domain.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor
from app.contracts.artifacts.classification_ref import ClassificationRef
from app.contracts.artifacts.contract_meta import StageIssue
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.domain.l1_contracts import (
    EvidenceGap,
    L1Fact,
    L1Snapshot,
)
from app.contracts.workflow.parsing_contracts import CompilationProfile
from app.contracts.artifacts.provenance import Provenance
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.reports.review_package import write_review_package
from app.infrastructure.logging import get_logger

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


def _dedup_location_facts(facts: list[Any]) -> list[Any]:
    seen: set[tuple[str, str, str, str]] = set()
    result: list[Any] = []
    for fact in facts:
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
    location_facts: list[Any] = []
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
        location_facts.extend(partial.location_facts)
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
        location_facts=_dedup_location_facts(location_facts),
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

    fact_keys: dict[str, list[str]] = {}
    for f in snapshot.facts:
        # Free-form model observations are independent facts, not variants of
        # one field.  Only structured ``key: value`` facts participate in the
        # contradiction check; otherwise 12 valid observations would trigger
        # an L1 rework loop merely because they share the fallback label.
        if "模型观察:" in f or "事实:" in f:
            continue
        key = f.split(":")[0] if ":" in f else f
        fact_keys.setdefault(key, []).append(f)
    for key, variants in fact_keys.items():
        unique = set(variants)
        if len(unique) > 1:
            snapshot.issues.append(
                StageIssue(
                    stage="l1",
                    severity="error",
                    code="fact_contradiction",
                    message=f"维度事实冲突: {key}",
                    detail="; ".join(sorted(unique)),
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
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
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
    # Preserve the dimension that actually consumed each KG fact.  The
    # flattened ``facts`` list remains backwards compatible, while L2 reads
    # this scoped map to avoid feeding unrelated evidence into a dimension.
    try:
        from app.infrastructure.reports.step_report import get_session_step_reports

        for step in await get_session_step_reports(session_id):
            if step.get("stage") != "L1" or not step.get("dimension_key"):
                continue
            consumed = (step.get("outputs") or {}).get("kg_evidence_consumed") or {}
            statements = consumed.get("fact_statements") or []
            if not statements:
                continue
            dim = step["dimension_key"]
            scoped = [f"[{dim}] KG事实: {statement}" for statement in statements]
            snapshot.facts_by_dimension[dim] = _dedup(
                [*(snapshot.facts_by_dimension.get(dim) or []), *scoped]
            )
            snapshot.facts = _dedup([*snapshot.facts, *scoped])
    except Exception as exc:
        logger.warning("[l1_aggregate] dimension-scoped KG fact merge failed: %s", exc)
    # Promote the canonical session-KG evidence into the L1Snapshot.  The
    # dimension compiler may legitimately produce no markdown facts when a
    # remote model returns prose without headings; that must not erase the
    # real GIS/KG facts that L1 observed and that L2 is required to consume.
    kg_fact_count = 0
    kg_facts: list[str] = []
    kg_source_refs: list[str] = []
    try:
        from app.evidence.retrieval.evidence_service import retrieve_evidence
        from app.contracts.evidence.evidence_contracts import ExplorationRequest

        evidence = await retrieve_evidence(
            ExplorationRequest(
                run_id=f"{session_id}:l1_snapshot",
                request_type="spatial_lookup",
                query="L1 canonical session KG facts",
                stage="L1",
                dimension_key="l1_snapshot",
                query_purpose="snapshot_fact_production",
                entity_scope=["parcels", "facilities", "roads", "annotations"],
            ),
            session_id=session_id,
            village_name=state.get("config", {}).get("village_name", ""),
        )
        kg_facts = [fact.statement for fact in evidence.evidence_bundle.facts]
        from app.domain.assessment.l1_fact_projection import evidence_fact_to_l1_fact

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
                "location_facts": [fact.model_dump(mode="json") for fact in snapshot.location_facts],
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
