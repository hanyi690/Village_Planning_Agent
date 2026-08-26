"""L3 aggregate node - merge typed PlanningClaimSets into PlanningProgram.

L3 reports are produced as evidence-bearing claims by the LLM worker. This
node accepts only that typed contract and performs deterministic proposal
adaptation, deduplication, provenance, persistence, and gating. Only
PlanningClaimSet reports are executable inputs.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.domain.common.context_guard import require_frozen_context
from app.infrastructure.artifacts.runtime import store_artifact
from app.contracts.program import PlanningClaim, PlanningClaimSet
from app.domain.program.claim_adapter import (
    canonical_package_intervention_id,
    classify_claims,
    compact_interventions,
)
from app.domain.program.assembler import assemble_planning_program
from app.infrastructure.artifacts import ContentAddressedArtifactRepository
from app.contracts.artifacts.ref import ArtifactRef as ArtifactDescriptor
from app.contracts.evidence.evidence_contracts import EvidenceSource
from app.contracts.domain.l1_contracts import EvidenceGap, L1Snapshot
from app.contracts.domain.l2_contracts import L2Strategy
from app.contracts.domain.l3_contracts import (
    ClaimDisposition,
    InterventionDependency,
    L3ProgramFragment,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
)
from app.contracts.artifacts.provenance import Provenance
from app.infrastructure.artifacts.fingerprint import semantic_checksum
from app.infrastructure.reports.review_package import write_review_package
from app.infrastructure.paths import run_tmp_root
from app.infrastructure.logging import get_logger
from app.domain.program.failure_scope import error_fingerprint, infer_failure_scope

from .gate import evaluate_l3_gate
from .review import build_l3_review_package

logger = get_logger(__name__)


def _claim_diagnostic_issue(dimension_key: str, diagnostic: Any) -> ProgramIssue:
    """Preserve the severity encoded by the current claim contract."""
    message = str(diagnostic or "").strip()
    severity = "info"
    code = "claim_set_diagnostic_audit"
    for prefix, typed_severity in (
        ("ERROR[", "error"),
        ("WARNING[", "warning"),
        ("INFO[", "info"),
    ):
        if not message.startswith(prefix):
            continue
        end = message.find("]")
        code = message[len(prefix) : end] if end > len(prefix) else "claim_set_diagnostic"
        severity = typed_severity
        break
    else:
        severity = "warning"
        code = "claim_set_diagnostic_untyped"
    claim_id = ""
    if code != "semantic_compile_exhausted" and "] " in message:
        body = message.split("] ", 1)[1]
        candidate = body.split(":", 1)[0].strip()
        if candidate and candidate not in {"claim", "program", dimension_key}:
            claim_id = candidate
    if code == "semantic_compile_exhausted":
        severity = "warning"
    scope = infer_failure_scope(code, has_claim_identity=bool(claim_id))
    return ProgramIssue(
        stage="l3",
        dimension_key=dimension_key,
        claim_id=claim_id,
        claim_ids=[claim_id] if claim_id else [],
        severity=severity,
        code=code,
        message=message,
        root_issue_id=f"{dimension_key}:{error_fingerprint(message)}",
        failure_scope=scope.value,
    )


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


def _canonical_claims(
    fragments: list[L3ProgramFragment],
) -> tuple[list[PlanningClaim], list[ProgramIssue], list[str], set[str]]:
    """Keep one authoritative occurrence for each claim id.

    A claim id is the accounting key shared by L3, TARGET_PROJECTION and the
    review UI.  Repeating it in two dimension reports must therefore be
    visible as a merge decision rather than creating two competing
    dispositions (or silently letting the last claim win in a dictionary).
    The first occurrence remains authoritative; its full source lineage is
    preserved and the duplicate is recorded as an auditable omission/issue.
    """
    claims: list[PlanningClaim] = []
    by_id: dict[str, PlanningClaim] = {}
    issues: list[ProgramIssue] = []
    omissions: list[str] = []
    duplicate_ids: set[str] = set()
    for fragment in fragments:
        for claim in fragment.claims or []:
            claim_id = str(claim.claim_id or "").strip()
            if not claim_id:
                # PlanningClaim requires an id, but keep this guard at the
                # aggregation boundary if a future adapter loosens that
                # contract.
                issues.append(
                    ProgramIssue(
                        stage="l3",
                        dimension_key=fragment.dimension_key,
                        severity="error",
                        code="claim_id_missing",
                        message="L3 claim has no stable claim_id and cannot be accounted for",
                        reason="claim_id is the cross-stage accounting key",
                    )
                )
                omissions.append(f"claim_without_id:{fragment.dimension_key}")
                continue
            previous = by_id.get(claim_id)
            if previous is None:
                by_id[claim_id] = claim
                claims.append(claim)
                continue
            duplicate_ids.add(claim_id)
            same_semantics = previous.model_dump(
                mode="json", exclude={"dimension_key"}
            ) == claim.model_dump(mode="json", exclude={"dimension_key"})
            severity = "warning" if same_semantics else "error"
            code = "duplicate_claim_id" if same_semantics else "conflicting_duplicate_claim_id"
            message = (
                f"claim {claim_id} appears in multiple L3 dimensions; "
                "the first occurrence remains authoritative"
            )
            issues.append(
                ProgramIssue(
                    stage="l3",
                    dimension_key=fragment.dimension_key,
                    claim_id=claim_id,
                    claim_ids=[claim_id],
                    dimension_keys=sorted({previous.dimension_key, claim.dimension_key}),
                    severity=severity,
                    code=code,
                    message=message,
                    detail=(
                        "duplicate has identical semantic payload"
                        if same_semantics
                        else "duplicate carries a conflicting semantic payload"
                    ),
                    reason="claim ids must be unique across dimension fragments",
                )
            )
            omissions.append(f"duplicate_claim:{claim_id}:{fragment.dimension_key}")
    return claims, issues, omissions, duplicate_ids


def _canonical_dispositions(
    claims: list[PlanningClaim],
    dispositions: list[ClaimDisposition],
    *,
    duplicate_ids: set[str],
) -> tuple[list[ClaimDisposition], list[ProgramIssue]]:
    """Enforce exactly one disposition for every canonical claim occurrence."""
    by_id: dict[str, ClaimDisposition] = {}
    issues: list[ProgramIssue] = []
    for disposition in dispositions:
        claim_id = str(disposition.claim_id or "").strip()
        if not claim_id:
            continue
        if claim_id in by_id:
            issues.append(
                ProgramIssue(
                    stage="l3",
                    dimension_key=disposition.dimension_key,
                    claim_id=claim_id,
                    claim_ids=[claim_id],
                    severity="error",
                    code="duplicate_claim_disposition",
                    message=f"claim {claim_id} produced more than one disposition",
                    reason="one disposition is required per canonical claim id",
                )
            )
            continue
        by_id[claim_id] = disposition

    canonical: list[ClaimDisposition] = []
    for claim in claims:
        claim_id = str(claim.claim_id or "").strip()
        disposition = by_id.get(claim_id)
        if disposition is None:
            disposition = ClaimDisposition(
                claim_id=claim_id,
                dimension_key=claim.dimension_key,
                status="invalid",
                reason="claim disposition was not produced by L3 accounting",
            )
            issues.append(
                ProgramIssue(
                    stage="l3",
                    dimension_key=claim.dimension_key,
                    claim_id=claim_id,
                    claim_ids=[claim_id],
                    severity="error",
                    code="claim_disposition_missing",
                    message=f"claim {claim_id} has no L3 disposition",
                    reason="every canonical claim must be admitted, pending, deferred, merged, or invalid",
                )
            )
        if claim_id in duplicate_ids:
            disposition = disposition.model_copy(
                update={
                    "status": "merged_duplicate",
                    "reason": (
                        f"duplicate claim id merged; authoritative disposition was: "
                        f"{disposition.reason}"
                    ),
                }
            )
        canonical.append(disposition)
    return canonical, issues


def merge_program_fragments(
    fragments: list[L3ProgramFragment],
    run_id: str,
) -> PlanningProgram:
    interventions: list[PlanningIntervention] = []
    pending_grounding_claims: list[PlanningClaim] = []
    claim_dispositions: list[ClaimDisposition] = []
    dependencies: list[InterventionDependency] = []
    omissions: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    program_issues: list[ProgramIssue] = []
    dimension_provenance: list[Provenance] = []
    source_refs: list[str] = []

    canonical_claims, claim_identity_issues, claim_omissions, duplicate_ids = _canonical_claims(fragments)
    canonical_claim_by_id = {claim.claim_id: claim for claim in canonical_claims}
    for frag in fragments:
        claims = [
            claim
            for claim in (frag.claims or [])
            if canonical_claim_by_id.get(claim.claim_id) is claim
        ]
        if frag.interventions:
            for direct in frag.interventions:
                program_issues.append(
                    ProgramIssue(
                        stage="l3",
                        dimension_key=frag.dimension_key,
                        severity="error",
                        code="direct_intervention_not_admitted",
                        message=(
                            "L3 fragment interventions are diagnostic-only; "
                            "derive executable interventions from admitted claims"
                        ),
                        detail=direct.intervention_id,
                        reason="direct intervention authority is disabled",
                    )
                )
        classified_interventions, pending_claims, dispositions, classification_issues = (
            classify_claims(claims, dimension_key=frag.dimension_key)
        )
        interventions.extend(classified_interventions)
        pending_grounding_claims.extend(pending_claims)
        claim_dispositions.extend(dispositions)
        program_issues.extend(classification_issues)
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

    program_issues.extend(claim_identity_issues)
    omissions.extend(claim_omissions)
    claim_dispositions, disposition_issues = _canonical_dispositions(
        canonical_claims,
        claim_dispositions,
        duplicate_ids=duplicate_ids,
    )
    program_issues.extend(disposition_issues)

    original_ids = {
        item.intervention_id: (
            canonical_package_intervention_id(
                item.project_package_ref,
                item.category,
                item.expected_output_kind,
                item.asset_kind,
                item.materialization_role or "",
            )
            if item.project_package_ref and item.planning_role == "spatial_intervention"
            else item.intervention_id
        )
        for item in interventions
    }
    interventions, compaction_issues = compact_interventions(interventions)
    program_issues.extend(compaction_issues)
    dependencies = [
        dependency.model_copy(
            update={
                "from_intervention_id": original_ids.get(
                    dependency.from_intervention_id,
                    dependency.from_intervention_id,
                ),
                "to_intervention_id": original_ids.get(
                    dependency.to_intervention_id,
                    dependency.to_intervention_id,
                ),
            }
        )
        for dependency in dependencies
    ]

    program = assemble_planning_program(
        _dedup_by_id(interventions, id_attr="intervention_id", name_attr="name"),
        _dedup_dependencies(dependencies),
        omissions=_dedup(omissions),
        evidence_gaps=_dedup_by_id(evidence_gaps, id_attr="gap_id"),
        program_issues=_dedup_program_issues(program_issues),
        dimension_provenance=dimension_provenance,
        claims=canonical_claims,
    )
    program.pending_grounding_claims = pending_grounding_claims
    program.claim_dispositions = claim_dispositions
    from app.evidence.retrieval.requirements import requirements_from_l3

    program.evidence_requirements = list(requirements_from_l3(program))
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
    from app.infrastructure.reports.report_store import ReportStore

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
        content = rec.get("instruction") or rec.get("content", "")
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
        try:
            claim_set = PlanningClaimSet.model_validate_json(content)
        except Exception as exc:
            raise ValueError(
                f"L3 report {dim_key} is not a PlanningClaimSet; expected PlanningClaimSet JSON"
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
                    _claim_diagnostic_issue(dim_key, diagnostic)
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

    # The frontend's explicit demo marker is the only path that may add this
    # deterministic acceptance slice. It is still a normal PlanningClaim, so
    # admission, TARGET_PROJECTION, GROUND, SELECT and EXECUTE all exercise
    # their production contracts; no geometry is injected here.
    from app.domain.program.demo_narrow_slice import (
        build_demo_narrow_slice_claims,
        task_description_from_state,
    )

    demo_task = task_description_from_state(state)
    if "[SPATIAL_DEMO_NARROW_SLICE" not in demo_task:
        try:
            from app.database.operations import get_planning_session_async

            session_record = await get_planning_session_async(session_id)
            demo_task = str((session_record or {}).get("task_description") or "")
        except Exception:
            demo_task = ""
    demo_claims = build_demo_narrow_slice_claims(demo_task)
    if demo_claims:
        fragments.append(
            L3ProgramFragment(
                dimension_key="implementation",
                claims=demo_claims,
                provenance=Provenance(
                    source="demo:narrow_slice",
                    run_id=run_id,
                    module="demo_narrow_slice",
                    trace=[f"claim:{claim.claim_id}" for claim in demo_claims],
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
    # L3 is the only stage allowed to reinterpret planning prose.  Run a
    # bounded, schema-constrained semantic repair before deterministic target
    # projection; geometry/BSMs remain exclusively owned by GROUND.
    from app.domain.program.semantic_repair import repair_planning_program

    repair_result = await repair_planning_program(
        program,
        cache_path=(
            Path(effective_base_dir)
            / str(session_id)
            / "l3-semantic-repair-cache.json"
        ),
    )
    program = repair_result.program
    logger.info(
        "[l3_aggregate] semantic repair applied=%s attempts=%d cache_hits=%d errors=%d",
        repair_result.applied,
        repair_result.attempts,
        repair_result.cache_hits,
        len(repair_result.validation_errors),
    )
    artifact_id = f"l3-{run_id}-{branch_id}-{semantic_checksum(program)[:16]}"
    program.artifact_id = artifact_id
    from app.evidence.retrieval.requirements import requirements_from_l3

    program.evidence_requirements = list(requirements_from_l3(program))
    program.provenance = Provenance(
        source="l3_plan",
        run_id=run_id,
        module="l3_plan",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L3 PLAN aggregated program from compiled dimension fragments.",
    )

    source_semantic_errors = [
        issue
        for issue in program.program_issues
        if issue.severity == "error"
        and issue.code != "classification_decision_required"
    ]

    # LLM-assisted closed-set classification: polygon/parcel targets get a
    # planning land-use code from the authoritative appendix5 set as part of
    # L3 planning (auditable, evidence-backed), so EXECUTE does not need an
    # interactive HUMAN decision for every parcel/polygon output.  The codes
    # remain subject to VALIDATE; nothing is inferred from current dlbm.
    try:
        from app.domain.program.classification import (
            apply_classification_decisions,
            classification_review_targets,
        )
        from app.domain.program.classification_generator import (
            generate_classification_decisions,
        )

        pending = classification_review_targets(program)
        if source_semantic_errors:
            logger.warning(
                "[l3_aggregate] classification runs before routing %d source semantic errors to L3",
                len(source_semantic_errors),
            )
        if pending:
            decisions = await generate_classification_decisions(program)
            if decisions:
                revised, _ = apply_classification_decisions(
                    program,
                    [decision.model_dump(mode="json") for decision in decisions],
                )
                program = revised
                artifact_id = f"l3-{run_id}-{branch_id}-{semantic_checksum(program)[:16]}"
                program.artifact_id = artifact_id
                program.provenance = Provenance(
                    source="l3_plan",
                    run_id=run_id,
                    module="l3_plan",
                    trace=[f"aggregate:{artifact_id}"],
                    natural_language_description=(
                        "L3 PLAN aggregated program from compiled dimension fragments "
                        "(LLM classification revision)."
                    ),
                )
                logger.info(
                    "[l3_aggregate] applied %d LLM classification decisions",
                    len(decisions),
                )
    except Exception as exc:
        logger.warning("[l3_aggregate] LLM classification generation failed: %s", exc)

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

    from app.workflow.stage_adapter import persist_gate_decision

    gate_ref = persist_gate_decision(state, "l3", gate_decision)

    pkg = build_l3_review_package(
        program=program,
        artifact_ref=ref,
        gate_decision=gate_decision,
        run_id=run_id,
    )
    review_id = write_review_package(pkg, base_dir=effective_base_dir)
    logger.info("[l3_aggregate] review package written: review_id=%s", review_id)

    try:
        from app.infrastructure.reports.step_report import save_step_report
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
                "semantic_repair_applied": repair_result.applied,
                "semantic_repair_attempts": repair_result.attempts,
                "semantic_repair_cache_hits": repair_result.cache_hits,
                "semantic_repair_validation_errors": repair_result.validation_errors,
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
        "artifact_refs": {
            "planning_program": ref.model_dump(mode="json"),
            "l3_gate": gate_ref.model_dump(mode="json"),
        },
        "l3_review_id": review_id,
    }


__all__ = ["l3_aggregate", "merge_program_fragments", "enrich_program_from_upstream"]
