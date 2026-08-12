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
        'app.domain.delivery.render_layers',
        'app.modules.schema.contracts.planned_state_contracts',
        'app.modules.spatial_ops.output.export_package',
    }
    assert imports.isdisjoint(forbidden)


def test_state_and_human_read_routes_use_application_projection() -> None:
    source = (ROOT / 'api/v1/routes.py').read_text(encoding='utf-8')
    assert 'app.application.queries.workflow_state' in source
    state_section = source[source.index("@router.get('/sessions/{session_id}/state'"):]
    state_section = state_section[:state_section.index("@router.get('/sessions/{session_id}/delivery'")]
    assert 'load_workflow_state(session_id)' in state_section
    assert 'aget_state_values(session_id)' not in state_section


def test_map_projection_names_delivery_snapshot_as_its_only_spatial_artifact() -> None:
    source = (ROOT / 'api/v1/routes.py').read_text(encoding='utf-8')
    map_section = source[source.index("@router.get('/sessions/{session_id}/map-layers'"):]
    map_section = map_section[:map_section.index("@router.get('/sessions/{session_id}/human-review'")]
    delivery_projection = (ROOT / 'application' / 'projections' / 'delivery.py').read_text(encoding='utf-8')
    assert "delivery_spatial_snapshot" in delivery_projection
    assert "delivery_projections.map_layers" in map_section
    assert "'PlannedState'" not in map_section
    assert 'allocated_geojson' not in map_section
    assert 'gis_data' not in map_section


def test_public_contracts_do_not_expose_internal_state_fields() -> None:
    source = (ROOT / 'api/v1/contracts.py').read_text(encoding='utf-8')
    for field in ('allocated_geojson', 'gis_data', 'layout_configs', 'render_artifacts'):
        assert field not in source


def test_delivery_land_balance_prefers_exported_snapshot_view() -> None:
    source = (ROOT / 'domain/delivery/aggregate.py').read_text(encoding='utf-8')
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


def test_gis_tools_receive_bundle_refs_not_raw_gis_state() -> None:
    tool_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ROOT / "tools" / "gis").rglob("*.py")
    )
    assert 'InjectedState("gis_data")' not in tool_sources


def test_legacy_agent_gis_layout_tools_are_removed() -> None:
    assert not (ROOT / "tools" / "gis" / "render.py").exists()
    assert not (ROOT / "tools" / "gis" / "validate.py").exists()
    source = (ROOT / "tools" / "gis" / "__init__.py").read_text(encoding="utf-8")
    assert "layout_configs" not in source


def test_delivery_stage_is_not_embedded_in_main_nodes() -> None:
    delivery_stage = (ROOT / "workflow" / "stages" / "deliver.py").read_text(encoding="utf-8")
    assert "async def deliver_node" in delivery_stage
    assert not (ROOT / "workflow" / "stages" / "main_nodes.py").exists()
    assert "stages.main_nodes" not in delivery_stage


def test_root_graph_does_not_depend_on_stage_private_helpers() -> None:
    source = (ROOT / "workflow" / "root_graph.py").read_text(encoding="utf-8")
    assert "main_nodes._" not in source
    assert "stages.main_nodes" not in source
    assert "app.application.interrupts" in source


def test_stage_routing_policy_lives_in_stage_support() -> None:
    support = (ROOT / "workflow" / "stages" / "support.py").read_text(encoding="utf-8")
    assert "STAGE_FORWARD_TARGET" in support
    assert "GATE_CHANNELS" in support


def test_step_reports_are_owned_by_evidence_module() -> None:
    production_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in ROOT.rglob("*.py")
    )
    assert "app.services.step_report" not in production_sources
    assert "app.services.stage_report" not in production_sources
    assert (ROOT / "modules" / "evidence" / "step_report.py").exists()
    assert (ROOT / "modules" / "evidence" / "stage_report.py").exists()


def test_projection_and_ground_are_independent_stage_services() -> None:
    projection = (ROOT / "workflow" / "stages" / "target_projection.py").read_text(encoding="utf-8")
    ground = (ROOT / "workflow" / "stages" / "ground.py").read_text(encoding="utf-8")
    assert "async def target_projection_node" in projection
    assert "async def ground_node" in ground
    assert "main_nodes" not in projection
    assert "main_nodes" not in ground


def test_select_is_an_independent_stage_service() -> None:
    select = (ROOT / "workflow" / "stages" / "select.py").read_text(encoding="utf-8")
    assert "async def select_node" in select
    assert "main_nodes" not in select


def test_execute_is_an_independent_stage_service() -> None:
    execute = (ROOT / "workflow" / "stages" / "execute.py").read_text(encoding="utf-8")
    assert "async def execute_node" in execute
    assert "main_nodes" not in execute


def test_validation_and_reconciliation_are_independent_stage_services() -> None:
    validate = (ROOT / "workflow" / "stages" / "validate.py").read_text(encoding="utf-8")
    reconcile = (ROOT / "workflow" / "stages" / "reconcile.py").read_text(encoding="utf-8")
    assert "async def validate_node" in validate
    assert "async def reconcile_node" in reconcile
    assert "main_nodes" not in validate
    assert "main_nodes" not in reconcile
