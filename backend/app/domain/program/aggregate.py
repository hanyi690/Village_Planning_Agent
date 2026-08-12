"""L3 aggregate node - merge typed PlanningClaimSets into PlanningProgram.

L3 reports are produced as evidence-bearing claims by the LLM worker. This
node accepts only that typed contract and performs deterministic proposal
adaptation, deduplication, provenance, persistence, and gating. Markdown and
INSTRUCTION text are never executable inputs.
"""
from __future__ import annotations

from typing import Any

from app.domain.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.program import PlanningClaimSet, ProgramProposal
from app.domain.program.claim_adapter import proposals_from_claims
from app.domain.program.assembler import assemble_planning_program
from app.infrastructure.artifacts import ContentAddressedArtifactRepository
from app.modules.schema.contracts.artifact_descriptor import ArtifactDescriptor
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import EvidenceGap, L1Snapshot
from app.modules.schema.contracts.l2_contracts import L2Strategy
from app.modules.schema.contracts.l3_contracts import (
    InterventionDependency,
    L3ProgramFragment,
    PlanningProgram,
    ProgramIssue,
)
from app.modules.schema.contracts.provenance import Provenance
from app.services.artifact_fingerprint import semantic_checksum
from app.services.review_package import write_review_package
from app.services.run_paths import run_tmp_root
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


def _dedup_program_issues(items: list[ProgramIssue]) -> list[ProgramIssue]:
    seen: set[tuple[str, str, str, str]] = set()
    out: list[ProgramIssue] = []
    for item in items:
        key = (item.dimension_key, item.code, item.message, item.detail)
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def merge_program_fragments(
    fragments: list[L3ProgramFragment],
    run_id: str,
) -> PlanningProgram:
    proposals: list[ProgramProposal] = []
    dependencies: list[InterventionDependency] = []
    omissions: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    program_issues: list[ProgramIssue] = []
    dimension_provenance: list[Provenance] = []
    source_refs: list[str] = []

    for frag in fragments:
        claims = list(frag.claims or [])
        proposals.extend(
            frag.proposals
            if frag.proposals
            else proposals_from_claims(claims, dimension_key=frag.dimension_key)
        )
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

    program = assemble_planning_program(
        _dedup_by_id(proposals, id_attr="proposal_id", name_attr="name"),
        _dedup_dependencies(dependencies),
        omissions=_dedup(omissions),
        evidence_gaps=_dedup_by_id(evidence_gaps, id_attr="gap_id"),
        program_issues=_dedup_program_issues(program_issues),
        dimension_provenance=dimension_provenance,
        claims=[claim for frag in fragments for claim in (frag.claims or [])],
    )
    program.sources = [
        EvidenceSource(source_type="report", reference=s)
        for s in _dedup(source_refs)
    ]
    return program


