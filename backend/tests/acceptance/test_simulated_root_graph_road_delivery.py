"""Quota-free root-graph acceptance using the real JinTian bundle."""

from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from tests.acceptance.test_upload_fixtures import _uploads
from tests.fixtures.db import make_session_with_uploads
from tests.support.simulated_planning_llm import SimulatedPlanningProvider


@pytest.mark.asyncio
@pytest.mark.timeout(900)
@pytest.mark.e2e
async def test_simulated_root_graph_reaches_road_line_and_transport_landuse(
    sqlite_db, pipeline_reset, monkeypatch, tmp_path
):
    """Run the actual root graph with simulated model responses only.

    The graph, bundle, KG, evidence hydration, target projection, GROUND,
    SELECT, the EXECUTE worker registry and road worker remain production code.
    The simulated provider is injected only at the three model contracts, so a
    successful test proves the design is executable without spending quota.
    """

    setup, teardown = sqlite_db
    await setup()
    session_id = 'sim-root-road-' + uuid.uuid4().hex[:8]
    run_root = tmp_path / 'simulated-root-run'
    monkeypatch.setenv('BACKEND_RUN_TMP_DIR', str(run_root))
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()
    try:
        await make_session_with_uploads(session_id, '金田村', uploads=_uploads())

        from app.infrastructure.context.planning_context_factory import get_cached_context
        from app.infrastructure.llm import planning_claims
        from app.infrastructure.llm import structured
        from app.evidence.identity import flash_source_semantic_classifier as source_classifier
        from app.domain.program import worker as l3_worker
        from app.infrastructure.llm.planning_claims import PlanningClaimGenerator

        async def current_fact_id(kind: str = 'road') -> str:
            context = get_cached_context(session_id)
            facts = list(getattr(context, 'l1_fact_records', []) or []) if context else []
            if kind == 'facility':
                matching_facts = [
                    item for item in facts
                    if (
                        str(getattr(item, 'semantic_type', '') or '').casefold()
                        in {'facility', '设施', '现状设施'}
                        or '祠堂' in str(getattr(item, 'statement', '') or '')
                        or '祠堂' in str(
                            (getattr(item, 'attributes', {}) or {}).get(
                                'normalized_name', ''
                            )
                        )
                    )
                ]
                report_key = 'public_services'
                phrase = '祠堂'
            else:
                matching_facts = [
                    item for item in facts
                    if (
                        str(getattr(item, 'semantic_type', '') or '').lower()
                        in {'road', '道路'}
                        or '村道' in str(getattr(item, 'statement', '') or '')
                        or '村道' in str(
                            (getattr(item, 'attributes', {}) or {}).get(
                                'normalized_name', ''
                            )
                        )
                    )
                ]
                report_key = 'traffic'
                phrase = '村道'
            if matching_facts:
                return str(getattr(matching_facts[0], 'fact_id', '') or '')
            from app.data.ingestion.compiler.core import compile_dimension_report
            from app.contracts.workflow.parsing_contracts import CompilationProfile
            from app.infrastructure.reports.report_store import ReportStore

            reports = await ReportStore.get_instance().get_layer_reports_with_sources(
                session_id, layer=1
            )
            report = reports.get(report_key) or {}
            snapshot = compile_dimension_report(
                CompilationProfile.L1_OBSERVATION,
                dimension_key=report_key,
                content=str(report.get('content') or ''),
                instruction=str(report.get('instruction') or ''),
                summary=str(report.get('summary') or ''),
                report_id=str(report.get('report_id') or ''),
                run_id=session_id,
            )
            for item in list(getattr(snapshot, 'fact_records', []) or []):
                if phrase in str(getattr(item, 'statement', '') or ''):
                    return str(getattr(item, 'fact_id', '') or '')
            from app.domain.assessment.l1_fact_projection import location_fact_to_l1_fact

            for item in list(getattr(snapshot, 'location_facts', []) or []):
                if phrase in str(getattr(item, 'normalized_name', '') or ''):
                    projected = location_fact_to_l1_fact(item)
                    return str(getattr(projected, 'fact_id', '') or '')
            return ''

        provider = SimulatedPlanningProvider(
            fact_id=current_fact_id,
            fact_id_by_kind=current_fact_id,
            facility_mode=True,
            combined_mode=True,
            # Fixture road ordinal 4 has no intersection with the hard
            # constraint polygons after the typed 6m widening buffer.
            semantic_source_marker='/4/',
        )
        monkeypatch.setattr(structured, 'run_structured_output', provider.structured_output)
        monkeypatch.setattr(planning_claims, 'run_structured_output', provider.structured_output)
        monkeypatch.setattr(source_classifier, 'run_structured_output', provider.structured_output)
        monkeypatch.setattr(PlanningClaimGenerator, '_get_llm', lambda _self: provider)

        # The real source-semantic boundary is enabled, but its provider
        # constructor is replaced with the explicit simulated classifier.
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
            project_name='金田村模拟 root graph 道路验收',
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
                'id': 'simulated-root-intent',
                'args': {'reason': 'simulated root acceptance'},
            }],
        )]

        graph = create_unified_planning_graph(MemorySaver())
        config = {
            'configurable': {'thread_id': session_id},
            'recursion_limit': 600,
            'max_concurrency': 8,
        }

        # Official LangGraph resume loop.  Any HUMAN pause is explicitly
        # approved for this quota-free acceptance; no stage is monkeypatched.
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
            raise AssertionError('simulated root graph did not reach a terminal delivery state')

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
            f"diagnostics={final.get('diagnostics')!r}; "
            f"phase={final.get('phase')!r}; calls={provider.calls!r}"
            f"; keys={sorted(final.keys())!r}; refs={final.get('artifact_refs')!r}"
            f"; gates={ {key: final.get(key) for key in ('l1_gate', 'l3_gate', 'target_projection_gate', 'ground_gate', 'select_gate', 'deliver_gate')} }"
            f"; fatal={final.get('fatal_error')!r}; status={final.get('status')!r}; "
            f"active_stage={final.get('active_stage')!r}; paused={final.get('paused_stage')!r}; "
            f"debug_artifacts={debug_artifacts!r}"
        )
        assert final.get('diagnostic_terminal') in (None, {})

        refs = dict(final.get('artifact_refs') or {})
        for key in (
            'l1_snapshot', 'l2_strategy', 'planning_program',
            'target_projection', 'grounding_result', 'scenario_set',
            'execution_plan', 'parcel_changeset', 'planned_state',
            'delivery_manifest', 'delivery_spatial_snapshot', 'render_layers',
            'render_artifacts',
        ):
            assert refs.get(key), f'missing root artifact: {key}'

        from app.contracts.spatial.parcel_change_contracts import ParcelChangeSet
        from app.contracts.spatial.planned_state_contracts import PlannedState
        from app.contracts.workflow.execution_plan_contracts import ExecutionPlan
        from app.contracts.workflow.parse_result_contracts import IntentCompilationResult

        projection = load_artifact(final, 'target_projection', IntentCompilationResult)
        assert projection.spatial_reference_specs
        road_spec = next(
            (
                spec for spec in projection.spatial_reference_specs
                if str(getattr(spec, 'source_collection_key', '') or '') == 'current_road'
            ),
            None,
        )
        assert road_spec is not None, f'calls={provider.calls}; specs=' + json.dumps(
            [
                item.model_dump(mode='json') if hasattr(item, 'model_dump') else str(item)
                for item in projection.spatial_reference_specs
            ],
            ensure_ascii=False,
        )
        road_target_id = str(getattr(road_spec, 'target_id', '') or '')

        execution_plan = load_artifact(final, 'execution_plan', ExecutionPlan)
        road_tasks = [
            task for task in (getattr(execution_plan, 'worker_tasks', []) or [])
            if str(getattr(task, 'worker_type', '') or '') == 'road_construction'
            or str(getattr(task, 'target_type', '') or '') == 'road'
        ]
        assert road_tasks, 'ROAD EXECUTE worker received no line task'
        assert all(getattr(task, 'expected_output_kind', '') == 'line' for task in road_tasks)

        changeset = load_artifact(final, 'parcel_changeset', ParcelChangeSet)
        road_changes = [
            item for item in (getattr(changeset, 'changes', []) or [])
            if (
                getattr(getattr(item, 'after_classification', None), 'code', '') == '1006'
            )
        ]
        assert road_changes, 'widened road produced no transportation land-use parcel change'
        assert all(getattr(item, 'after_geometry_wkt', '') for item in road_changes)

        planned = load_artifact(final, 'planned_state', PlannedState)
        assert any(
            getattr(road, 'geometry', '')
            and str(getattr(road, 'derived_from_target', '') or '') == road_target_id
            for road in (getattr(planned, 'roads', []) or [])
        ), 'ROAD EXECUTE produced no planned linear geometry'
        assert any(
            str(getattr(item, 'planning_land_use', '') or '')
            and str(getattr(item, 'planning_land_use', '') or '') == '1006'
            for item in (getattr(planned, 'parcels', []) or [])
        )
        planned_facilities = list(getattr(planned, 'facilities', []) or [])
        assert planned_facilities, (
            'combined EXECUTE produced no planned facility point; '
            f'calls={provider.calls!r}'
        )
        assert all(getattr(item, 'geometry', '') for item in planned_facilities)
        assert all(
            getattr(item, 'source_feature_ids', []) or getattr(item, 'candidate_id', '')
            for item in planned_facilities
        )

        render_artifacts = load_artifact(final, 'render_artifacts')
        static_preview = dict((render_artifacts or {}).get('static_preview') or {})
        assert static_preview.get('status') == 'completed', render_artifacts
        assert int(static_preview.get('planned_road_count') or 0) >= 1
        assert int(static_preview.get('planned_point_count') or 0) >= 1
        combined_preview = Path(__file__).parents[2] / 'output' / 'execution_result_combined.png'
        combined_preview.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(static_preview['path']), combined_preview)

        # Read the same immutable delivery artifacts through the stable
        # frontend projection.  This proves that the line and the parcel
        # change survive the DELIVER read boundary, not only the worker merge.
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
        assert 'planned_road' in map_layer_types, map_layer_types
        assert 'facility_point' in map_layer_types, map_layer_types
        planned_landuse = next(
            layer for layer in map_payload.layers
            if layer.layer_name == 'complete_planned_landuse'
        )
        assert any(
            str(
                (feature.get('properties') or {}).get('planning_code')
                or (feature.get('properties') or {}).get('planning_land_use')
                or ''
            ) == '1006'
            for feature in (planned_landuse.geojson.get('features') or [])
        )

        before_resume_calls = dict(provider.calls)
        # A second resume/invoke against the terminal checkpoint must not
        # regenerate any model output or mutate the immutable artifact set.
        await graph.ainvoke(None, config)
        after_resume_calls = dict(provider.calls)
        assert after_resume_calls == before_resume_calls

        assert provider.calls.get('L1:traffic', 0) >= 1
        assert provider.calls.get('L2:resource_endowment', 0) == 1
        # L3 is intentionally split into claims and report projections.
        assert provider.calls.get('L3:traffic_planning', 0) == 2
    finally:
        await teardown()
