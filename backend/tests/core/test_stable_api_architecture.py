"""Static boundaries that keep frontend contracts independent of workflow internals."""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi import FastAPI

from app.agent.plan_state.state import AgentState
from app.api.routes import router as api_router


ROOT = Path(__file__).resolve().parents[2] / 'app'


def test_legacy_frontend_read_routes_are_removed() -> None:
    app = FastAPI()
    app.include_router(api_router)
    paths = set(app.openapi()['paths'])
    assert '/api/v1/sessions' in paths
    assert '/api/sessions/{session_id}/stream' not in paths
    assert '/api/sessions/{session_id}/sync' not in paths
    assert '/api/sessions/{session_id}/status' not in paths
    assert '/api/sessions/{session_id}/render-layers' not in paths
    assert '/api/human-review/{session_id}' not in paths


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding='utf-8'))
    result: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            result.add(node.module)
    return result


def test_stable_api_does_not_import_agent_business_models_or_renderers() -> None:
    imports = _imports(ROOT / 'api/v1/routes.py')
    forbidden = {
        'app.agent.deliver.render_layers',
        'app.modules.schema.contracts.planned_state_contracts',
        'app.modules.spatial_ops.output.export_package',
    }
    assert imports.isdisjoint(forbidden)


def test_map_projection_names_delivery_snapshot_as_its_only_spatial_artifact() -> None:
    source = (ROOT / 'api/v1/routes.py').read_text(encoding='utf-8')
    map_section = source[source.index("@router.get('/sessions/{session_id}/map-layers'"):]
    map_section = map_section[:map_section.index("@router.get('/sessions/{session_id}/human-review'")]
    assert "'DeliverySpatialSnapshot'" in map_section
    assert "'PlannedState'" not in map_section
    assert 'allocated_geojson' not in map_section
    assert 'gis_data' not in map_section


def test_public_contracts_do_not_expose_internal_state_fields() -> None:
    source = (ROOT / 'api/v1/contracts.py').read_text(encoding='utf-8')
    for field in ('allocated_geojson', 'gis_data', 'layout_configs', 'render_artifacts'):
        assert field not in source


def test_delivery_land_balance_prefers_exported_snapshot_view() -> None:
    source = (ROOT / 'agent/deliver/aggregate.py').read_text(encoding='utf-8')
    exported = source.index('exported_planned = _planned_view_from_export(export_result)')
    gate = source.index('check_delivery_gate(', exported)

    assert exported < gate
    assert '_build_planned_view(current_parcels, planned_state)' not in source[exported:gate]
    assert 'planned_parcels=planned_for_balance' in source[gate:]


def test_parent_agent_state_no_longer_duplicates_stage_payloads() -> None:
    fields = set(AgentState.__annotations__)
    assert fields.isdisjoint({
        'specs', 'land_design_briefs', 'layout_configs', 'action_results',
        'export_result', 'render_artifacts', 'execution_errors',
        'l4_write_result', 'execution_outcome_target_coverage',
    })