def enrich_program_from_upstream(
    program: PlanningProgram,
    base_dir: str | None,
    run_id: str,
    context_version: str = "",
    context_fingerprint: str = "",
    artifact_refs: dict[str, Any] | None = None,
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

    repository = ContentAddressedArtifactRepository(
        run_tmp_root() if base_dir is None else base_dir
    )

    refs = artifact_refs or {}
    snapshot: L1Snapshot | None = None
    try:
        l1_ref_data = refs.get("l1_snapshot")
        if not isinstance(l1_ref_data, dict):
            raise ValueError("missing canonical l1_snapshot ref")
        l1_descriptor = ArtifactDescriptor.model_validate(l1_ref_data)
        l1_payload = repository.get_json(l1_descriptor)
        snapshot = L1Snapshot(**l1_payload)
    except Exception as e:
        logger.info("[l3_aggregate] L1 snapshot not found, skipping enrichment: %s", e)

    strategy: L2Strategy | None = None
    try:
        l2_ref_data = refs.get("l2_strategy")
        if not isinstance(l2_ref_data, dict):
            raise ValueError("missing canonical l2_strategy ref")
        l2_descriptor = ArtifactDescriptor.model_validate(l2_ref_data)
        l2_payload = repository.get_json(l2_descriptor)
        strategy = L2Strategy(**l2_payload)
    except Exception as e:
        logger.info("[l3_aggregate] L2 strategy not found, skipping enrichment: %s", e)

    if snapshot is not None:
        program.l1_snapshot_ref = str((refs.get("l1_snapshot") or {}).get("digest") or "")
        l1_constraints = list(snapshot.constraints)

    if strategy is not None:
        program.l2_strategy_ref = str((refs.get("l2_strategy") or {}).get("digest") or "")
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
    base_dir: str | None = None,
) -> dict[str, Any]:
    from app.services.report_store import ReportStore

    effective_base_dir = run_tmp_root() if base_dir is None else base_dir

    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    require_frozen_context(state)

    store = ReportStore.get_instance()
    raw_reports = await store.get_layer_reports_with_sources(session_id, layer=3)

    fragments: list[L3ProgramFragment] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        content = rec.get("content", "")
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
        try:
            claim_set = PlanningClaimSet.model_validate_json(content)
        except Exception as exc:
            raise ValueError(
                f"L3 report {dim_key} is not a PlanningClaimSet; Markdown/INSTRUCTION is not executable"
            ) from exc
        claims = [
            claim.model_copy(update={"dimension_key": claim.dimension_key or dim_key})
            for claim in claim_set.claims
        ]
        fragments.append(
            L3ProgramFragment(
                dimension_key=dim_key,
                claims=claims,
                program_issues=[
                    ProgramIssue(
                        stage="l3",
                        dimension_key=dim_key,
                        severity="error",
                        code="claim_set_diagnostic",
                        message=diagnostic,
                    )
                    for diagnostic in claim_set.diagnostics
                ],
                provenance=Provenance(
                    source=report_id,
                    run_id=run_id,
                    module="l3_plan",
                    trace=[f"claim_set:{dim_key}"],
                ),
            )
        )

    program = merge_program_fragments(fragments, run_id=run_id)
    program.context_version = context_version
    branch_id = str(state.get("branch_id") or "main")
    l1_constraints, l2_strategy = enrich_program_from_upstream(
        program,
        base_dir=base_dir,
        run_id=run_id,
        context_version=context_version,
        context_fingerprint=state.get("context_fingerprint", ""),
        artifact_refs=dict(state.get("artifact_refs") or {}),
    )
    artifact_id = f"l3-{run_id}-{branch_id}-{semantic_checksum(program)[:16]}"
    program.artifact_id = artifact_id
    program.provenance = Provenance(
        source="l3_plan",
        run_id=run_id,
        module="l3_plan",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L3 PLAN aggregated program from compiled dimension fragments.",
    )

    ref = ArtifactDescriptor.model_validate(
        store_artifact(
            state,
            "planning_program",
            "l3_plan",
            "PlanningProgram",
            program,
            base_dir=base_dir,
        )
    )
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
    review_id = write_review_package(pkg, base_dir=effective_base_dir)
    logger.info("[l3_aggregate] review package written: review_id=%s", review_id)

    try:
        from app.modules.evidence.step_report import save_step_report
        from app.workflow.stage_audit import build_input_audit

        await save_step_report(
            session_id,
            "L3",
            step_name="l3_aggregate",
            layer=3,
            inputs=build_input_audit(
                state,
                stage="L3",
                source_refs=["artifact:l1_snapshot", "artifact:l2_strategy", *[f"L3:{key}" for key in sorted(raw_reports)]],
                artifact_refs={
                    key: (state.get("artifact_refs") or {}).get(key)
                    for key in ("l1_snapshot", "l2_strategy")
                    if (state.get("artifact_refs") or {}).get(key)
                },
            ),
            outputs={
                "intervention_count": len(program.interventions),
                "spatial_instruction_count": sum(
                    1 for item in program.interventions
                    if getattr(item, "spatial_requirements", None)
                ),
                "program_issue_count": len(program.program_issues),
                "gate_route": gate_decision.feedback_route or ("PASS" if gate_decision.passed else "FAIL"),
            },
            artifacts=[{"key": "planning_program", **ref.model_dump(mode="json")}],
            diagnostics={"fact_consumer": "L1Snapshot + L2Strategy + L3 dimension reports"},
        )
    except Exception as exc:
        logger.debug("[l3_aggregate] step report failed: %s", exc)

    return {
        # The post-L3 chain consumes the canonical ref-only map.  Planning
        # program recovery must not depend on a duplicate top-level ref.
        "artifact_refs": {"planning_program": ref.model_dump(mode="json")},
        "l3_gate_decision": gate_decision.model_dump(mode="json"),
        "l3_review_id": review_id,
    }


__all__ = ["l3_aggregate", "merge_program_fragments", "enrich_program_from_upstream"]
