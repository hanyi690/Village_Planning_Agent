"""Production stage boundary: simulated L3 output through TARGET_PROJECTION and GROUND."""

from __future__ import annotations

import json
import hashlib
import os
import uuid
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from tests.acceptance.test_upload_fixtures import _uploads
from tests.fixtures.db import make_session_with_uploads


FIXTURE = Path(__file__).parents[1] / "fixtures" / "mvp_village"


@pytest.mark.asyncio
@pytest.mark.timeout(120)
async def test_simulated_l3_reaches_ground_without_manual_projection(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path
):
    setup, teardown = sqlite_db
    await setup()
    try:
        sid = "sess-simulated-l3-ground-" + uuid.uuid4().hex[:6]
        await make_session_with_uploads(sid, "金田村", uploads=_uploads())

        run_root = tmp_path / "run-tmp"
        monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(run_root))
        from app.infrastructure.paths import reset_run_tmp_root_cache

        reset_run_tmp_root_cache()

        from app.application.sessions.session_bundle import build_session_bundle
        from app.contracts.domain.l1_contracts import L1Fact, L1LocationFact
        from app.contracts.domain.l3_contracts import PlanningProgram
        from app.contracts.domain.planning_semantics import (
            FacilityPlanningParameters,
            RoadPlanningParameters,
        )
        from app.contracts.program import PlanningClaim, PlanningClaimSet
        from app.contracts.evidence.source_semantic_contracts import (
            SourceFeatureSemanticDecision,
            SourceSemanticClassificationSnapshot,
        )
        from app.domain.program.semantic_repair import ProgramSemanticRepairResult
        from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
        from app.evidence.identity.source_semantic_runtime import (
            classify_source_semantics,
        )
        from app.evidence.retrieval.evidence_graph import EvidenceGraph
        from app.infrastructure.artifacts.runtime import load_artifact
        from app.infrastructure.context.planning_context_factory import (
            build_planning_context,
        )
        from app.infrastructure.kg.gazetteer import build_gazetteer
        from app.infrastructure.kg.manager import KGManager
        from app.infrastructure.reports.report_store import ReportStore
        from app.workflow.stage_adapter import persist_stage_artifact
        from app.spatial.grounding.village_cluster_mapper import (
            assign_villages_to_clusters,
            build_village_clusters,
            stable_entity_ref,
        )
        from app.workflow.stages.ground import ground_node
        from app.workflow.stages.target_projection import target_projection_node
        from app.domain.program.aggregate import l3_aggregate

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
            def __init__(self, name):
                self.name = name

            def with_structured_output(self, response_model, **_kwargs):
                owner_name = self.name

                class _Structured:
                    async def ainvoke(self, _prompt):
                        quote = "社前村" if owner_name == "社前" else "园寨村"
                        start = report_text.index(quote)
                        return response_model(decisions=[{
                            "entity_ref": stable_entity_ref("village", owner_name),
                            "status": "mapped",
                            "candidate_ids": [clusters[min(1, len(clusters) - 1)].cluster_id],
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
            llm=_VillageBindingLLM("社前"),
        ):
            gazetteer.upsert(entry)
        for entry in await assign_villages_to_clusters(
            gazetteer,
            parcels,
            ["园寨"],
            report_text,
            llm=_VillageBindingLLM("园寨"),
        ):
            gazetteer.upsert(entry)

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
            ),
            L1LocationFact(
                mention="园寨",
                normalized_name="园寨",
                role="village",
                aliases=["园寨"],
                spatial_hint="园寨",
                source_span="自然村 | 园寨 | 园寨自然村",
                source_report_ref="report:current",
                dimension_key="socio_economic",
                confidence=0.95,
            ),
        ]
        shrine_features = []
        for feature in list(
            (getattr(context.workspace, "points", {}) or {}).get(
                "annotations_current"
            ) or []
        ):
            raw = getattr(feature, "_raw", {}) or {}
            source_feature_id = str(raw.get("source_feature_id") or "").strip()
            if not source_feature_id or str(getattr(feature, "text", "") or "").strip() != "祠":
                continue
            shrine_features.append(feature)
        assert shrine_features
        road_features = []
        for feature in list(
            (getattr(context.workspace, "lines", {}) or {}).get(
                "roads_current"
            ) or []
        ):
            raw = getattr(feature, "_raw", {}) or {}
            source_feature_id = str(raw.get("source_feature_id") or "").strip()
            geometry = getattr(feature, "geometry", {}) or {}
            if (
                source_feature_id
                and isinstance(geometry, dict)
                and geometry.get("type") in {"LineString", "MultiLineString"}
            ):
                road_features.append(feature)
        assert road_features
        target_road_feature = road_features[:1]
        target_road_source_id = str(
            (getattr(target_road_feature[0], "_raw", {}) or {}).get(
                "source_feature_id"
            )
            or ""
        ).strip()
        assert target_road_source_id
        use_real_source_semantic = os.getenv(
            "RUN_REAL_L3_SOURCE_SEMANTIC", ""
        ).strip().lower() in {"1", "true", "yes", "on"}
        shrine_fact_id = (
            "l1:fact:real-shrine"
            if use_real_source_semantic
            else "l1:fact:sim-shrine"
        )
        source_semantic_snapshot = None
        if use_real_source_semantic:
            from app.core.settings import MINIMAX_API_KEY

            if not MINIMAX_API_KEY:
                pytest.skip("RUN_REAL_L3_SOURCE_SEMANTIC requires MINIMAX_API_KEY")
            target_shrine_features = shrine_features[:1]
            context.l1_fact_records = [
                L1Fact(
                    fact_id="l1:fact:real-shrine",
                    statement="社前村有祠堂设施",
                    fact_kind="document_observation",
                    semantic_type="facility",
                    attributes={"normalized_name": "祠堂"},
                    value=1,
                    unit="处",
                        source_refs=["report:current"],
                        source_snapshot_ref=str(
                            getattr(context, "l1_snapshot_ref", "")
                            or "snapshot:current"
                        ),
                        source_feature_ids=[
                            str((getattr(feature, "_raw", {}) or {}).get("source_feature_id"))
                            for feature in target_shrine_features
                            if str((getattr(feature, "_raw", {}) or {}).get("source_feature_id") or "").strip()
                        ],
                    )
            ]
            snapshot, source_semantic_decisions, diagnostics = await classify_source_semantics(
                context,
                enabled=True,
                source_features={"facility": target_shrine_features, "road": []},
            )
            assert snapshot is not None
            assert diagnostics == []
            assert set(source_semantic_decisions) == {
                str((getattr(target_shrine_features[0], "_raw", {}) or {}).get("source_feature_id"))
            }
            assert all(
                decision.status == "accepted"
                and decision.semantic_type == "祠堂"
                and len(decision.proposal_digests) == 2
                for decision in source_semantic_decisions.values()
            )
            source_semantic_snapshot = snapshot
        else:
            road_fact_id = "l1:fact:sim-road-one"
            source_semantic_decisions = {}
            for feature in shrine_features:
                raw = getattr(feature, "_raw", {}) or {}
                source_feature_id = str(raw.get("source_feature_id") or "").strip()
                source_semantic_decisions[source_feature_id] = SourceFeatureSemanticDecision(
                    source_feature_id=source_feature_id,
                    raw_label="祠",
                    semantic_type="祠堂",
                    status="accepted",
                        authority="inferred_current",
                        candidate_ref=f"l1:{shrine_fact_id}:entity",
                        supporting_fact_refs=[shrine_fact_id],
                )
            source_semantic_decisions[target_road_source_id] = SourceFeatureSemanticDecision(
                source_feature_id=target_road_source_id,
                raw_label="",
                semantic_type="村道",
                status="accepted",
                authority="inferred_current",
                candidate_ref=f"{road_fact_id}:entity",
                supporting_fact_refs=[road_fact_id],
            )
            context.l1_fact_records = [
                L1Fact(
                    fact_id=shrine_fact_id,
                    statement="金田村下属社前村有祠堂设施",
                    fact_kind="document_observation",
                    dimension_key="historical_culture",
                    semantic_type="facility",
                    attributes={
                        "normalized_name": "祠堂",
                        "role": "facility",
                        "location": "社前村",
                    },
                    value=3,
                    unit="处",
                    source_refs=["report:current"],
                    source_snapshot_ref=str(
                        getattr(context.data_snapshot, "snapshot_id", "")
                        or "snapshot:simulated"
                    ),
                    source_feature_ids=[
                        str((getattr(feature, "_raw", {}) or {}).get("source_feature_id"))
                        for feature in shrine_features
                        if str((getattr(feature, "_raw", {}) or {}).get("source_feature_id") or "").strip()
                    ],
                ),
                L1Fact(
                    fact_id=road_fact_id,
                    statement="金田村现状有一条需要提升的村道",
                    fact_kind="document_observation",
                    dimension_key="traffic",
                    semantic_type="road",
                    attributes={
                        "normalized_name": "村道",
                        "role": "road",
                        "location": "金田村",
                    },
                    source_refs=["report:traffic"],
                    source_feature_ids=[target_road_source_id],
                    source_snapshot_ref=str(
                        getattr(context.data_snapshot, "snapshot_id", "")
                        or "snapshot:simulated"
                    ),
                )
            ]
            context.source_semantic_decisions = source_semantic_decisions
            context.evidence_graph = EvidenceGraph(
                context,
                index=PlaceEvidenceIndex.build(context),
            )
            source_semantic_snapshot = SourceSemanticClassificationSnapshot(
                source_snapshot_ref=str(
                    getattr(context.data_snapshot, "snapshot_id", "")
                    or "snapshot:simulated"
                ),
                source_snapshot_digest=str(context.data_snapshot.digest),
                l1_fact_fingerprint="l1-fingerprint:simulated-road",
                vocabulary_fingerprint="vocabulary-fingerprint:simulated-road",
                prompt_version="simulated-source-semantic-v1",
                model_id="simulated-minimax",
                fingerprint="source-semantic-fingerprint:simulated-road",
                decisions=list(source_semantic_decisions.values()),
            )
        assert context.evidence_graph is not None
        scoped = context.evidence_graph.query_facility_bsms("社前村", "祠堂")
        assert scoped.status == "resolved", scoped
        assert scoped.candidates[0].feature_bsm or scoped.candidates[0].source_bsm

        claim_set = PlanningClaimSet(
            dimension_key="historical_culture",
            claims=[
                    PlanningClaim(
                        claim_id="simulated-祠堂-maintenance",
                        dimension_key="historical_culture",
                        statement="社前村现状祠堂需要保留并作为公共文化设施维护。",
                        planning_role="spatial_intervention",
                        project_package_ref="simulated:historical_culture:祠堂",
                        suggested_category="facility",
                    suggested_output_kind="point",
                    asset_kind="facility",
                    suggested_interventions=["祠堂维护"],
                    intervention_action="preserve",
                    location_hints=["社前村", "祠堂"],
                        evidence_refs=["report:current", shrine_fact_id],
                        source_fact_refs=[shrine_fact_id],
                    facility_parameters=FacilityPlanningParameters(
                        facility_type="祠堂",
                        action="preserve",
                    ),
                ),
            ],
        )
        if not use_real_source_semantic:
            claim_set.claims.append(
                    PlanningClaim(
                        claim_id="simulated-road-upgrade-from-l1-fact",
                        dimension_key="historical_culture",
                        statement="金田村现状村道需要提升。",
                        planning_role="spatial_intervention",
                        project_package_ref="simulated:historical_culture:village-road",
                        suggested_category="road",
                    suggested_output_kind="line",
                    asset_kind="road",
                    suggested_interventions=["村道提升"],
                    intervention_action="upgrade",
                    evidence_refs=["report:traffic"],
                    source_fact_refs=["l1:fact:sim-road-one"],
                    road_parameters=RoadPlanningParameters(
                        action="upgrade",
                        length_m=100,
                    ),
                )
            )

        store = ReportStore.get_instance()

        async def fake_reports(_session_id, *, layer):
            assert layer == 3
            return {
                "historical_culture": {
                    "instruction": claim_set.model_dump_json(),
                    "report_id": "report:simulated-l3:historical_culture",
                }
            }

        async def no_provider_repair(program, **_kwargs):
            return ProgramSemanticRepairResult(program=program, applied=False)

        monkeypatch.setattr(store, "get_layer_reports_with_sources", fake_reports)
        monkeypatch.setattr(
            "app.domain.program.semantic_repair.repair_planning_program",
            no_provider_repair,
        )

        state = {
            "session_id": sid,
            "run_id": sid,
            "branch_id": "main",
            "config": {
                "village_name": "金田村",
                "source_semantic_llm_enabled": False,
            },
            "artifact_refs": {},
            "retry_counts": {},
            "context_version": str(context.version),
            "context_ref": {
                "session_id": sid,
                "version": str(context.version),
                "snapshot_digest": str(context.data_snapshot.digest),
            },
        }

        aggregate_output = await l3_aggregate(state, base_dir=str(run_root))
        state["artifact_refs"].update(aggregate_output["artifact_refs"])
        state["artifact_refs"]["source_semantic_classification"] = persist_stage_artifact(
            state,
            "target_projection",
            "SourceSemanticClassificationSnapshot",
            source_semantic_snapshot,
        )
        program = load_artifact(state, "planning_program", PlanningProgram)
        assert len(program.interventions) == (1 if use_real_source_semantic else 2)

        async def run_stage(node, current):
            before = dict(current.get("artifact_refs") or {})
            patch = await node(current)
            merged = dict(current)
            merged.update(patch)
            merged["artifact_refs"] = {
                **before,
                **dict(patch.get("artifact_refs") or {}),
            }
            return merged

        state = await run_stage(target_projection_node, state)
        projection = load_artifact(state, "target_projection")
        assert projection["compilation_status"] == "validated", json.dumps(
            projection, ensure_ascii=False
        )
        shrine_spec = next(
            (
                item
                for item in projection["spatial_reference_specs"]
                if "祠堂" in json.dumps(item, ensure_ascii=False)
            ),
            None,
        )
        assert shrine_spec, json.dumps(
            {
                "specs": projection["spatial_reference_specs"],
                "program_interventions": [
                    item.model_dump(mode="json")
                    for item in program.interventions
                ],
                "diagnostics": projection.get("diagnostics", []),
            },
            ensure_ascii=False,
        )
        shrine_json = json.dumps(shrine_spec, ensure_ascii=False)
        assert "祠堂" in shrine_json
        if shrine_spec["type"] == "directional":
            shrine_filter = (shrine_spec.get("reference") or {}).get("filter") or {}
            assert shrine_filter["rdf_type"] == "Facility"
            assert shrine_filter["source_feature_ids"]
            assert shrine_spec["source_binding_ref"]
            assert shrine_spec["l1_fact_refs"] == [shrine_fact_id]
        else:
            assert shrine_spec["type"] == "composed"
            assert shrine_spec["op"] == "and"
            assert "社前村" in shrine_json
        if not use_real_source_semantic:
            road_spec = next(
                item
                for item in projection["spatial_reference_specs"]
                if target_road_source_id in json.dumps(item, ensure_ascii=False)
            )
            assert road_spec["reference"]["filter"]["source_feature_ids"] == [
                target_road_source_id
            ]
            assert road_spec["source_binding_ref"]
            assert road_spec["source_collection_key"] == "current_road"
            assert road_spec["source_snapshot_ref"]
            assert road_spec["source_feature_digest"]
        assert state["target_projection_gate"]["passed"] is True

        state = await run_stage(ground_node, state)
        grounding = load_artifact(state, "grounding_result")
        assert grounding["candidates"], json.dumps(grounding, ensure_ascii=False)
        assert not grounding["unresolved"], json.dumps(
            grounding, ensure_ascii=False
        )
        candidate = next(
            item
            for item in grounding["candidates"]
            if (
                item.get("geometry", {}).get("source_feature_ids")
                or item.get("geometry", {}).get("source_bsms")
            )
        )
        assert (
            candidate["geometry"].get("source_feature_ids")
            or candidate["geometry"].get("source_bsms")
        ), json.dumps(
            candidate, ensure_ascii=False
        )
        assert candidate["geometry"]["source_refs"], json.dumps(
            candidate, ensure_ascii=False
        )
        if not use_real_source_semantic:
            road_candidates = [
                item
                for item in grounding["candidates"]
                if item.get("target_kind") == "road"
                and target_road_source_id in json.dumps(item, ensure_ascii=False)
            ]
            assert len(road_candidates) == 1, json.dumps(
                grounding, ensure_ascii=False
            )
            road_geometry = road_candidates[0]["geometry"]
            assert road_geometry["kind"] == "line", json.dumps(
                road_geometry, ensure_ascii=False
            )
            assert road_geometry["role"] == "execution_geometry", json.dumps(
                road_geometry, ensure_ascii=False
            )
            assert road_geometry["granularity"] == "exact_feature", json.dumps(
                road_geometry, ensure_ascii=False
            )
            assert road_geometry["wkt"]
            assert road_geometry["source_feature_ids"] == [target_road_source_id]
            assert road_geometry["l1_fact_refs"] == ["l1:fact:sim-road-one"]
            assert road_geometry["source_binding_ref"]
        assert state["ground_gate"]["passed"] is True

        # SELECT must stop at the typed readiness boundary here.  This
        # fixture intentionally has no authoritative network snapshot or
        # source-identity binding for every candidate, so continuing to
        # EXECUTE would fabricate execution authority.
        from app.workflow.stages.select import select_node

        state = await run_stage(select_node, state)
        select_gate = state.get("select_gate") or {}
        select_route = (
            select_gate.get("feedback_route")
            if isinstance(select_gate, dict)
            else getattr(select_gate, "feedback_route", None)
        )
        assert select_route == "HUMAN", select_gate
        assert not state["artifact_refs"].get("planning_scenario")
        issue_fingerprint = (
            select_gate.get("issue_fingerprint")
            if isinstance(select_gate, dict)
            else getattr(select_gate, "issue_fingerprint", "")
        )
        assert "solver_readiness:blocked" in str(issue_fingerprint)
    finally:
        await teardown()
