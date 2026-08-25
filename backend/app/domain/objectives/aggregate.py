"""L2 aggregate node for typed decision sets.

The worker is the only semantic producer.  This node validates the persisted
``L2DecisionSet`` envelopes, merges value objects, and creates the stage
artifact.  It never interprets report prose, headings, bullets, or keywords.
"""
from __future__ import annotations

import json
from typing import Any

from app.domain.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.domain.l1_contracts import EvidenceGap
from app.contracts.domain.l2_contracts import (
    ConflictHypothesis,
    L2DecisionSet,
    L2Strategy,
    PlanningObjective,
    PriorityDecision,
    SpatialStructureIntent,
    StrategyConflict,
    StrategyIssue,
    StrategyRule,
    TargetMetric,
)
from app.contracts.artifacts.provenance import Provenance
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.reports.review_package import write_review_package
from app.infrastructure.logging import get_logger

from .gate import evaluate_l2_gate
from .review import build_l2_review_package

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
    out: list[EvidenceSource] = []
    for s in sources:
        if s.reference not in seen:
            seen.add(s.reference)
            out.append(s)
    return out


def _dedup_models(values: list[Any], identity: str) -> list[Any]:
    seen: set[str] = set()
    result: list[Any] = []
    for value in values:
        key = str(getattr(value, identity, "") or "").strip()
        if not key:
            key = semantic_checksum(value)[:24]
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def _reference_issues(
    *,
    objectives: list[PlanningObjective],
    strategy_rules: list[StrategyRule],
    priority_decisions: list[PriorityDecision],
    spatial_intents: list[SpatialStructureIntent],
    conflicts: list[ConflictHypothesis],
) -> list[StrategyIssue]:
    """Check typed references without inferring semantic conflicts."""

    objective_ids = {item.objective_id for item in objectives}
    strategy_ids = {item.strategy_id for item in strategy_rules}

    def _missing(values: list[str], known: set[str]) -> list[str]:
        return [value for value in values if value and value not in known]

    issues: list[StrategyIssue] = []
    checks = [
        ("strategy", item.strategy_id, item.objective_refs, objective_ids)
        for item in strategy_rules
    ]
    checks.extend(
        ("priority", item.priority_id, item.strategy_refs, strategy_ids)
        for item in priority_decisions
    )
    checks.extend(
        ("spatial_structure", item.structure_id, item.objective_refs, objective_ids)
        for item in spatial_intents
    )
    checks.extend(
        ("conflict", item.conflict_id, [*item.objective_refs, *item.strategy_refs], objective_ids | strategy_ids)
        for item in conflicts
    )
    for kind, item_id, refs, known in checks:
        missing = _missing(refs, known)
        if missing:
            issues.append(
                StrategyIssue(
                    stage="l2",
                    severity="warning",
                    code="unknown_decision_reference",
                    message=f"{kind} {item_id} references unknown decision IDs",
                    detail=", ".join(missing),
                )
            )
    return issues


def _normalize_decision_set(
    payload: Any,
    *,
    dimension_key: str,
) -> L2DecisionSet:
    """Validate one worker envelope and assign only missing transport IDs."""

    decision = payload if isinstance(payload, L2DecisionSet) else L2DecisionSet.model_validate(payload)
    diagnostics = list(decision.diagnostics)
    if decision.dimension_key and decision.dimension_key != dimension_key:
        diagnostics.append(
            f"dimension_key_mismatch:{decision.dimension_key}->{dimension_key}"
        )
    decision = decision.model_copy(update={"dimension_key": dimension_key, "diagnostics": diagnostics})

    def _with_ids(items: list[Any], prefix: str, field: str) -> list[Any]:
        output: list[Any] = []
        for index, item in enumerate(items, start=1):
            if str(getattr(item, field, "") or "").strip():
                output.append(item)
            else:
                output.append(item.model_copy(update={field: f"{dimension_key}:{prefix}:{index}"}))
        return output

    gaps = []
    for index, gap in enumerate(decision.evidence_gaps, start=1):
        updates: dict[str, Any] = {}
        if not str(gap.gap_id or "").strip():
            updates["gap_id"] = f"{dimension_key}:evidence_gap:{index}"
        if not str(gap.dimension or "").strip():
            updates["dimension"] = dimension_key
        gaps.append(gap.model_copy(update=updates) if updates else gap)
    return decision.model_copy(
        update={
            "objectives": _with_ids(decision.objectives, "objective", "objective_id"),
            "metrics": _with_ids(decision.metrics, "metric", "metric_id"),
            "strategies": _with_ids(decision.strategies, "strategy", "strategy_id"),
            "priorities": _with_ids(decision.priorities, "priority", "priority_id"),
            "spatial_structures": _with_ids(decision.spatial_structures, "structure", "structure_id"),
            "conflicts": _with_ids(decision.conflicts, "conflict", "conflict_id"),
            "evidence_gaps": gaps,
        }
    )


