"""L3 aggregate node - merge L3ProgramFragments into PlanningProgram.

Wave E decision: l3_aggregate does ONLY merge/dedup/provenance + persist +
gate + review. ALL extraction lives in the shared parse-compiler
(parsing/compiler/profiles/l3_planning.py), which this node invokes per
dimension. It does NOT re-parse report content.
"""
from __future__ import annotations

from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap, L1Snapshot
from app.modules.schema.contracts.l2_contracts import L2Strategy
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    L3ProgramFragment,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.modules.schema.contracts.parsing_contracts import CompilationProfile
from app.modules.schema.contracts.provenance import Provenance
from app.services.artifact_store import FilesystemArtifactStore
from app.services.review_package import write_review_package
from app.utils.logger import get_logger

from .gate import evaluate_l3_gate
from .review import build_l3_review_package

logger = get_logger(__name__)


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _dedup_by_id(
    items: list[Any],
    *,
    id_attr: str = "intervention_id",
    name_attr: str | None = None,
) -> list[Any]:
    """Dedup by ``id_attr`` keeping first occurrence.

    When ``name_attr`` is given and the same id reappears with a different
    name (rare), both items are kept to avoid dropping a distinct target.
    """
    out: list[Any] = []
    seen: dict[Any, Any] = {}
    for item in items:
        key = getattr(item, id_attr)
        if name_attr is None:
            if key not in seen:
                seen[key] = True
                out.append(item)
            continue
        prev = seen.get(key)
        if prev is None:
            seen[key] = getattr(item, name_attr)
            out.append(item)
        elif prev == getattr(item, name_attr):
            continue
        else:
            seen[key] = getattr(item, name_attr)
            out.append(item)
    return out


def _dedup_dependencies(
    deps: list[InterventionDependency],
) -> list[InterventionDependency]:
    seen: set[tuple[str, str]] = set()
    out: list[InterventionDependency] = []
    for dep in deps:
        key = (dep.from_intervention_id, dep.to_intervention_id)
        if key not in seen:
            seen.add(key)
            out.append(dep)
    return out


def merge_program_fragments(
    fragments: list[L3ProgramFragment],
    run_id: str,
) -> PlanningProgram:
    interventions: list[PlanningIntervention] = []
    dependencies: list[InterventionDependency] = []
    omissions: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    program_issues: list[ProgramIssue] = []
    dimension_provenance: list[Provenance] = []
    source_refs: list[str] = []

    for frag in fragments:
        interventions.extend(frag.interventions)
        dependencies.extend(frag.dependencies)
        omissions.extend(frag.omissions)
        evidence_gaps.extend(frag.evidence_gaps)
        program_issues.extend(frag.program_issues)
        if frag.provenance is not None and frag.provenance.source:
            source_refs.append(frag.provenance.source)
        dimension_provenance.append(
            frag.provenance
            if frag.provenance is not None
            else Provenance(
                source="l3_plan",
                run_id=run_id,
                module="l3_plan",
                trace=[f"fragment:{frag.dimension_key}"],
            )
        )

    return PlanningProgram(
        interventions=_dedup_by_id(
            interventions, id_attr="intervention_id", name_attr="name"
        ),
        dependencies=_dedup_dependencies(dependencies),
        omissions=_dedup(omissions),
        evidence_gaps=_dedup_by_id(evidence_gaps, id_attr="gap_id"),
        sources=[
            EvidenceSource(source_type="report", reference=s)
            for s in _dedup(source_refs)
        ],
        program_issues=program_issues,
        dimension_provenance=dimension_provenance,
        provenance=None,
    )


