"""L2 aggregate node - merge L2StrategyFragments into L2Strategy.

Wave D decision: l2_aggregate does ONLY merge/dedup/provenance + persist +
gate + review. ALL extraction lives in the shared parse-compiler
(parsing/compiler/profiles/l2_strategy.py), which this node invokes per
dimension. It does NOT re-parse report content.
"""
from __future__ import annotations

from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap
from app.modules.schema.contracts.l2_contracts import L2Strategy, L2StrategyFragment
from app.modules.schema.contracts.parsing_contracts import CompilationProfile
from app.modules.schema.contracts.provenance import Provenance
from app.services.artifact_store import FilesystemArtifactStore
from app.services.review_package import write_review_package
from app.utils.logger import get_logger

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
    from app.services.report_store import ReportStore

    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    store = ReportStore.get_instance()
    raw_reports = await store.get_layer_reports_with_sources(session_id, layer=2)

    from app.modules.parsing.compiler.core import compile_dimension_report

    fragments: list[L2StrategyFragment] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        content = rec.get("content", "")
        summary = rec.get("summary", "") or ""
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
        frag = compile_dimension_report(
            CompilationProfile.L2_STRATEGY,
            dimension_key=dim_key,
            content=content,
            instruction=rec.get("instruction", "") or "",
            summary=summary,
            report_id=report_id,
            run_id=run_id,
        )
        if frag is not None:
            fragments.append(frag)

    strategy = merge_strategy_fragments(fragments, run_id=run_id)
    strategy.context_version = context_version
    artifact_id = f"l2-{run_id}-v1"
    strategy.artifact_id = artifact_id
    strategy.provenance = Provenance(
        source="l2_observe",
        run_id=run_id,
        module="l2_observe",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L2 STRATEGIZE aggregated strategy from compiled dimension fragments.",
    )

    artifact_store = FilesystemArtifactStore(base_dir=base_dir)
    ref = ArtifactRef(
        context_version=context_version,
        artifact_id=artifact_id,
        module="l2_strategize",
        run_id=run_id,
        artifact_type="L2Strategy",
        revision="v1",
    )
    artifact_store.store(ref, strategy.model_dump(mode="json"))
    logger.info("[l2_aggregate] L2Strategy stored: %s", ref)

    gate_decision = evaluate_l2_gate(strategy, run_id=run_id, context_version=context_version)

    pkg = build_l2_review_package(
        strategy=strategy,
        artifact_ref=ref,
        gate_decision=gate_decision,
        run_id=run_id,
    )
    review_id = write_review_package(pkg, base_dir=base_dir)
    logger.info("[l2_aggregate] review package written: review_id=%s", review_id)

    return {
        "l2_strategy_ref": {
            "artifact_id": artifact_id,
            "module": "l2_strategize",
            "run_id": run_id,
            "artifact_type": "L2Strategy",
            "revision": "v1",
            "context_version": context_version,
        },
        "l2_gate_decision": gate_decision.model_dump(mode="json"),
        "l2_review_id": review_id,
    }


__all__ = ["l2_aggregate", "merge_strategy_fragments"]
