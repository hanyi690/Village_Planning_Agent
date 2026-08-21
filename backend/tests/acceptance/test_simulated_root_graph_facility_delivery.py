"""Quota-free root-graph acceptance for a semantically bound facility point."""

from __future__ import annotations

import json
import uuid

import pytest

from tests.acceptance.test_complete_execution_render import _uploads
from tests.fixtures.db import make_session_with_uploads
from tests.support.simulated_planning_llm import SimulatedPlanningProvider


@pytest.mark.asyncio
@pytest.mark.timeout(900)
@pytest.mark.e2e
async def test_simulated_root_graph_reaches_facility_point_delivery(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path
):
    """Run the production root graph for a Point source-semantic target.

    The fixture annotations use the short raw label ``祠`` while the L1 fact
    says ``祠堂``.  The simulated provider is therefore required for the
    source-semantic closed-set decision; it cannot be replaced by an exact
    string match or by a synthetic coordinate.
    """

    setup, teardown = sqlite_db
    await setup()
    session_id = 'sim-root-facility-' + uuid.uuid4().hex[:8]
    run_root = tmp_path / 'simulated-root-facility-run'
    monkeypatch.setenv('BACKEND_RUN_TMP_DIR', str(run_root))
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()
    try:
        await make_session_with_uploads(session_id, '金田村', uploads=_uploads())

        from app.infrastructure.context.planning_context_factory import get_cached_context
        from app.infrastructure.llm import planning_claims
        from app.infrastructure.llm import structured
        from app.evidence.identity import flash_source_semantic_classifier as source_classifier
        from app.domain.objectives import worker as l2_worker
        from app.domain.program import worker as l3_worker
        from app.infrastructure.llm.planning_claims import PlanningClaimGenerator

        async def current_fact_id() -> str:
            context = get_cached_context(session_id)
            facts = list(getattr(context, 'l1_fact_records', []) or []) if context else []
            for item in facts:
                semantic_type = str(getattr(item, 'semantic_type', '') or '').casefold()
                statement = str(getattr(item, 'statement', '') or '')
                attributes = getattr(item, 'attributes', {}) or {}
                normalized_name = str(attributes.get('normalized_name', '') or '')
                if (
                    semantic_type in {'facility', '设施', '现状设施'}
                    or '祠堂' in statement
                    or '祠堂' in normalized_name
                ):
                    return str(getattr(item, 'fact_id', '') or '')

            from app.data.ingestion.compiler.core import compile_dimension_report
            from app.contracts.workflow.parsing_contracts import CompilationProfile
            from app.infrastructure.reports.report_store import ReportStore

            reports = await ReportStore.get_instance().get_layer_reports_with_sources(
                session_id, layer=1
            )
            public_services = reports.get('public_services') or {}
            snapshot = compile_dimension_report(
                CompilationProfile.L1_OBSERVATION,
                dimension_key='public_services',
                content=str(public_services.get('content') or ''),
                instruction=str(public_services.get('instruction') or ''),
                summary=str(public_services.get('summary') or ''),
                report_id=str(public_services.get('report_id') or ''),
                run_id=session_id,
            )
            for item in list(getattr(snapshot, 'fact_records', []) or []):
                statement = str(getattr(item, 'statement', '') or '')
                if '祠堂' in statement:
                    return str(getattr(item, 'fact_id', '') or '')
            from app.domain.assessment.l1_fact_projection import location_fact_to_l1_fact

            for item in list(getattr(snapshot, 'location_facts', []) or []):
                if '祠堂' in str(getattr(item, 'normalized_name', '') or ''):
                    projected = location_fact_to_l1_fact(item)
                    return str(getattr(projected, 'fact_id', '') or '')
            return ''

        provider = SimulatedPlanningProvider(
            fact_id=current_fact_id,
            facility_mode=True,
            # Annotation ordinal 4 is a real ``祠`` Point in the JinTian fixture.
            semantic_source_marker='/4/',
        )
        monkeypatch.setattr(structured, 'run_structured_output', provider.structured_output)
        monkeypatch.setattr(planning_claims, 'run_structured_output', provider.structured_output)
        monkeypatch.setattr(source_classifier, 'run_structured_output', provider.structured_output)
        monkeypatch.setattr(l2_worker, '_get_llm', lambda: provider)
        monkeypatch.setattr(PlanningClaimGenerator, '_get_llm', lambda _self: provider)

        from app.evidence.identity.flash_source_semantic_classifier import SourceSemanticClassifier

        monkeypatch.setattr(
            source_classifier,
            'create_minimax_source_semantic_classifier',
            lambda: SourceSemanticClassifier(llm=provider, model_id='simulated-minimax'),
        )

        from app.workflow.plan_state.state_factory import StateFactory
        from app.workflow.root_graph import create_unified_planning_graph
        from langchain_core.messages import AIMessage
        from langgraph.checkpoint.memory import MemorySaver
        from langgraph.types import Command

        initial_state = StateFactory.create(
            session_id=session_id,
            project_name='金田村模拟 root graph 设施点验收',
            village_name='金田村',
            rag_enabled=False,
            rag_layer_config={1: False, 2: False, 3: False},
            step_mode=False,
        )
        initial_state['run_id'] = session_id
        initial_state['phase'] = 'layer1'
        initial_state['runtime']['config']['source_semantic_llm_enabled'] = True
        initial_state['messages'] = [AIMessage(
            content='',
            tool_calls=[{
                'name': 'advance_planning_intent',
                'id': 'simulated-root-facility-intent',
                'args': {'reason': 'simulated root facility acceptance'},
            }],
        )]

        graph = create_unified_planning_graph(MemorySaver())
        config = {
            'configurable': {'thread_id': session_id},
            'recursion_limit': 600,
            'max_concurrency': 8,
        }

        values = await graph.ainvoke(initial_state, config)
        for _ in range(30):
            snapshot = await graph.aget_state(config)
            tasks = list(getattr(snapshot, 'tasks', ()) or ()) if snapshot else []
            interrupts = [
                item
                for task in tasks
                for item in (getattr(task, 'interrupts', ()) or ())
            ]
            if not interrupts:
                values = dict(getattr(snapshot, 'values', None) or values or {})
                if values.get('delivery_status') or values.get('diagnostic_terminal'):
                    break
                if not tasks:
                    break
                values = await graph.ainvoke(None, config)
                continue
            values = await graph.ainvoke(
                Command(resume={'action': 'approve', 'decision': 'approve'}),
                config,
            )
        else:
            raise AssertionError('simulated facility graph did not reach terminal delivery')

        final = dict((await graph.aget_state(config)).values or values or {})
        from app.infrastructure.artifacts.runtime import load_artifact

        debug_artifacts = {}
        for debug_key in ('execution_diagnostics', 'execution_result', 'delivery_manifest'):
            try:
                debug_artifacts[debug_key] = load_artifact(final, debug_key)
            except Exception as exc:  # pragma: no cover - assertion diagnostics
                debug_artifacts[debug_key] = f'{type(exc).__name__}: {exc}'
        assert final.get('delivery_status') in {'complete', 'partial'}, (
            f"terminal={final.get('diagnostic_terminal')!r}; "
            f"diagnostics={final.get('diagnostics')!r}; calls={provider.calls!r}; "
            f"gates={{key: final.get(key) for key in ('l1_gate', 'l3_gate', 'target_projection_gate', 'ground_gate', 'select_gate', 'deliver_gate')}}; "
            f"fatal={final.get('fatal_error')!r}; debug_artifacts={debug_artifacts!r}"
        )
        assert final.get('diagnostic_terminal') in (None, {})

        refs = dict(final.get('artifact_refs') or {})
        for key in (
            'l1_snapshot', 'l2_strategy', 'planning_program',
            'target_projection', 'grounding_result', 'site_selection',
            'execution_plan', 'planned_state', 'delivery_manifest',
        ):
            assert refs.get(key), f'missing root artifact: {key}'

        from app.contracts.workflow.execution_plan_contracts import ExecutionPlan
        from app.contracts.workflow.parse_result_contracts import IntentCompilationResult
        from app.contracts.evidence.source_semantic_contracts import SourceSemanticClassificationSnapshot

        projection = load_artifact(final, 'target_projection', IntentCompilationResult)
        semantic_snapshot = load_artifact(
            final,
            'source_semantic_classification',
            SourceSemanticClassificationSnapshot,
        )
        assert any(
            str(getattr(item, 'raw_label', '') or '') == '祠'
            and str(getattr(item, 'status', '') or '') == 'accepted'
            and str(getattr(item, 'semantic_type', '') or '') == '祠堂'
            for item in (getattr(semantic_snapshot, 'decisions', []) or [])
        )
        assert any(
            str(getattr(spec, 'target_id', '') or '').endswith('sim-facility-hall')
            and str(getattr(spec, 'source_collection_key', '') or '') == 'current_facility'
            for spec in projection.spatial_reference_specs
        ), f'calls={provider.calls}; specs=' + json.dumps(
            [
                item.model_dump(mode='json') if hasattr(item, 'model_dump') else str(item)
                for item in projection.spatial_reference_specs
            ],
            ensure_ascii=False,
        )

        execution_plan = load_artifact(final, 'execution_plan', ExecutionPlan)
        facility_tasks = [
            task for task in (getattr(execution_plan, 'worker_tasks', []) or [])
            if 'facility' in str(getattr(task, 'worker_type', '') or '').casefold()
        ]
        assert facility_tasks, 'FACILITY EXECUTE worker received no point task'
        assert all(getattr(task, 'expected_output_kind', '') == 'point' for task in facility_tasks)

        from app.contracts.spatial.planned_state_contracts import PlannedState

        planned = load_artifact(final, 'planned_state', PlannedState)
        planned_facilities = list(getattr(planned, 'facilities', []) or [])
        assert planned_facilities, 'FACILITY EXECUTE produced no planned facility point'
        assert all(getattr(item, 'geometry', '') for item in planned_facilities)
        assert all(
            getattr(item, 'source_feature_ids', []) or getattr(item, 'candidate_id', '')
            for item in planned_facilities
        )

        from app.api.v1.contracts import MapLayerCollection
        from app.api.v1.routes.map_layers import get_map_layers
        from app.application.queries.artifacts import ArtifactRead

        async def fake_workflow_state(_session_id):
            return {'session_id': _session_id}

        async def fake_artifact_read(_session_id, key):
            payload = load_artifact(final, key)
            if payload is None:
                return None
            if hasattr(payload, 'model_dump'):
                payload = payload.model_dump(mode='json')
            return ArtifactRead(
                session_id=_session_id,
                artifact_key=key,
                artifact_ref=dict(refs.get(key) or {}),
                payload=payload,
            )

        monkeypatch.setattr(
            'app.application.projections.delivery.load_workflow_state',
            fake_workflow_state,
        )
        monkeypatch.setattr(
            'app.application.projections.delivery.artifact_queries.read',
            fake_artifact_read,
        )
        map_response = await get_map_layers(session_id)
        map_payload = MapLayerCollection.model_validate(
            map_response.model_dump(mode='python')
        )
        map_layer_types = {layer.layer_name for layer in map_payload.layers}
        assert 'facility_point' in map_layer_types, map_layer_types
        facility_layer = next(
            layer for layer in map_payload.layers if layer.layer_name == 'facility_point'
        )
        assert facility_layer.geojson.get('features')
        assert all(
            feature.get('geometry', {}).get('type') == 'Point'
            for feature in facility_layer.geojson.get('features') or []
        )

        # The public evidence boundary is intentionally project-wide when no
        # layer/entity scope is supplied.  After this root graph has produced
        # durable L1 and report artifacts, one query must expose the complete
        # relevant source set for the planning LLM: report background, typed
        # L1 localization, KG relations, uploaded text, and Bundle geometry.
        from app.api.v1.contracts import EvidenceQueryRequest
        from app.api.v1.routes.evidence import query_session_evidence

        evidence_response = await query_session_evidence(
            session_id,
            EvidenceQueryRequest(
                query='金田村社前村祠堂的BSM',
                village_name='金田村',
                request_type='spatial_lookup',
            ),
        )
        evidence_payload = evidence_response.model_dump(mode='json')
        evidence_packet = evidence_payload['evidence_packet']
        evidence_bundle = evidence_payload['evidence_bundle']
        source_types = {
            str(source.get('source_type') or '')
            for source in evidence_bundle['sources']
        }
        assert {
            'report',
            'l1',
            'kg',
            'local_text',
            'gis_layer',
        }.issubset(source_types), evidence_bundle['sources']
        fact_types = {
            str(fact.get('fact_type') or '')
            for fact in evidence_bundle['facts']
        }
        assert {
            'l1_fact',
            'planning_text',
            'bundle_feature_identity',
        }.issubset(fact_types), evidence_bundle['facts']
        assert evidence_packet['candidate_refs'], evidence_packet
        assert evidence_packet['l1_snapshot_ref']
        assert any(
            trace.get('step') == 'semantic_candidate_scope'
            and trace.get('project_wide') is True
            and trace.get('source_coverage') == 'project_wide'
            for trace in evidence_packet['query_trace']
        ), evidence_packet['query_trace']

        before_resume_calls = dict(provider.calls)
        await graph.ainvoke(None, config)
        assert provider.calls == before_resume_calls
        assert provider.calls.get('L1:public_services', 0) >= 1
        assert provider.calls.get('L3:public_service', 0) == 1
        assert provider.calls.get('fact_ref:present', 0) >= 1
    finally:
        await teardown()
