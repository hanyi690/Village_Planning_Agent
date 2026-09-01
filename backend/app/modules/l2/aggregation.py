"""L2 aggregate node for typed decision sets.

The worker is the only semantic producer.  This node validates the persisted
``L2DecisionSet`` envelopes, merges value objects, and creates the stage
artifact.  It never interprets report prose, headings, bullets, or keywords.
"""
from __future__ import annotations

from typing import Any

from app.core.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.l1.l1_contracts import EvidenceGap
from app.contracts.l2.l2_contracts import (
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
from app.workflow.validation.l1_fact_catalog import build_l1_fact_catalog
from app.workflow.validation.l2_boundary import normalize_l2_decision_boundary

from .validation import evaluate_l2_gate
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

    return decision.model_copy(update={"dimension_key": dimension_key, "diagnostics": diagnostics})


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
    from app.modules.evidence.requirements import requirements_from_l2

    strategy.evidence_requirements = list(requirements_from_l2(strategy))
    return strategy


async def l2_aggregate(
    state: dict[str, Any],
    *,
    base_dir: str = ".run-tmp",
) -> dict[str, Any]:
    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    require_frozen_context(state)

    known_l1_fact_ids: set[str] = set()
    l1_load_error = ""
    try:
        from app.infrastructure.artifacts.runtime import load_artifact

        l1_snapshot = load_artifact(state, "l1_snapshot")
        payload = (
            l1_snapshot.model_dump(mode="json")
            if hasattr(l1_snapshot, "model_dump")
            else l1_snapshot
        )
        if not isinstance(payload, dict):
            raise TypeError("L1 snapshot payload is not a typed object")
        known_l1_fact_ids = {
            str(item.get("fact_id") or "").strip()
            for item in (payload.get("fact_records") or [])
            if isinstance(item, dict) and str(item.get("fact_id") or "").strip()
        }
    except Exception as exc:  # fail closed below when refs are present
        l1_load_error = f"{type(exc).__name__}: {exc}"
        logger.warning("[l2_aggregate] unable to load L1 fact identity set: %s", exc)

    l1_fact_catalog = build_l1_fact_catalog(
        {"fact_id": value} for value in known_l1_fact_ids
    )

    from app.infrastructure.artifacts.dimension_runtime import (
        load_layer_dimension_products,
    )

    dimension_products, dimension_errors = load_layer_dimension_products(
        state,
        layer=2,
        model_type=L2DecisionSet,
    )
    raw_reports = dimension_products
    decision_sets: list[L2DecisionSet] = []
    for dim_key, typed_decision in dimension_products.items():
        try:
            decision = _normalize_decision_set(
                typed_decision,
                dimension_key=dim_key,
            )
            decision = normalize_l2_decision_boundary(
                decision,
                catalog=l1_fact_catalog,
            ).decision
            from app.workflow.validation.l2_closure import validate_l2_decision_set

            validate_l2_decision_set(
                decision,
                known_l1_fact_ids=set(l1_fact_catalog.usable_allowed_fact_ids),
            )
            decision_sets.append(decision)
        except Exception as exc:
            dimension_errors[dim_key] = f"{type(exc).__name__}: {exc}"

    strategy = merge_decision_sets(decision_sets, run_id=run_id)
    if l1_load_error:
        strategy.strategy_issues.append(StrategyIssue(
            stage="l2",
            severity="error",
            code="l1_fact_catalog_unavailable",
            message="L2 cannot validate its exact L1 fact dependency closure",
            detail=l1_load_error,
        ))
        strategy.evidence_gaps.append(EvidenceGap(
            gap_id="l2:l1-fact-catalog:unavailable",
            dimension="shared",
            description="Authoritative L1 fact identities could not be loaded",
            required_fact="restore the l1_snapshot CAS artifact and retry L2",
            severity="error",
        ))
    for dim_key, detail in sorted(dimension_errors.items()):
        strategy.strategy_issues.append(StrategyIssue(
            stage="l2",
            severity="error",
            code="dimension_product_incomplete",
            message=f"L2 dimension product is not consumable: {dim_key}",
            detail=detail,
        ))
        strategy.evidence_gaps.append(EvidenceGap(
            gap_id=f"l2:dimension:{dim_key}:product",
            dimension=dim_key,
            description="typed L2 dimension product is missing, pending, or invalid",
            required_fact="rerun the exact L2 dimension product or request HUMAN review",
            severity="error",
        ))
    strategy.context_version = context_version
    branch_id = str(state.get("branch_id") or "main")
    artifact_id = f"l2-{run_id}-{branch_id}-{semantic_checksum(strategy)[:16]}"
    strategy.artifact_id = artifact_id
    from app.modules.evidence.requirements import requirements_from_l2

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

    gate_ref = persist_gate_decision(
        state,
        "l2",
        gate_decision,
        output_refs={"l2_strategy": ref},
    )

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
