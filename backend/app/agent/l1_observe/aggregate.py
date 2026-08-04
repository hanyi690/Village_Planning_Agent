"""L1 aggregate node - merge 12 L1DimensionFragments into L1Snapshot.

Wave B decision: l1_aggregate does ONLY merge/dedup/conflict/provenance +
persist + gate + review. ALL extraction lives in the shared parse-compiler
(parsing/compiler/profiles/l1_observation.py), which this node invokes per
dimension. It does NOT re-parse report content.
"""
from __future__ import annotations

from typing import Any

from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.classification_ref import ClassificationRef
from app.modules.schema.contracts.contract_meta import StageIssue
from app.modules.schema.contracts.l1_contracts import EvidenceGap, L1DimensionFragment, L1Snapshot
from app.modules.schema.contracts.parsing_contracts import CompilationProfile
from app.modules.schema.contracts.provenance import Provenance
from app.services.artifact_store import FilesystemArtifactStore
from app.services.review_package import write_review_package
from app.utils.logger import get_logger

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


def merge_fragments(
    fragments: list[L1DimensionFragment],
    run_id: str,
) -> L1Snapshot:
    facts: list[str] = []
    constraints: list[str] = []
    issues: list[StageIssue] = []
    opportunities: list[str] = []
    evidence_gaps: list[EvidenceGap] = []
    classification_refs: list[ClassificationRef] = []
    dimension_provenance: list[Provenance] = []

    for frag in fragments:
        facts.extend(frag.facts)
        constraints.extend(frag.constraints)
        issues.extend(frag.issues)
        opportunities.extend(frag.opportunities)
        evidence_gaps.extend(frag.evidence_gaps)
        classification_refs.extend(frag.classification_refs)
        dimension_provenance.append(
            frag.provenance
            if frag.provenance is not None
            else Provenance(
                source="l1_observe",
                run_id=run_id,
                module="l1_observe",
                trace=[f"fragment:{frag.dimension_key}"],
            )
        )

    snapshot = L1Snapshot(
        context_version="",
        artifact_id="",
        facts=_dedup(facts),
        constraints=_dedup(constraints),
        issues=issues,
        opportunities=_dedup(opportunities),
        evidence_gaps=evidence_gaps,
        sources=[],
        classification_refs=classification_refs,
        dimension_provenance=dimension_provenance,
    )

    fact_keys: dict[str, list[str]] = {}
    for f in snapshot.facts:
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
    from app.services.report_store import ReportStore

    run_id = state.get("run_id", state.get("session_id", ""))
    session_id = state.get("session_id", run_id)
    context_version = state.get("context_version", "")

    store = ReportStore.get_instance()
    raw_reports = await store.get_layer_reports_with_sources(session_id, layer=1)

    from app.modules.parsing.compiler.core import compile_dimension_report

    fragments: list[L1DimensionFragment] = []
    for dim_key, rec in raw_reports.items():
        rec = rec or {}
        content = rec.get("content", "")
        summary = rec.get("summary", "") or ""
        report_id = rec.get("report_id", f"rpt-{dim_key}-v1")
        frag = compile_dimension_report(
            CompilationProfile.L1_OBSERVATION,
            dimension_key=dim_key,
            content=content,
            instruction=content,
            summary=summary,
            report_id=report_id,
            run_id=run_id,
        )
        if frag is not None:
            fragments.append(frag)

    snapshot = merge_fragments(fragments, run_id=run_id)
    snapshot.context_version = context_version
    artifact_id = f"l1-{run_id}-v1"
    snapshot.artifact_id = artifact_id
    snapshot.provenance = Provenance(
        source="l1_observe",
        run_id=run_id,
        module="l1_observe",
        trace=[f"aggregate:{artifact_id}"],
        natural_language_description="L1 OBSERVE aggregated snapshot from compiled dimension fragments.",
    )

    artifact_store = FilesystemArtifactStore(base_dir=base_dir)
    ref = ArtifactRef(
        context_version=context_version,
        artifact_id=artifact_id,
        module="l1_observe",
        run_id=run_id,
        artifact_type="L1Snapshot",
        revision="v1",
    )
    artifact_store.store(ref, snapshot.model_dump(mode="json"))
    logger.info("[l1_aggregate] L1Snapshot stored: %s", ref)

    gate_decision = evaluate_l1_gate(snapshot, run_id=run_id, context_version=context_version)

    pkg = build_l1_review_package(
        snapshot=snapshot,
        artifact_ref=ref,
        gate_decision=gate_decision,
        run_id=run_id,
    )
    review_id = write_review_package(pkg, base_dir=base_dir)
    logger.info("[l1_aggregate] review package written: review_id=%s", review_id)

    return {
        "l1_snapshot_ref": {
            "artifact_id": artifact_id,
            "module": "l1_observe",
            "run_id": run_id,
            "artifact_type": "L1Snapshot",
            "revision": "v1",
            "context_version": context_version,
        },
        "l1_gate_decision": gate_decision.model_dump(mode="json"),
        "l1_review_id": review_id,
    }


__all__ = ["l1_aggregate", "merge_fragments"]
