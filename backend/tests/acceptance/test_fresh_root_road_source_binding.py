"""Fresh production-stage road binding without hand-written source IDs in L3."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest


_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))

from benchmark_real_evidence import _load_bundle  # noqa: E402


@pytest.mark.asyncio
async def test_fresh_target_projection_binds_one_real_road_line_from_l1_fact(
    monkeypatch, tmp_path
):
    """The official stage boundary must produce the exact line binding.

    The L3 intervention contains only a typed ``source_fact_refs`` value.  The
    simulated typed classifier chooses one member from the closed source
    vocabulary; it does not provide a source feature ID or any geometry to
    TARGET_PROJECTION.  The source ID and WKT must therefore come from the
    current bundle/KG path.
    """
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()

    from app.contracts.domain.l1_contracts import L1Fact
    from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
    from app.contracts.domain.planning_semantics import RoadPlanningParameters
    from app.contracts.program import PlanningClaim
    from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
    from app.contracts.spatial.grounding_contracts import GroundingResult
    from app.contracts.evidence.source_semantic_contracts import (
        SourceFeatureSemanticProposal,
        SourceFeatureSemanticProposalBatch,
    )
    from app.contracts.ports.planning_ports import PlanningPorts
    from app.evidence.identity.flash_source_semantic_classifier import (
        SourceSemanticClassifier,
    )
    from app.infrastructure.context.planning_context import PlanningContext
    from app.infrastructure.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter
    from app.infrastructure.kg.builder import KGBuilder
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.spatial.model.workspace import SpatialWorkspace
    from app.workflow.stage_adapter import persist_stage_artifact
    from app.workflow.stages.ground import ground_node
    from app.workflow.stages.target_projection import target_projection_node

    bundle, counts = _load_bundle()
    assert counts["current_road"] == 131
    session_id = "fresh-root-road-source-binding"
    workspace = SpatialWorkspace.from_bundle(
        bundle,
        session_id=session_id,
        source="fresh-root-acceptance",
    )
    roads = list(workspace.lines.get("roads_current") or [])
    assert roads
    target_source_id = str(
        (getattr(roads[0], "_raw", {}) or {}).get("source_feature_id") or ""
    ).strip()
    assert target_source_id

    kg = KGBuilder.build("金田村", bundle)
    context = PlanningContext(
        session_id=session_id,
        village_name="金田村",
        version=1,
        workspace=workspace,
        data_snapshot=workspace.snapshot,
        kg=kg,
        kg_session_ref=session_id,
        kg_version=1,
        ports=PlanningPorts(spatial_query=KGSpatialQueryAdapter(kg)),
    )
    fact_id = "l1:fresh-root:road"
    context.l1_snapshot_ref = "artifact://l1/fresh-root-road"
    context.l1_fact_records = [
        L1Fact(
            fact_id=fact_id,
            statement="金田村现状有一条需要提升的村道",
            fact_kind="document_observation",
            dimension_key="traffic",
            semantic_type="road",
            attributes={
                "normalized_name": "村道",
                "role": "road",
                "location": "金田村",
            },
            value=1,
            unit="条",
            source_refs=["report:traffic"],
            source_snapshot_ref=workspace.snapshot.snapshot_id,
        )
    ]

    class _Structured:
        async def ainvoke(self, messages):
            payload = json.loads(messages[1]["content"])
            proposals = []
            for item in payload["source_items"]:
                source_id = str(item["source_feature_id"])
                if source_id == target_source_id:
                    proposals.append(
                        SourceFeatureSemanticProposal(
                            source_feature_id=source_id,
                            candidate_ref=f"l1:{fact_id}:entity",
                            supporting_fact_refs=[fact_id],
                        )
                    )
                else:
                    proposals.append(
                        SourceFeatureSemanticProposal(source_feature_id=source_id)
                    )
            return SourceFeatureSemanticProposalBatch(proposals=proposals)

    class _SimulatedTypedClassifier:
        calls = 0

        def with_structured_output(self, _response_model, **_kwargs):
            self.calls += 1
            return _Structured()

    classifier = SourceSemanticClassifier(
        llm=_SimulatedTypedClassifier(),
        model_id="simulated-minimax-fresh-root",
    )
    context.evidence_graph = None

    intervention = PlanningIntervention(
        intervention_id="fresh-root-road-upgrade",
        target_id="fresh-root-road-upgrade",
        name="村道提升",
        planning_role="spatial_intervention",
        project_package_ref="pkg:fresh-root-road",
        admission_reason="typed_spatial_claim_ready",
        claim_refs=["fresh-root-road-claim"],
        source_fact_refs=[fact_id],
        category="road",
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        intervention_action="upgrade",
        spatial_requirements={
            "location": "金田村",
            "source_fact_refs": [fact_id],
        },
        road_parameters=RoadPlanningParameters(action="upgrade", length_m=100.0),
    )
    claim = PlanningClaim(
        claim_id="fresh-root-road-claim",
        dimension_key="traffic",
        statement="金田村现状有一条需要提升的村道",
        planning_role="spatial_intervention",
        project_package_ref="pkg:fresh-root-road",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        intervention_action="upgrade",
        road_parameters=RoadPlanningParameters(action="upgrade", length_m=100.0),
        location_hints=["金田村"],
        source_fact_refs=[fact_id],
    )
    program = PlanningProgram(
        interventions=[intervention],
        claims=[claim],
        l1_snapshot_ref=context.l1_snapshot_ref,
    )

    state = {
        "session_id": session_id,
        "run_id": session_id,
        "branch_id": "main",
        "config": {
            "village_name": "金田村",
            "source_semantic_llm_enabled": True,
        },
        "artifact_refs": {},
        "retry_counts": {},
        "context_version": "1",
        "context_ref": {
            "session_id": session_id,
            "version": "1",
            "snapshot_id": workspace.snapshot.snapshot_id,
            "snapshot_digest": workspace.snapshot.digest,
        },
        "source_semantic_classifier": classifier,
    }
    state["artifact_refs"]["planning_program"] = persist_stage_artifact(
        state,
        "l3",
        "PlanningProgram",
        program,
    )

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )

    async def run_stage(node):
        before = dict(state.get("artifact_refs") or {})
        patch = await node(state)
        state.update(patch)
        state["artifact_refs"] = {
            **before,
            **dict(patch.get("artifact_refs") or {}),
        }

    await run_stage(target_projection_node)
    projection = load_artifact(state, "target_projection", IntentCompilationResult)
    road_spec = projection.spatial_reference_specs[0]
    assert road_spec.reference.filter["rdf_type"] == "Road"
    assert road_spec.reference.filter["source_feature_ids"] == [target_source_id]
    assert road_spec.source_collection_key == "current_road"
    assert road_spec.source_binding_ref.startswith("source-binding:")
    assert road_spec.l1_fact_refs == [fact_id]
    assert classifier.llm.calls == 10

    first_projection_digest = state["artifact_refs"]["target_projection"]["digest"]
    first_semantic_digest = state["artifact_refs"][
        "source_semantic_classification"
    ]["digest"]
    await run_stage(target_projection_node)
    assert classifier.llm.calls == 10
    assert state["artifact_refs"]["target_projection"]["digest"] == (
        first_projection_digest
    )
    assert state["artifact_refs"]["source_semantic_classification"]["digest"] == (
        first_semantic_digest
    )

    await run_stage(ground_node)
    grounding = load_artifact(state, "grounding_result", GroundingResult)
    assert grounding.candidates
    assert not grounding.unresolved
    geometry = grounding.candidates[0].geometry
    assert geometry is not None
    assert geometry.kind == "line"
    assert geometry.granularity == "exact_feature"
    assert geometry.role == "execution_geometry"
    assert geometry.source_feature_ids == [target_source_id]
    assert geometry.l1_fact_refs == [fact_id]
    assert geometry.wkt
    assert "LINESTRING" in geometry.wkt or "MULTILINESTRING" in geometry.wkt

    first_ground_digest = state["artifact_refs"]["grounding_result"]["digest"]
    await run_stage(ground_node)
    assert classifier.llm.calls == 10
    assert state["artifact_refs"]["grounding_result"]["digest"] == first_ground_digest
