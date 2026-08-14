"""L2 aggregate node - merge L2StrategyFragments into L2Strategy.

Wave D decision: l2_aggregate does ONLY merge/dedup/provenance + persist +
gate + review. ALL extraction lives in the shared parse-compiler
(parsing/compiler/profiles/l2_strategy.py), which this node invokes per
dimension. It does NOT re-parse report content.
"""
from __future__ import annotations

from typing import Any

from app.domain.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.artifacts.artifact_descriptor import ArtifactDescriptor
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.domain.l1_contracts import EvidenceGap
from app.contracts.domain.l2_contracts import L2Strategy, L2StrategyFragment
from app.contracts.workflow.parsing_contracts import CompilationProfile
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


def merge_strategy_fragments(
    fragments: list[L2StrategyFragment],
    run_id: str,
) -> L2Strategy:
    goals: list[str] = []
    strategies: list[str] = []
    priorities: list[str] = []
    conflicts: list[Any] = []
    evidence_gaps: list[EvidenceGap] = []
    strategy_issues: list[Any] = []
    spatial_structure = ""
    dimension_provenance: list[Provenance] = []
    sources: list[EvidenceSource] = []

    for frag in fragments:
        goals.extend(frag.goals)
        strategies.extend(frag.strategies)
        priorities.extend(frag.priorities)
        conflicts.extend(frag.conflicts)
        evidence_gaps.extend(frag.evidence_gaps)
        strategy_issues.extend(frag.strategy_issues)
        if not spatial_structure and frag.spatial_structure:
            spatial_structure = frag.spatial_structure
        dimension_provenance.append(
            frag.provenance
            if frag.provenance is not None
            else Provenance(
                source="l2_observe",
                run_id=run_id,
                module="l2_observe",
                trace=[f"fragment:{frag.dimension_key}"],
            )
        )
        if frag.provenance and frag.provenance.source:
            sources.append(
                EvidenceSource(
                    source_type="report",
                    reference=frag.provenance.source,
                )
            )

    return L2Strategy(
        context_version="",
        artifact_id="",
        development_goals=_dedup(goals),
        spatial_structure=spatial_structure,
        implementation_priorities=_dedup(strategies + priorities),
        strategy_conflicts=conflicts,
        evidence_refs=[],
        evidence_gaps=evidence_gaps,
        sources=_dedup_sources(sources),
        strategy_issues=strategy_issues,
        dimension_provenance=dimension_provenance,
    )


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

    from app.data.ingestion.compiler.core import compile_dimension_report

    fragments: list[L2StrategyFragment] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        content = rec.get("content", "")
        summary = rec.get("summary", "") or ""
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
        try:
            frag = compile_dimension_report(
            CompilationProfile.L2_STRATEGY,
            dimension_key=dim_key,
            content=content,
            instruction=rec.get("instruction", "") or "",
            summary=summary,
            report_id=report_id,
            run_id=run_id,
            )
        except Exception as exc:  # noqa: BLE001 - one dimension must not break the aggregate
            logger.warning("[l2_aggregate] compile failed for dim=%s: %s", dim_key, exc)
            frag = None
        if frag is not None:
            fragments.append(frag)

    strategy = merge_strategy_fragments(fragments, run_id=run_id)
    strategy.context_version = context_version
    branch_id = str(state.get("branch_id") or "main")
    artifact_id = f"l2-{run_id}-{branch_id}-{semantic_checksum(strategy)[:16]}"
    strategy.artifact_id = artifact_id
    strategy.provenance = Provenance(
        source="l2_observe",
        run_id=run_id,
        module="l2_observe",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L2 STRATEGIZE aggregated strategy from compiled dimension fragments.",
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


__all__ = ["l2_aggregate", "merge_strategy_fragments"]
