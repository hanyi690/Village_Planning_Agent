"""真实 bundle 上验证空间 stage artifact 的连续性。

该测试不调用外部 provider：L1 村落绑定使用受控的模拟 LLM，SELECT 的
terrain/suitability、scenario、EXECUTE、VALIDATE、RECONCILE、DELIVER 都走
生产实现。它专门验证大地块子几何不会在 stage 边界退回整块 BSM。
"""

from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")

from tests.acceptance.test_upload_fixtures import _uploads  # noqa: E402
from tests.fixtures.db import make_session_with_uploads  # noqa: E402


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"


@pytest.mark.asyncio
async def test_real_spatial_stage_chain_preserves_subgeometry_lineage(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path
):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-real-spatial-chain-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        run_root = tmp_path / "run-tmp"
        monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))
        from app.infrastructure.paths import reset_run_tmp_root_cache

        reset_run_tmp_root_cache()


        from app.application.sessions.session_bundle import build_session_bundle
        from app.contracts.artifacts.classification_ref import (
            ClassificationDecision,
            ClassificationSystem,
        )
        from app.contracts.domain.l1_contracts import L1LocationFact
        from app.contracts.evidence.source_semantic_contracts import (
            SourceFeatureSemanticDecision,
        )
        from app.contracts.domain.l3_contracts import PlanningIntervention, PlanningProgram
        from app.contracts.spatial.candidate_geometry import CandidateGeometry
        from app.contracts.spatial.grounded_problem import GroundedPlanningProblem
        from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
        from app.contracts.spatial.grounding_contracts import (
            CandidateSite,
            GroundingResult,
        )
        from app.contracts.workflow.parse_contracts import SiteAreaTarget, SpatialPlanningIntent
        from app.contracts.workflow.parse_result_contracts import (
            CompilationStatus,
            IntentCompilationResult,
        )
        from app.domain.ground.aggregate import ground_aggregate
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
        from app.evidence.retrieval.evidence_graph import (
            EvidenceGraph,
            enrich_evidence_packet_with_spatial_graph,
        )
        from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
        from app.contracts.evidence.evidence_contracts import ExplorationRequest
        from app.evidence.retrieval.evidence_service import retrieve_evidence
        from app.infrastructure.context.planning_context_factory import (
            build_planning_context,
        )
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.kg.manager import KGManager
        from app.domain.suitability.subgeometry import derive_planning_subgeometry
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            build_village_clusters,
            stable_entity_ref,
        )
        from app.workflow.stage_adapter import persist_stage_artifact
        from app.workflow.stages.deliver import deliver_node
        from app.workflow.stages.execute import execute_node
        from app.workflow.stages.reconcile import reconcile_node
        from app.workflow.stages.select import select_node
        from app.workflow.stages.validate import validate_node

        bundle = await build_session_bundle(sid)
        kg = KGManager().get_or_build_kg("金田村", bundle=bundle, session_id=sid)
        gazetteer = build_gazetteer(kg, bundle)
        report_text = (FIXTURE / "current_report.md").read_text(encoding="utf-8")

        context = await build_planning_context(
            sid,
            village_name="金田村",
            include_reports=True,
        )
        context.kg = kg
        context.gazetteer = gazetteer
        context.reports = {"current_report": report_text}
        parcels = list(context.current_parcels() or [])
        assert parcels

        clusters = build_village_clusters(parcels)
        assert clusters

        class _VillageBindingLLM:
            def with_structured_output(self, response_model, **_kwargs):
                class _Structured:
                    async def ainvoke(self, _prompt):
                        quote = "社前村"
                        start = report_text.index(quote)
                        return response_model(decisions=[{
                            "entity_ref": stable_entity_ref("village", "社前"),
                            "status": "mapped",
                            "candidate_ids": [
                                clusters[min(1, len(clusters) - 1)].cluster_id
                            ],
                            "source_span": {
                                "segment_id": "report",
                                "start": start,
                                "end": start + len(quote),
                                "quote_hash": hashlib.sha256(
                                    quote.encode("utf-8")
                                ).hexdigest(),
                            },
                            "reason_code": "",
                        }])

                return _Structured()

        for entry in await assign_villages_to_clusters(
            gazetteer,
            parcels,
            ["社前"],
            report_text,
            llm=_VillageBindingLLM(),
        ):
            gazetteer.upsert(entry)

        context.evidence_graph = EvidenceGraph(
            context,
            index=PlaceEvidenceIndex.build(context),
        )
        coarse_scope_target = "coarse-village-scope"
        coarse_scope_spec = SpatialReferenceSpec(
            type="topological",
            topo="sfWithin",
            reference=RefObject(kind="village", filter={"label_contains": "社前"}),
            target_id=coarse_scope_target,
        )
        coarse_scope_grounding = ground_aggregate([coarse_scope_spec], context)
        assert coarse_scope_grounding.candidates == []
        assert coarse_scope_grounding.unresolved
        assert coarse_scope_grounding.unresolved[0].code == "search_scope_not_materialized"
        assert (
            coarse_scope_grounding.spatial_query_evidence[0]
            .query_params["search_scope"]["scope_type"]
            == "village_scope"
        )
        raw_semantic_result = context.evidence_graph.query_facility_bsms(
            "社前村", "祠堂"
        )
        assert raw_semantic_result.status == "ambiguous"
        assert len(raw_semantic_result.candidates) > 1
        assert all(
            candidate.feature_bsm
            and candidate.source_feature_id
            for candidate in raw_semantic_result.candidates
        )
        raw_packet = enrich_evidence_packet_with_spatial_graph(
            EvidencePacket(request="社前村祠堂的BSM"),
            context,
            query="社前村祠堂的BSM",
            village_name="金田村",
            entity_scope=["facilities"],
        )
        assert raw_packet.ambiguity_status == "multiple"
        assert len(raw_packet.candidate_refs) == len(raw_semantic_result.candidates)
        assert all(
            ref.source_authority_score == 1.0
            and 0.0 < ref.semantic_match_score <= 1.0
            and 0.0 < ref.retrieval_score < 1.0
            and ref.selection_confidence is None
            for ref in raw_packet.candidate_refs
        )
        raw_live_result = await retrieve_evidence(
            ExplorationRequest(
                run_id=sid,
                request_type="spatial_lookup",
                query="社前村祠堂的BSM",
                stage="GROUND",
                dimension_key="location",
                entity_scope=["facilities"],
                required_facts=["BSM"],
            ),
            sid,
            village_name="金田村",
        )
        assert raw_live_result.evidence_packet is not None
        assert raw_live_result.evidence_packet.ambiguity_status == "multiple"
        assert len(raw_live_result.evidence_packet.candidate_refs) > 1

        context.location_facts = [
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                aliases=["祠堂", "祠"],
                spatial_hint="社前村",
                source_span="现状设施 | 祠堂 | 社前村 | 三座祠堂",
                source_report_ref="report:current",
                dimension_key="historical_culture",
                confidence=0.95,
            )
        ]
        context.l1_snapshot_ref = "artifact://l1/real-spatial-chain"
        semantic_decisions = {}
        for feature in list(
            (getattr(context.workspace, "points", {}) or {}).get(
                "annotations_current"
            ) or []
        ):
            raw = getattr(feature, "_raw", {}) or {}
            source_feature_id = str(raw.get("source_feature_id") or "").strip()
            if not source_feature_id or str(getattr(feature, "text", "") or "").strip() != "祠":
                continue
            semantic_decisions[source_feature_id] = SourceFeatureSemanticDecision(
                source_feature_id=source_feature_id,
                raw_label="祠",
                semantic_type="祠堂",
                status="accepted",
                authority="inferred_current",
                candidate_ref="l1:fixture:祠堂:entity",
                supporting_fact_refs=["report:current"],
            )
        assert semantic_decisions
        context.source_semantic_decisions = semantic_decisions
        context.evidence_graph = EvidenceGraph(
            context,
            index=PlaceEvidenceIndex.build(context),
        )
        scoped = context.evidence_graph.query_facility_bsms("社前村", "祠堂")
        assert scoped.status == "resolved", scoped
        facility = scoped.candidates[0]
        facility_ref = facility.entity_ref or "祠堂"
        assert facility.related_parcel_bsms

        # Black-box retrieval path: the user question must receive the same
        # bundle-backed identity and packet as the direct EvidenceGraph call.
        live_result = await retrieve_evidence(
            ExplorationRequest(
                run_id=sid,
                request_type="spatial_lookup",
                query="社前村祠堂的BSM",
                stage="GROUND",
                dimension_key="location",
                entity_scope=["facilities"],
                required_facts=["BSM"],
            ),
            sid,
            village_name="金田村",
        )
        live_packet = live_result.evidence_packet
        assert live_packet is not None
        assert live_packet.candidate_refs
        assert live_packet.ambiguity_status == "resolved"
        assert live_packet.candidate_refs[0].source_authority_score == 1.0
        assert 0.0 < live_packet.candidate_refs[0].semantic_match_score <= 1.0
        assert 0.0 < live_packet.candidate_refs[0].retrieval_score < 1.0
        assert live_packet.candidate_refs[0].selection_confidence is None
        assert live_packet.candidate_refs[0].identity.bundle_feature_bsm == (
            facility.feature_bsm or facility.source_bsm
        )
        assert any(
            fact.fact_type == "bundle_feature_identity"
            and fact.fields.get("bundle_feature_bsm")
            for fact in live_result.evidence_bundle.facts
        )

        # Real bundle acceptance for the LLM semantic-spec boundary: the
        # simulated parser contributes only a closed-set text qualifier; the
        # returned feature identity still comes from the real bundle/KG join.
        semantic_spec = SpatialReferenceSpec(
            type="attributive",
            reference=RefObject(
                kind="entity_type",
                filter={"label_contains": "祠堂"},
            ),
        )
        semantic_packet = enrich_evidence_packet_with_spatial_graph(
            EvidencePacket(request="社前村祠堂"),
            context,
            query="社前村祠堂",
            village_name="金田村",
            entity_scope=["facilities"],
            spatial_spec=semantic_spec,
        )
        assert semantic_packet.candidate_refs
        assert semantic_packet.candidate_refs[0].identity.bundle_feature_bsm
        assert any(
            trace.get("step") == "directional_scope_hint"
            and trace.get("parser") == "llm_structured"
            for trace in semantic_packet.query_trace
        )
        target_area_ha = 0.01
        target_id = "site-real-spatial-chain"
        planning_spec = semantic_spec.model_copy(update={"target_id": target_id})
        grounding = ground_aggregate(
            [planning_spec],
            context,
            target_metadata={
                target_id: {
                    "target_kind": "site_area",
                    "expected_output_kind": "polygon",
                }
            },
            evidence_packets={target_id: live_packet},
        )
        grounding = GroundingResult.model_validate(grounding.model_dump(mode="python"))
        assert not grounding.unresolved, grounding.unresolved
        assert grounding.candidates
        source_site = grounding.candidates[0]
        source_candidate = source_site.geometry
        assert source_candidate is not None
        assert source_candidate.feature_bsms
        assert source_candidate.source_bsms
        assert source_candidate.source_refs
        source_crs = str(
            getattr(getattr(context.workspace, "metadata", None), "crs", "")
            or getattr(context, "geometry_crs", "")
            or "EPSG:4326"
        )
        from shapely import wkt as shapely_wkt
        from shapely.geometry import shape

        parcels_by_bsm = {
            str(
                getattr(item, "bsm", "")
                or (item.get("bsm", "") if isinstance(item, dict) else "")
            ): item
            for item in parcels
            if str(
                getattr(item, "bsm", "")
                or (item.get("bsm", "") if isinstance(item, dict) else "")
            ).strip()
        }
        source_bsm = ""
        source_parcel_geometry = None
        planning_subgeometry = None
        for candidate_bsm in sorted(set(source_candidate.source_bsms)):
            parcel = parcels_by_bsm.get(candidate_bsm)
            if parcel is None:
                continue
            raw_geometry = (
                parcel.get("geometry")
                if isinstance(parcel, dict)
                else getattr(parcel, "geometry", None)
            )
            parcel_geometry = (
                shape(raw_geometry) if isinstance(raw_geometry, dict) else raw_geometry
            )
            if (
                parcel_geometry is None
                or parcel_geometry.is_empty
                or not parcel_geometry.is_valid
            ):
                continue
            candidate_subgeometry = derive_planning_subgeometry(
                parcel_geometry.wkt,
                source_crs=source_crs,
                target_area_ha=target_area_ha,
                tolerance_pct=5.0,
            )
            if (
                candidate_subgeometry is None
                or not candidate_subgeometry.feasible
                or candidate_subgeometry.operation
                in {"bundle_extent", "bundle_extent_within_tolerance"}
            ):
                continue
            source_bsm = candidate_bsm
            source_parcel_geometry = parcel_geometry
            planning_subgeometry = candidate_subgeometry
            break
        assert source_bsm
        assert source_bsm in parcels_by_bsm
        assert source_parcel_geometry is not None
        assert planning_subgeometry is not None
        assert planning_subgeometry.operation != "bundle_extent"

        planning_geometry_payload = source_candidate.model_dump(mode="python")
        planning_geometry_payload.update(
            {
                "candidate_id": "",
                "target_id": target_id,
                "kind": "polygon",
                "role": "execution_geometry",
                "candidate_membership": "alternative",
                "materialization_role": "site_footprint",
                "wkt": planning_subgeometry.geometry_wkt,
                "eligible_geometry_wkt": planning_subgeometry.eligible_geometry_wkt,
                "crs": source_crs,
                "granularity": "parcel_extent",
                "spatial_domain_kind": "parcel_extent",
                "candidate_bbox": tuple(
                    float(value)
                    for value in shapely_wkt.loads(
                        planning_subgeometry.geometry_wkt
                    ).bounds
                ),
                "source_area_ha": planning_subgeometry.source_area_ha,
                "planning_area_ha": planning_subgeometry.planning_area_ha,
                "coverage_ratio": planning_subgeometry.coverage_ratio,
                "source_ref": f"bundle:landuse_current:{source_bsm}",
                "source_refs": [
                    *source_candidate.source_refs,
                    f"bundle:landuse_current:{source_bsm}",
                ],
                "evidence_refs": [
                    *source_candidate.evidence_refs,
                    source_bsm,
                    f"bundle:landuse_current:{source_bsm}",
                ],
                "identity_confidence": source_candidate.identity_confidence or 0.9,
                "geometry_confidence": source_candidate.geometry_confidence or 0.9,
                "source_bsms": [source_bsm],
                "l1_snapshot_ref": context.l1_snapshot_ref,
                "bundle_snapshot_digest": str(context.data_snapshot.digest),
                "subgeometry_operation": planning_subgeometry.operation,
                "subgeometry_diagnostics": list(planning_subgeometry.diagnostics),
                "generation_operation": "grounded_parcel_refinement_fixture",
                "hard_constraint_status": "pending",
                "availability_status": planning_subgeometry.availability_status,
                "eligible_area_ha": planning_subgeometry.eligible_area_ha,
                "excluded_area_ha": planning_subgeometry.excluded_area_ha,
            }
        )
        planning_geometry = CandidateGeometry.model_validate(
            planning_geometry_payload
        )
        assert planning_geometry.grounding_ready
        assert planning_geometry.is_executable
        assert planning_geometry.role == "execution_geometry"
        assert planning_geometry.spatial_domain_kind == "parcel_extent"
        assert planning_geometry.subgeometry_operation != "bundle_extent"
        planning_site_payload = source_site.model_dump(mode="python")
        planning_site_payload.update(
            {
                "site_id": f"{source_site.site_id}:subgeometry:{source_bsm}",
                "candidate_id": planning_geometry.candidate_id,
                "source_parcels": [source_bsm],
                "available_geometry_wkt": planning_geometry.wkt,
                "available_area_ha": planning_geometry.planning_area_ha or 0.0,
                "source_area_ha": planning_geometry.source_area_ha or 0.0,
                "coverage_ratio": planning_geometry.coverage_ratio,
                "hard_constraint_result": {
                    "constraint_id": "ground_geometry",
                    "passed": True,
                },
                "target_ref": target_id,
                "target_kind": "site_area",
                "expected_output_kind": "polygon",
                "geometry": planning_geometry,
                "candidate_bbox": planning_geometry.candidate_bbox,
                "identity_confidence": planning_geometry.identity_confidence,
                "geometry_confidence": planning_geometry.geometry_confidence,
                "schema_status": "valid",
            }
        )
        planning_site = CandidateSite.model_validate(planning_site_payload)

        target_domains = []
        for domain in grounding.problem.target_domains:
            if domain.target_id == target_id:
                target_domains.append(
                    domain.model_copy(
                        update={
                            "target_kind": "site_area",
                            "expected_output_kind": "polygon",
                            "candidate_site_refs": [planning_site.site_id],
                            "geometry_roles": ["execution_geometry"],
                            "status": "resolved",
                            "evidence_refs": list(planning_geometry.evidence_refs),
                        }
                    )
                )
            else:
                target_domains.append(domain)
        candidate_domains = []
        for domain in grounding.problem.candidate_domains:
            if domain.target_id == target_id:
                candidate_domains.append(
                    domain.model_copy(
                        update={
                            "candidate_ids": [planning_geometry.candidate_id],
                            "candidate_geometry_refs": [planning_geometry.candidate_id],
                            "geometry_granularities": ["parcel_extent"],
                            "geometry_uncertainty_radius_m": 0.0,
                            "geometry_uncertainty_reasons": [],
                            "status": "resolved",
                            "deferred_reason": "",
                        }
                    )
                )
            else:
                candidate_domains.append(domain)
        planning_problem_payload = grounding.problem.model_dump(mode="python")
        planning_problem_payload.update(
            {
                "target_domains": target_domains,
                "candidate_domains": candidate_domains,
                "candidate_geometries": [planning_geometry],
                "parcel_resource_pool": None,
                "unresolved": [],
                "deferred": [],
                "fingerprint": "",
            }
        )
        planning_problem = GroundedPlanningProblem.model_validate(
            planning_problem_payload
        )
        assert planning_problem.candidate_completeness.ready
        grounding = grounding.model_copy(
            update={
                "candidates": [planning_site],
                "unresolved": [],
                "problem": planning_problem,
            }
        )
        target = SiteAreaTarget(
            target_id=target_id,
            site_area_id=target_id,
            name="社前村祠堂周边服务用地",
            category="公共服务",
            materialization_role="site_footprint",
            action="new",
            area_ha=target_area_ha,
            location_hint="社前村祠堂附近",
            candidate_bsms=[source_bsm],
            classification_decision=ClassificationDecision(
                target_id=target_id,
                code_system=ClassificationSystem.GBT21010,
                candidate_codes=["1103"],
                selected_code="1103",
                evidence_refs=["report:current"],
                status="resolved",
            ),
        )
        intent = SpatialPlanningIntent(
            village_name="金田村",
            site_area_targets=[target],
        )
        projection = IntentCompilationResult(
            typed_intent=intent,
            compilation_status=CompilationStatus.COMMITTED,
        )
        program = PlanningProgram(
            interventions=[
                PlanningIntervention(
                    intervention_id=target_id,
                    target_id=target_id,
                    name=target.name,
                    execution_mode="spatial",
                    expected_output_kind="polygon",
                    category="site_area",
                    materialization_role="site_footprint",
                    intervention_action="new",
                    classification_decision=target.classification_decision,
                )
            ],
            l1_snapshot_ref=context.l1_snapshot_ref,
        )

        state = {
            "session_id": sid,
            "run_id": sid,
            "branch_id": "main",
            "config": {"village_name": "金田村"},
            "artifact_refs": {},
            "retry_counts": {},
            "context_version": str(context.version),
        }
        for key, stage, schema_id, payload in (
            ("target_projection", "target_projection", "IntentCompilationResult", projection),
            ("grounding_result", "ground", "GroundingResult", grounding),
            ("planning_program", "target_projection", "PlanningProgram", program),
        ):
            state["artifact_refs"][key] = persist_stage_artifact(
                state, stage, schema_id, payload
            )
        context_patch = {
            "context_ref": {
                "session_id": sid,
                "version": str(context.version),
                "snapshot_digest": str(context.data_snapshot.digest),
            },
            "context_version": str(context.version),
        }
        state.update(context_patch)

        async def _run_stage(node, current):
            before = dict(current.get("artifact_refs") or {})
            patch = await node(current)
            merged = dict(current)
            merged.update(patch)
            merged["artifact_refs"] = {
                **before,
                **dict(patch.get("artifact_refs") or {}),
            }
            return merged

        state = await _run_stage(select_node, state)
        scenario_ref = state["artifact_refs"].get("planning_scenario")
        assert scenario_ref
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.contracts.planning.scenario import PlanningScenario

        scenario = load_artifact(state, "planning_scenario", PlanningScenario)
        from app.domain.suitability.model import SuitabilitySurface

        suitability = load_artifact(state, "suitability_surface", SuitabilitySurface)
        assert scenario.status in {"complete", "partial"}, json.dumps({
            "status": scenario.status,
            "selected": {
                item.target_id: item.candidate_ids
                for item in scenario.target_selections
            },
            "relations": [item.model_dump(mode="json") for item in scenario.relation_satisfactions],
            "findings": [item.model_dump(mode="json") for item in scenario.findings],
            "suitability": [item.model_dump(mode="json") for item in suitability.candidates],
            "target_diagnostics": suitability.target_diagnostics,
        }, ensure_ascii=False)
        selected_feature = next(
            item for item in scenario.feature_intents if item.target_id == target_id
        )
        assert selected_feature.subgeometry_operation != "bundle_extent"
        assert selected_feature.subgeometry_operation == planning_subgeometry.operation
        assert selected_feature.source_bsms
        assert selected_feature.source_bsms == [source_bsm]
        assert set(selected_feature.source_bsms).issubset(
            set(source_candidate.source_bsms)
        )
        assert selected_feature.geometry_wkt != source_parcel_geometry.wkt

        state = await _run_stage(execute_node, state)
        assert state["artifact_refs"].get("execution_result")
        state = await _run_stage(validate_node, state)
        final_relation_ref = state["artifact_refs"].get("final_relation_validation")
        assert final_relation_ref
        from app.domain.validation.relation_validation import FinalScenarioValidation

        final_validation = load_artifact(
            state,
            "final_relation_validation",
            FinalScenarioValidation,
        )
        assert final_validation.passed, json.dumps(
            {
                "status": final_validation.status,
                "findings": [
                    item.model_dump(mode="json")
                    for item in final_validation.findings
                ],
                "satisfactions": [
                    item.model_dump(mode="json")
                    for item in final_validation.satisfactions
                ],
                "final_features": [
                    {
                        "target_id": item.target_id,
                        "candidate_id": item.candidate_id,
                        "crs": item.crs,
                        "geometry_wkt": item.geometry_wkt[:240],
                    }
                    for item in final_validation.final_features
                ],
                "hard_blockers": final_validation.hard_blockers,
            },
            ensure_ascii=False,
        )
        state = await _run_stage(reconcile_node, state)
        assert state["artifact_refs"].get("reconciliation_report")
        state = await _run_stage(deliver_node, state)
        assert state["artifact_refs"].get("delivery_manifest")
        assert state["artifact_refs"].get("delivery_spatial_snapshot")
        assert state["artifact_refs"].get("render_layers")
        from app.contracts.artifacts.delivery_manifest_contracts import DeliveryManifest

        manifest = load_artifact(state, "delivery_manifest", DeliveryManifest)
        assert manifest.delivery_status in {"complete", "partial"}, json.dumps(
            manifest.diagnostic_summary,
            ensure_ascii=False,
        )
        assert (
            manifest.diagnostic_summary.get("planning_output", {}).get("status")
            == "ready"
        ), manifest.diagnostic_summary
        from app.application.queries.artifacts import ArtifactRead
        from app.application.projections.delivery import DeliveryProjectionService

        async def fake_workflow_state(_session_id):
            return {"session_id": _session_id}

        async def fake_artifact_read(_session_id, key):
            payload = load_artifact(state, key)
            if payload is None:
                return None
            if hasattr(payload, "model_dump"):
                payload = payload.model_dump(mode="json")
            return ArtifactRead(
                session_id=_session_id,
                artifact_key=key,
                artifact_ref=dict(state["artifact_refs"].get(key) or {}),
                payload=payload,
            )

        monkeypatch.setattr(
            "app.application.projections.delivery.load_workflow_state",
            fake_workflow_state,
        )
        monkeypatch.setattr(
            "app.application.projections.delivery.artifact_queries.read",
            fake_artifact_read,
        )
        map_layers = await DeliveryProjectionService().map_layers(sid)
        assert map_layers.delivery_status in {"complete", "partial"}
        assert map_layers.layers
        assert any(
            layer.layer_name == "complete_planned_landuse"
            and layer.feature_count > 0
            for layer in map_layers.layers
        )
        planned_layer = next(
            layer
            for layer in map_layers.layers
            if layer.layer_name == "complete_planned_landuse"
        )
        planned_feature = next(
            feature
            for feature in planned_layer.geojson["features"]
            if feature.get("properties", {}).get("target_id") == target_id
        )
        planned_properties = planned_feature["properties"]
        assert planned_properties["source_bsms"] == [source_bsm]
        assert planned_properties["subgeometry_operation"] == (
            planning_subgeometry.operation
        )
        assert planned_properties["subgeometry_operation"] != "bundle_extent"
        assert all(
            layer.geojson.get("type") == "FeatureCollection"
            and isinstance(layer.geojson.get("features"), list)
            for layer in map_layers.layers
        )
    finally:
        await teardown()