def enrich_program_from_upstream(
    program: PlanningProgram,
    base_dir: str,
    run_id: str,
) -> tuple[list[str] | None, Any | None]:
    """Load L1/L2 artifacts by run_id convention and enrich the program.

    Sets ``l1_snapshot_ref`` / ``l2_strategy_ref``, back-fills each
    intervention's ``derives_from_strategy`` from the L2 spatial structure,
    and appends cross-layer warning issues (``l1_constraint_unaddressed`` /
    ``strategy_orphan``). Returns ``(l1_constraints, l2_strategy)`` for the
    L3 gate; each is ``None`` when the corresponding artifact is unavailable.
    """
    l1_constraints: list[str] | None = None
    l2_strategy: Any | None = None

    store = FilesystemArtifactStore(base_dir=base_dir)

    snapshot: L1Snapshot | None = None
    try:
        l1_payload = store.retrieve(
            ArtifactRef(
                artifact_id=f"l1-{run_id}-v1",
                module="l1_observe",
                run_id=run_id,
                artifact_type="L1Snapshot",
                revision="v1",
            )
        )
        snapshot = L1Snapshot(**l1_payload)
    except Exception as e:
        logger.info("[l3_aggregate] L1 snapshot not found, skipping enrichment: %s", e)

    strategy: L2Strategy | None = None
    try:
        l2_payload = store.retrieve(
            ArtifactRef(
                artifact_id=f"l2-{run_id}-v1",
                module="l2_strategize",
                run_id=run_id,
                artifact_type="L2Strategy",
                revision="v1",
            )
        )
        strategy = L2Strategy(**l2_payload)
    except Exception as e:
        logger.info("[l3_aggregate] L2 strategy not found, skipping enrichment: %s", e)

    if snapshot is not None:
        program.l1_snapshot_ref = f"l1-{run_id}-v1"
        l1_constraints = list(snapshot.constraints)

    if strategy is not None:
        program.l2_strategy_ref = f"l2-{run_id}-v1"
        l2_strategy = strategy
        for intervention in program.interventions:
            if intervention.derives_from_strategy is None:
                if strategy.spatial_structure:
                    intervention.derives_from_strategy = strategy.spatial_structure
                elif strategy.implementation_priorities:
                    intervention.derives_from_strategy = strategy.implementation_priorities[0]

    if snapshot is not None and snapshot.constraints:
        for intervention in program.interventions:
            unaddressed = [
                c
                for c in snapshot.constraints
                if not any(c.lower() in ic.lower() for ic in intervention.constraints)
            ]
            if unaddressed:
                program.program_issues.append(
                    ProgramIssue(
                        stage="l3",
                        severity="warning",
                        code="l1_constraint_unaddressed",
                        message="L1 约束未被干预方案覆盖: " + "; ".join(unaddressed[:3]),
                        detail="; ".join(unaddressed[:3]),
                    )
                )

    if (
        strategy is not None
        and strategy.spatial_structure
        and not any(i.derives_from_strategy for i in program.interventions)
    ):
        program.program_issues.append(
            ProgramIssue(
                stage="l3",
                severity="warning",
                code="strategy_orphan",
                message="L2 空间结构未映射到任何干预方案",
                detail=strategy.spatial_structure,
            )
        )

    return l1_constraints, l2_strategy


async def l3_aggregate(
    state: dict[str, Any],
    *,
    base_dir: str = ".run-tmp",
) -> dict[str, Any]:
    from app.services.report_store import ReportStore

    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    store = ReportStore.get_instance()
    raw_reports = await store.get_layer_reports_with_sources(session_id, layer=3)

    from app.modules.parsing.compiler.core import compile_dimension_report

    fragments: list[L3ProgramFragment] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        content = rec.get("content", "")
        summary = rec.get("summary", "") or ""
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
        frag = compile_dimension_report(
            CompilationProfile.L3_PLANNING,
            dimension_key=dim_key,
            content=content,
            instruction=rec.get("instruction", "") or "",
            summary=summary,
            report_id=report_id,
            run_id=run_id,
        )
        if frag is not None:
            fragments.append(frag)

    program = merge_program_fragments(fragments, run_id=run_id)
    program.context_version = context_version
    artifact_id = f"l3-{run_id}-v1"
    program.artifact_id = artifact_id
    program.provenance = Provenance(
        source="l3_plan",
        run_id=run_id,
        module="l3_plan",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L3 PLAN aggregated program from compiled dimension fragments.",
    )

    l1_constraints, l2_strategy = enrich_program_from_upstream(
        program, base_dir=base_dir, run_id=run_id
    )

    artifact_store = FilesystemArtifactStore(base_dir=base_dir)
    ref = ArtifactRef(
        context_version=context_version,
        artifact_id=artifact_id,
        module="l3_plan",
        run_id=run_id,
        artifact_type="PlanningProgram",
        revision="v1",
    )
    artifact_store.store(ref, program.model_dump(mode="json"))
    logger.info("[l3_aggregate] PlanningProgram stored: %s", ref)

    gate_decision = evaluate_l3_gate(
        program,
        run_id=run_id,
        context_version=context_version,
        l1_constraints=l1_constraints,
        l2_strategy=l2_strategy,
    )

    pkg = build_l3_review_package(
        program=program,
        artifact_ref=ref,
        gate_decision=gate_decision,
        run_id=run_id,
    )
    review_id = write_review_package(pkg, base_dir=base_dir)
    logger.info("[l3_aggregate] review package written: review_id=%s", review_id)

    return {
        "l3_program_ref": {
            "artifact_id": artifact_id,
            "module": "l3_plan",
            "run_id": run_id,
            "artifact_type": "PlanningProgram",
            "revision": "v1",
            "context_version": context_version,
        },
        "l3_gate_decision": gate_decision.model_dump(mode="json"),
        "l3_review_id": review_id,
    }


__all__ = ["l3_aggregate", "merge_program_fragments", "enrich_program_from_upstream"]