def merge_decision_sets(
    decision_sets: list[L2DecisionSet],
    run_id: str,
) -> L2Strategy:
    objectives = _dedup_models(
        [item for decision in decision_sets for item in decision.objectives],
        "objective_id",
    )
    metrics = _dedup_models(
        [item for decision in decision_sets for item in decision.metrics],
        "metric_id",
    )
    strategy_rules = _dedup_models(
        [item for decision in decision_sets for item in decision.strategies],
        "strategy_id",
    )
    priority_decisions = _dedup_models(
        [item for decision in decision_sets for item in decision.priorities],
        "priority_id",
    )
    spatial_intents = _dedup_models(
        [item for decision in decision_sets for item in decision.spatial_structures],
        "structure_id",
    )
    conflict_hypotheses = _dedup_models(
        [item for decision in decision_sets for item in decision.conflicts],
        "conflict_id",
    )
    evidence_gaps = _dedup_models(
        [
            EvidenceGap(
                gap_id=gap.gap_id,
                dimension=gap.dimension,
                description=gap.description,
                required_fact=gap.required_fact,
                severity=gap.severity,
            )
            for decision in decision_sets
            for gap in decision.evidence_gaps
            if gap.description.strip()
        ],
        "gap_id",
    )

    goals = _dedup([
        item.statement.strip()
        for item in objectives
        if item.statement.strip() and item.kind == "goal"
    ])
    strategies = _dedup([
        item.statement.strip()
        for item in strategy_rules
        if item.statement.strip()
    ])
    priorities = _dedup([
        item.statement.strip()
        for item in priority_decisions
        if item.statement.strip()
    ] + strategies)
    spatial_structure = "；".join(
        item.statement.strip()
        for item in spatial_intents
        if item.statement.strip()
    )
    conflicts = [
        StrategyConflict(
            description=item.description,
            between=[*item.objective_refs, *item.strategy_refs],
            severity=item.severity,
        )
        for item in conflict_hypotheses
        if item.description.strip()
    ]
    strategy_issues = _reference_issues(
        objectives=objectives,
        strategy_rules=strategy_rules,
        priority_decisions=priority_decisions,
        spatial_intents=spatial_intents,
        conflicts=conflict_hypotheses,
    )
    dimension_provenance = [
        Provenance(
            source="l2_decision_set",
            run_id=run_id,
            module="l2_decision_set",
            trace=[f"dimension:{decision.dimension_key}"],
        )
        for decision in decision_sets
    ]
    source_refs = _dedup([
        ref
        for decision in decision_sets
        for ref in decision.source_refs
        if str(ref).strip()
    ])
    sources = _dedup_sources([
        EvidenceSource(source_type="report", reference=ref)
        for ref in source_refs
    ])
    strategy = L2Strategy(
        context_version="",
        artifact_id="",
        decision_sets=decision_sets,
        objectives=objectives,
        metrics=metrics,
        strategy_rules=strategy_rules,
        priority_decisions=priority_decisions,
        spatial_structure_intents=spatial_intents,
        conflict_hypotheses=conflict_hypotheses,
        development_goals=goals,
        spatial_structure=spatial_structure,
        implementation_priorities=priorities,
        strategy_conflicts=conflicts,
        evidence_refs=source_refs,
        evidence_gaps=evidence_gaps,
        sources=sources,
        strategy_issues=strategy_issues,
        dimension_provenance=dimension_provenance,
    )
    from app.evidence.retrieval.requirements import requirements_from_l2

    strategy.evidence_requirements = list(requirements_from_l2(strategy))
    return strategy


