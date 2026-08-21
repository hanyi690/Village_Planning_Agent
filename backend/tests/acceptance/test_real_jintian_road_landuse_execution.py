from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.contracts.spatial.planned_state_contracts import PlannedState
from app.contracts.workflow.execution_plan_contracts import RoadPlanResult
from app.contracts.workflow.parse_contracts import RoadTarget, SpatialPlanningIntent
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.merge import merge_worker_results
from app.domain.materialization.nodes.road_worker import _road_worker
from app.domain.materialization.planned_state_builder import changeset_to_planned_state


_SCRIPTS_ROOT = Path(__file__).resolve().parents[2] / "scripts"
if str(_SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_ROOT))


@pytest.mark.parametrize(
    ("action", "planning_kind"),
    [("new", "new_corridor"), ("widen", "existing_road_intervention")],
)
def test_real_jintian_source_bound_road_materializes_line_and_transport_land(
    action: str,
    planning_kind: str,
):
    """Real JinTian line + real current parcels produce both output contracts."""

    from benchmark_real_evidence import _load_bundle
    from app.spatial.model.workspace import SpatialWorkspace
    from app.domain.delivery.render_layers import build_planned_overlay_layers

    bundle, counts = _load_bundle()
    assert counts["current_road"] == 131
    assert counts["landuse_current"] == 660
    road = list(bundle.lines.get("roads_current") or [])[0]
    source_feature_id = str((road._raw or {}).get("source_feature_id") or "")
    assert source_feature_id

    target = RoadTarget(
        target_id=f"real-jintian-road-{action}",
        action=action,
        road_planning_kind=planning_kind,
        road_level="village_road",
        roadbed_width_m=8.0,
        road_evidence_refs=[f"bundle:current_road:{source_feature_id}"],
        path_bsms=[str(road.bsm)],
    )
    target_payload = target.model_dump(mode="json")

    class _SourceBoundPlanner:
        def is_available(self):
            return True

        def plan(self, _state):
            return RoadPlanResult(
                available=True,
                layers=[{
                    "layerType": "planned_road",
                    "layerName": "规划道路",
                    "data": {
                        "type": "FeatureCollection",
                        "features": [{
                            "type": "Feature",
                            "geometry": road.geometry,
                            "properties": {
                                "target_id": target.target_id,
                                "target_ids": [target.target_id],
                                "feature_id": source_feature_id,
                                "road_level": "village_road",
                                "roadbed_width_m": 8.0,
                                "source_feature_ids": [source_feature_id],
                                "source_refs": [
                                    f"bundle:current_road:{source_feature_id}"
                                ],
                            },
                        }],
                    },
                }],
            )

    workspace = SpatialWorkspace.from_bundle(
        bundle,
        session_id="real-jintian-road-landuse-execution",
        source="real-jintian-road-landuse-acceptance",
    )
    state = ExecuteAgentState(
        session_id="real-jintian-road-landuse-execution",
        village_name="金田村",
        spatial_workspace=workspace,
        execution_plan={
            "worker_tasks": [{
                "task_id": f"road_construction:real-jintian-road-{action}",
                "worker_type": "road_construction",
                "target_id": target.target_id,
                "target_type": "road",
                "expected_output_kind": "line",
                "assignment": {
                    "target_id": target.target_id,
                    "target_type": "road",
                    "target_binding": target_payload,
                },
            }],
        },
        tasks_to_run=["road"],
        ports=SimpleNamespace(road_planner=_SourceBoundPlanner()),
    )

    worker_result = _road_worker(state)
    assert worker_result.task_results[0].status == "succeeded"
    assert any(layer["layerType"] == "planned_road" for layer in worker_result.layers)
    assert worker_result.parcel_changes
    transport_changes = [
        change
        for change in worker_result.parcel_changes
        if change.after_classification is not None
        and change.after_classification.code == "1006"
    ]
    assert transport_changes
    assert all(change.derived_from_bsms for change in transport_changes)

    changeset, layers, diagnostics, _ = merge_worker_results([worker_result])
    assert diagnostics == []
    assert changeset.changes
    planned = changeset_to_planned_state(
        changeset,
        SpatialPlanningIntent(road_targets=[target]),
        layers,
    )
    assert isinstance(planned, PlannedState)
    assert planned.roads
    assert planned.parcels
    assert any(item.planning_land_use == "1006" for item in planned.parcels)
    rendered_layers = build_planned_overlay_layers(planned)
    assert any(layer["layerType"] == "planned_road" for layer in rendered_layers)
    assert any(layer["layerType"] == "function_zone" for layer in rendered_layers)

    # Keep a visible artifact tied to the same authoritative road overlay;
    # this is deliberately separate from the project/facility demo PNG.
    from shutil import copyfile
    from shapely.geometry import mapping
    from shapely import wkt as shapely_wkt
    from app.infrastructure.rendering.static_render import render_comparison_preview

    def _feature(geometry, **properties):
        return {
            "type": "Feature",
            "properties": properties,
            "geometry": geometry,
        }

    current_features = [
        _feature(
            parcel.geometry,
            bsm=str(getattr(parcel, "bsm", "") or ""),
            change_status="preserved",
        )
        for parcel in (bundle.polygons.get("landuse_current") or [])
        if isinstance(getattr(parcel, "geometry", None), dict)
    ]
    change_features = []
    for change in changeset.changes:
        try:
            geometry = mapping(shapely_wkt.loads(change.after_geometry_wkt))
        except Exception:
            continue
        change_features.append(
            _feature(
                geometry,
                change_status="modified",
                planning_land_use="1006",
                source_bsms=list(change.derived_from_bsms),
            )
        )
    preview_layers = [
        {
            "layerType": "current_landuse",
            "layerName": "现状地类",
            "data": {"type": "FeatureCollection", "features": current_features},
            "geojson": {"type": "FeatureCollection", "features": current_features},
        },
        {
            "layerType": "complete_planned_landuse",
            "layerName": "完整期末地类",
            "data": {"type": "FeatureCollection", "features": current_features},
            "geojson": {"type": "FeatureCollection", "features": current_features},
        },
        {
            "layerType": "planned_changes",
            "layerName": "交通用地变更",
            "color": "#dc2626",
            "data": {"type": "FeatureCollection", "features": change_features},
            "geojson": {"type": "FeatureCollection", "features": change_features},
        },
    ]
    preview_layers.extend(rendered_layers)
    boundary = getattr(bundle, "boundary", None)
    if boundary is not None and isinstance(getattr(boundary, "geometry", None), dict):
        boundary_data = {
            "type": "FeatureCollection",
            "features": [_feature(boundary.geometry)],
        }
        preview_layers.append({
            "layerType": "boundary",
            "layerName": "村域边界",
            "color": "#0f172a",
            "data": boundary_data,
            "geojson": boundary_data,
        })
    output_dir = Path(__file__).parents[2] / "output"
    preview = render_comparison_preview(preview_layers, str(output_dir), "金田村道路执行")
    assert preview["status"] == "completed"
    assert preview["planned_road_count"] >= 1
    copyfile(preview["path"], output_dir / "execution_result_road.png")