async def l2_aggregate(
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
    raw_reports = await store.get_layer_reports_with_sources(session_id, layer=2)

    decision_sets: list[L2DecisionSet] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        instruction = rec.get("instruction", "") or ""
        try:
            payload = instruction if isinstance(instruction, dict) else json.loads(instruction)
            decision_sets.append(_normalize_decision_set(payload, dimension_key=dim_key))
        except Exception as exc:  # noqa: BLE001 - one dimension must not break the aggregate
            logger.warning("[l2_aggregate] typed decision load failed for dim=%s: %s", dim_key, exc)

    strategy = merge_decision_sets(decision_sets, run_id=run_id)
    strategy.context_version = context_version
    branch_id = str(state.get("branch_id") or "main")
    artifact_id = f"l2-{run_id}-{branch_id}-{semantic_checksum(strategy)[:16]}"
    strategy.artifact_id = artifact_id
    from app.evidence.retrieval.requirements import requirements_from_l2

    strategy.evidence_requirements = list(requirements_from_l2(strategy))
    strategy.provenance = Provenance(
        source="l2_observe",
        run_id=run_id,
        module="l2_observe",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L2 STRATEGIZE aggregated typed decision sets.",
    )

    ref = ArtifactDescriptor.model_validate(
        store_artifact(
            state,
            "l2_strategy",
            "l2_strategize",
            "L2Strategy",
            strategy,
            base_dir=base_dir,
        )
    )
    logger.info("[l2_aggregate] L2Strategy stored: %s", ref)

    gate_decision = evaluate_l2_gate(strategy, run_id=run_id, context_version=context_version)

    from app.workflow.stage_adapter import persist_gate_decision

    gate_ref = persist_gate_decision(state, "l2", gate_decision)

    pkg = build_l2_review_package(
        strategy=strategy,
        artifact_ref=ref,
        gate_decision=gate_decision,
        run_id=run_id,
    )
    review_id = write_review_package(pkg, base_dir=base_dir)
    logger.info("[l2_aggregate] review package written: review_id=%s", review_id)

    try:
        from app.infrastructure.reports.step_report import save_step_report
        from app.workflow.stage_audit import build_input_audit

        await save_step_report(
            session_id,
            "L2",
            step_name="l2_aggregate",
            layer=2,
            inputs=build_input_audit(
                state,
                stage="L2",
                source_refs=["artifact:l1_snapshot", *[f"L2:{key}" for key in sorted(raw_reports)]],
                artifact_refs={"l1_snapshot": (state.get("artifact_refs") or {}).get("l1_snapshot")},
            ),
            outputs={
                "development_goals": strategy.development_goals,
                "implementation_priorities": strategy.implementation_priorities,
                "evidence_refs": strategy.evidence_refs,
                "evidence_gap_count": len(strategy.evidence_gaps),
                "gate_route": gate_decision.feedback_route or ("PASS" if gate_decision.passed else "FAIL"),
            },
            artifacts=[{"key": "l2_strategy", **ref.model_dump(mode="json")}],
            diagnostics={"fact_consumer": "L2 dimension prompts via EXPLORE evidence service"},
        )
    except Exception as exc:
        logger.debug("[l2_aggregate] step report failed: %s", exc)

    return {
        "artifact_refs": {
            "l2_strategy": ref.model_dump(mode="json"),
            "l2_gate": gate_ref.model_dump(mode="json"),
        },
        "l2_review_id": review_id,
    }


__all__ = ["l2_aggregate", "merge_decision_sets"]
