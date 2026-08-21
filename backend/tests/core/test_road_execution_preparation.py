from __future__ import annotations

import json
import hashlib
import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.contracts.domain.road_planning import (
    ExistingRoadPlanningInput,
    NewCorridorPlanningInput,
    RoadArtifactEvidence,
    RoadEndpointEvidence,
    RoadRoutingEvidence,
)
from app.domain.materialization.existing_road_materializer import (
    materialize_existing_road_interventions,
)
from app.domain.materialization.road_generator import _road_targets_to_stage2
from app.domain.materialization.execute_state import ExecuteAgentState
from app.domain.materialization.nodes.road_worker import (
    _normalize_road_unresolved_findings,
    _road_worker,
)
from app.domain.materialization.road_generator import (
    _partition_stage4_candidates,
    execute_road_planning_from_agent_state,
)
from app.spatial.network.road_candidate_preparation import (
    build_road_evidence_catalog,
    new_corridor_inputs_to_stage2_targets,
)
from app.spatial.network.planning_nodes import _road_intents


def _write_feature_collection(
    path: Path,
    features: list[dict],
    *,
    crs: str = "EPSG:4326",
) -> Path:
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "crs": {"type": "name", "properties": {"name": crs}},
                "features": features,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def _line_feature(identifier: str, coordinates: list[list[float]], **properties: object) -> dict:
    return {
        "type": "Feature",
        "id": identifier,
        "geometry": {"type": "LineString", "coordinates": coordinates},
        "properties": dict(properties),
    }


def _artifact(role: str, ref: str) -> RoadArtifactEvidence:
    return RoadArtifactEvidence(
        role=role,
        artifact_ref=ref,
        checksum="sha256:test",
    )


def _endpoint(role: str, entity_ref: str, coordinate: tuple[float, float]) -> RoadEndpointEvidence:
    return RoadEndpointEvidence(
        role=role,
        resolution_status="resolved",
        entity_ref=entity_ref,
        coordinate=coordinate,
        coordinate_crs="EPSG:4326",
        source_artifact_ref="artifact://grounding/place-resolution",
        source_feature_id=entity_ref,
        evidence_refs=[f"evidence://{entity_ref}"],
    )


class _Workspace:
    def __init__(self, payload: dict, *, dem: object | None = None) -> None:
        self._payload = payload
        self.rasters = SimpleNamespace(dem=dem)

    def to_delivery_inputs(self) -> dict:
        return self._payload


def _execution_state(targets: list[dict], workspace: _Workspace) -> ExecuteAgentState:
    tasks = []
    for index, target in enumerate(targets, start=1):
        target_id = str(target["target_id"])
        tasks.append(
            {
                "task_id": f"task-road-{index}",
                "worker_type": "road_construction",
                "target_id": target_id,
                "target_type": "road",
                "expected_output_kind": "line",
                "assignment": {
                    "target_id": target_id,
                    "target_type": "road",
                    "expected_output_kind": "line",
                    "target_binding": target,
                },
            }
        )
    return ExecuteAgentState(
        session_id="road-contract-test",
        spatial_workspace=workspace,
        execution_plan={"worker_tasks": tasks},
        tasks_to_run=["road"],
    )


def _workspace_payload() -> dict:
    return {
        "road_geojson": {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "features": [
                _line_feature(
                    "ROAD-FEATURE-001",
                    [[116.0, 24.8], [116.01, 24.81]],
                    bsm="ROAD-BSM-001",
                )
            ],
        },
        "boundary_geojson": {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [115.99, 24.79],
                                [116.02, 24.79],
                                [116.02, 24.82],
                                [115.99, 24.82],
                                [115.99, 24.79],
                            ]
                        ],
                    },
                    "properties": {"bsm": "BOUNDARY-001"},
                }
            ],
        },
        "landuse_current_geojson": {
            "type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": "EPSG:4326"}},
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [115.99, 24.79],
                                [116.02, 24.79],
                                [116.02, 24.82],
                                [115.99, 24.82],
                                [115.99, 24.79],
                            ]
                        ],
                    },
                    "properties": {"bsm": "PARCEL-001", "DLBM": "0101"},
                }
            ],
        },
    }


def test_build_catalog_uses_only_authoritative_feature_and_stage1_segment_ids(
    tmp_path: Path,
) -> None:
    roads = _write_feature_collection(
        tmp_path / "current_roads.geojson",
        [
            _line_feature(
                "source-ignored-when-bsm-exists",
                [[116.0, 24.8], [116.01, 24.81]],
                bsm="ROAD-BSM-001",
                name="Y122乡道",
            ),
            _line_feature(
                "ROAD-FEATURE-002",
                [[116.01, 24.81], [116.02, 24.82]],
                name="村道",
            ),
        ],
    )
    edges = _write_feature_collection(
        tmp_path / "road_edges.geojson",
        [
            _line_feature(
                "not-the-segment-contract",
                [[0.0, 0.0], [10.0, 0.0]],
                edge_id="E000001",
            )
        ],
        crs="EPSG:4527",
    )

    catalog = build_road_evidence_catalog(
        road_edges_path=edges,
        current_roads_path=roads,
        routing_evidence=RoadRoutingEvidence(dem=_artifact("dem", "artifact://dem")),
    )

    assert catalog.current_road_feature_ids == {
        "ROAD-BSM-001",
        "ROAD-FEATURE-002",
    }
    assert catalog.current_road_segment_ids == {"E000001"}
    assert catalog.current_network is not None
    assert catalog.current_network.artifact_ref == edges.resolve().as_uri()
    assert catalog.current_network.checksum.startswith("sha256:")
    assert catalog.routing_evidence.dem is not None


def test_build_catalog_accepts_bundle_source_feature_identity_when_nested_in_raw(
    tmp_path: Path,
) -> None:
    source_feature_id = "bundle://current-road/source-feature-001"
    roads = _write_feature_collection(
        tmp_path / "current_roads.geojson",
        [
            _line_feature(
                "road-index-0",
                [[116.0, 24.8], [116.01, 24.81]],
                bsm="ROAD-BSM-001",
                _raw={"source_feature_id": source_feature_id},
            )
        ],
    )
    edges = _write_feature_collection(
        tmp_path / "road_edges.geojson",
        [_line_feature("edge-0", [[116.0, 24.8], [116.01, 24.81]], edge_id="E000001")],
        crs="EPSG:4527",
    )

    catalog = build_road_evidence_catalog(
        road_edges_path=edges,
        current_roads_path=roads,
    )

    assert catalog.current_road_feature_ids == {source_feature_id}


def test_existing_road_materialization_selects_exact_stage1_segments_with_lineage(
    tmp_path: Path,
) -> None:
    roads = _write_feature_collection(
        tmp_path / "current_roads.geojson",
        [_line_feature("ROAD-FEATURE-001", [[116.0, 24.8], [116.01, 24.81]])],
    )
    edges = _write_feature_collection(
        tmp_path / "road_edges.geojson",
        [
            _line_feature("edge-one", [[0.0, 0.0], [10.0, 0.0]], edge_id="E000001"),
            _line_feature("edge-two", [[10.0, 0.0], [20.0, 0.0]], edge_id="E000002"),
        ],
        crs="EPSG:4527",
    )
    planning_input = ExistingRoadPlanningInput(
        target_id="road-upgrade-1",
        source_project_id="project-1",
        action="upgrade",
        existing_road_segment_ids=["E000002"],
        road_evidence_refs=["evidence://kg/y122"],
        routing_evidence=RoadRoutingEvidence(
            current_network=RoadArtifactEvidence(
                role="current_road_network",
                artifact_ref=edges.resolve().as_uri(),
                checksum="sha256:test-network",
            )
        ),
    )

    result = materialize_existing_road_interventions(
        [planning_input],
        road_edges_path=edges,
        current_roads_path=roads,
        output_path=tmp_path / "planned_existing_roads.geojson",
    )

    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert result.report["materialized_feature_count"] == 1
    assert len(payload["features"]) == 1
    feature = payload["features"][0]
    assert feature["properties"]["target_id"] == "road-upgrade-1"
    assert feature["properties"]["source_project_id"] == "project-1"
    assert feature["properties"]["source_road_segment_id"] == "E000002"
    assert feature["properties"]["road_planning_kind"] == "existing_road_intervention"
    assert feature["properties"]["is_construction_design"] is False
    assert feature["properties"]["source_network_checksum"] == "sha256:test-network"
    assert feature["geometry"]["type"] == "LineString"


def test_existing_road_materialization_never_substitutes_an_unknown_binding(
    tmp_path: Path,
) -> None:
    roads = _write_feature_collection(tmp_path / "current_roads.geojson", [])
    edges = _write_feature_collection(tmp_path / "road_edges.geojson", [], crs="EPSG:4527")
    planning_input = ExistingRoadPlanningInput(
        target_id="road-repair-missing",
        action="repair",
        existing_road_segment_ids=["E999999"],
        routing_evidence=RoadRoutingEvidence(
            current_network=RoadArtifactEvidence(
                role="current_road_network",
                artifact_ref=edges.resolve().as_uri(),
                checksum="sha256:test-network",
            )
        ),
    )

    result = materialize_existing_road_interventions(
        [planning_input],
        road_edges_path=edges,
        current_roads_path=roads,
        output_path=tmp_path / "planned_existing_roads.geojson",
    )

    payload = json.loads(result.output_path.read_text(encoding="utf-8"))
    assert payload["features"] == []
    assert result.report["status"] == "partial"
    assert result.diagnostics[0]["code"] == "ROAD_EXISTING_SEGMENT_MATERIALIZATION_MISSING"


def test_new_corridor_adapter_emits_only_two_auditable_resolved_endpoints(
    tmp_path: Path,
) -> None:
    planning_input = NewCorridorPlanningInput(
        target_id="road-new-1",
        source_project_id="project-new-1",
        start_endpoint=_endpoint("start", "place://village-a", (116.0, 24.8)),
        end_endpoint=_endpoint("end", "place://village-b", (116.02, 24.82)),
        routing_evidence=RoadRoutingEvidence(dem=_artifact("dem", "artifact://dem")),
    )

    targets = new_corridor_inputs_to_stage2_targets([planning_input])
    stage2_dir = _road_targets_to_stage2(targets, tmp_path)

    demands = json.loads((stage2_dir / "demand_points.geojson").read_text(encoding="utf-8"))
    projects = json.loads((stage2_dir / "road_projects.json").read_text(encoding="utf-8"))
    assert len(demands["features"]) == 2
    assert {item["properties"]["location_status"] for item in demands["features"]} == {
        "resolved"
    }
    assert all("-start" not in item["properties"]["name"] for item in demands["features"])
    project = projects["projects"][0]
    assert project["typed_contract_version"] == "road-planning-input-v1"
    assert project["action"] == "new"
    assert project["start_geometry"]["coordinates"] == [116.0, 24.8]
    assert project["end_geometry"]["coordinates"] == [116.02, 24.82]
    assert project["requires_human_confirmation"] is False
    assert project["start_endpoint_evidence"]["source_artifact_ref"]
    assert project["end_endpoint_evidence"]["evidence_refs"]

    intents = _road_intents(stage2_dir)
    assert len(intents) == 1
    assert intents[0]["action"] == "new"
    assert intents[0]["mentioned_places"] == [
        "place://village-a",
        "place://village-b",
    ]
    assert intents[0]["requires_human_confirmation"] is False
    assert intents[0]["extraction_method"] == "typed_road_planning_input"


def test_generator_routes_existing_intervention_around_stage26(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.materialization import road_generator

    monkeypatch.setattr(road_generator, "_road_output_root", lambda: tmp_path / "road")
    state = _execution_state(
        [
            {
                "target_id": "road-existing-1",
                "action": "upgrade",
                "road_planning_kind": "existing_road_intervention",
                "existing_road_segment_ids": ["E000001"],
            }
        ],
        _Workspace(_workspace_payload()),
    )

    result = execute_road_planning_from_agent_state(state)

    assert result["ready_existing_target_count"] == 1
    assert result["ready_new_corridor_target_count"] == 0
    assert result["unresolved_items"] == []
    assert result["artifacts"]["stage2"] is None
    assert result["artifacts"]["stage2_6"] is None
    planned = next(
        layer for layer in result["layout_layers"] if layer["layerType"] == "planned_road"
    )
    feature = planned["data"]["features"][0]
    assert feature["properties"]["target_id"] == "road-existing-1"
    assert feature["properties"]["source_road_segment_id"] == "E000001"


def test_generator_routes_proven_new_corridor_through_typed_stage26(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.materialization import road_generator

    monkeypatch.setattr(road_generator, "_road_output_root", lambda: tmp_path / "road")
    state = _execution_state(
        [
            {
                "target_id": "road-new-proven",
                "source_project_id": "project-new-proven",
                "action": "new",
                "road_planning_kind": "new_corridor",
                "start_endpoint": _endpoint(
                    "start",
                    "place://road-start",
                    (116.0, 24.8),
                ).model_dump(mode="json"),
                "end_endpoint": _endpoint(
                    "end",
                    "place://road-end",
                    (116.01, 24.81),
                ).model_dump(mode="json"),
            }
        ],
        _Workspace(_workspace_payload()),
    )

    result = execute_road_planning_from_agent_state(state)

    assert result["ready_existing_target_count"] == 0
    assert result["ready_new_corridor_target_count"] == 1
    assert result["unresolved_items"] == []
    assert result["artifacts"]["stage2"] is not None
    assert result["artifacts"]["stage2_6"] is not None
    assert result["stage2_6_report"]["located_entity_count"] >= 2
    assert result["automatic_route_generation_allowed"] is True
    formal = [
        layer
        for layer in result["layout_layers"]
        if layer["layerType"] == "planned_road_candidates"
    ]
    assert formal
    assert formal[0]["data"]["features"]
    assert {
        feature["properties"]["target_id"]
        for feature in formal[0]["data"]["features"]
    } == {"road-new-proven"}


def test_stage4_partition_never_promotes_unbound_network_repairs_to_target_output() -> None:
    payload = {
        "type": "FeatureCollection",
        "features": [
            _line_feature(
                "target-candidate",
                [[116.0, 24.8], [116.01, 24.81]],
                target_id="road-new-1",
                source_type="road_project",
                screening_status="feasible",
            ),
            _line_feature(
                "target-rejected",
                [[116.0, 24.8], [116.012, 24.812]],
                target_id="road-new-1",
                source_type="road_project",
                screening_status="rejected_hard_constraint",
            ),
            _line_feature(
                "network-repair",
                [[116.02, 24.8], [116.03, 24.81]],
                source_id="NC0001",
                source_type="component_connection",
            ),
        ],
    }

    target_payload, rejected_payload, network_payload = _partition_stage4_candidates(
        payload,
        {"road-new-1"},
    )

    assert [item["id"] for item in target_payload["features"]] == [
        "target-candidate"
    ]
    assert [item["id"] for item in rejected_payload["features"]] == [
        "target-rejected"
    ]
    assert [item["id"] for item in network_payload["features"]] == [
        "network-repair"
    ]


def test_worker_classifies_post_gate_candidate_failure_as_route_failed() -> None:
    target = {
        "target_id": "road-new-route-failed",
        "source_project_id": "project-road-failed",
        "action": "new",
        "road_planning_kind": "new_corridor",
        "start_endpoint": _endpoint(
            "start", "place://route-start", (116.0, 24.8)
        ).model_dump(mode="json"),
        "end_endpoint": _endpoint(
            "end", "place://route-end", (116.02, 24.82)
        ).model_dump(mode="json"),
    }

    findings = _normalize_road_unresolved_findings(
        [target],
        produced_target_ids=set(),
        unresolved_items=[
            {
                "target_id": "road-new-route-failed",
                "diagnostic_codes": ["ROAD_CANDIDATE_NOT_GENERATED"],
                "evidence_refs": ["artifact://stage4/blocked-requests"],
                "message": "No target-bound route survived candidate generation.",
            }
        ],
    )

    assert findings[0]["code"] == "road_route_failed"
    assert findings[0]["reason_code"] == "route_failed"
    assert "artifact://stage4/blocked-requests" in findings[0]["evidence_refs"]


def test_generator_prepares_real_workspace_dem_and_landuse_for_stage4(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np
    import rasterio
    from rasterio.transform import from_origin

    from app.domain.materialization import road_generator

    dem_path = tmp_path / "terrain-dem.tif"
    elevations = np.linspace(100.0, 104.0, 80 * 80, dtype="float32").reshape(80, 80)
    with rasterio.open(
        dem_path,
        "w",
        driver="GTiff",
        width=80,
        height=80,
        count=1,
        dtype="float32",
        crs="EPSG:4326",
        transform=from_origin(115.99, 24.82, 0.0005, 0.0005),
        nodata=-9999.0,
    ) as dataset:
        dataset.write(elevations, 1)

    monkeypatch.setattr(road_generator, "_road_output_root", lambda: tmp_path / "road")
    state = _execution_state(
        [
            {
                "target_id": "road-new-terrain",
                "action": "new",
                "road_planning_kind": "new_corridor",
                "start_endpoint": _endpoint(
                    "start", "place://terrain-start", (116.0, 24.8)
                ).model_dump(mode="json"),
                "end_endpoint": _endpoint(
                    "end", "place://terrain-end", (116.01, 24.81)
                ).model_dump(mode="json"),
            }
        ],
        _Workspace(_workspace_payload(), dem=SimpleNamespace(path=str(dem_path))),
    )

    result = execute_road_planning_from_agent_state(state)

    dem_evidence = result["routing_evidence"]["dem"]
    assert dem_evidence["artifact_ref"] == dem_path.resolve().as_uri()
    assert dem_evidence["checksum"].startswith("sha256:")
    assert result["routing_evidence"]["land_friction"] is not None
    assert result["artifacts"]["dem"] == str(dem_path.resolve())
    assert result["artifacts"]["terrain_routing_grid"] is not None
    assert result["stage4_report"]["parameters"]["routing_method"] == (
        "raster_least_cost_path"
    )
    assert result["stage4_report"]["input_roles"]["dem_grid"] is not None


def test_generator_injects_only_checksum_verified_terrain_friction_grid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import numpy as np
    from pyproj import Transformer

    from app.domain.materialization import road_generator

    transformer = Transformer.from_crs("EPSG:4326", "EPSG:4527", always_xy=True)
    start_xy = transformer.transform(116.0, 24.8)
    end_xy = transformer.transform(116.01, 24.81)
    cell_size = 50.0
    x_min = min(start_xy[0], end_xy[0]) - 500.0
    y_max = max(start_xy[1], end_xy[1]) + 500.0
    width = math.ceil((max(start_xy[0], end_xy[0]) - x_min + 500.0) / cell_size)
    height = math.ceil((y_max - min(start_xy[1], end_xy[1]) + 500.0) / cell_size)
    shape = (height, width)
    grid_path = tmp_path / "terrain-friction-grid.npz"
    np.savez_compressed(
        grid_path,
        elevation_m=np.full(shape, 100.0, dtype="float32"),
        slope_deg=np.full(shape, 2.0, dtype="float32"),
        land_cost=np.full(shape, 1.0, dtype="float32"),
        inside_boundary=np.ones(shape, dtype=bool),
        x_min=np.asarray(x_min),
        y_max=np.asarray(y_max),
        cell_size_m=np.asarray(cell_size),
        metric_crs=np.asarray("EPSG:4527"),
    )
    checksum = "sha256:" + hashlib.sha256(grid_path.read_bytes()).hexdigest()

    monkeypatch.setattr(road_generator, "_road_output_root", lambda: tmp_path / "road")
    state = _execution_state(
        [
            {
                "target_id": "road-new-cost-grid",
                "action": "new",
                "road_planning_kind": "new_corridor",
                "start_endpoint": _endpoint(
                    "start", "place://grid-start", (116.0, 24.8)
                ).model_dump(mode="json"),
                "end_endpoint": _endpoint(
                    "end", "place://grid-end", (116.01, 24.81)
                ).model_dump(mode="json"),
                "routing_evidence": {
                    "land_friction": {
                        "role": "land_friction",
                        "artifact_ref": grid_path.resolve().as_uri(),
                        "checksum": checksum,
                    }
                },
            }
        ],
        _Workspace(_workspace_payload()),
    )

    result = execute_road_planning_from_agent_state(state)

    assert result["artifacts"]["terrain_routing_grid"] == str(grid_path.resolve())
    assert result["stage4_report"]["parameters"]["routing_method"] == (
        "raster_least_cost_path"
    )
    assert result["stage4_report"]["input_roles"]["dem_grid"] is not None


def test_worker_returns_target_bound_typed_unresolved_without_stage26_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.materialization import road_generator

    monkeypatch.setattr(road_generator, "_road_output_root", lambda: tmp_path / "road")
    state = _execution_state(
        [
            {
                "target_id": "road-new-unproven",
                "action": "new",
                "road_planning_kind": "new_corridor",
                "start_anchor": [116.0, 24.8],
                "end_anchor": [116.01, 24.81],
                "candidate_bsms": ["PARCEL-001"],
                "candidate_bbox": [115.99, 24.79, 116.02, 24.82],
            }
        ],
        _Workspace(_workspace_payload()),
    )

    result = _road_worker(state)

    assert result.layers == []
    assert len(result.unresolved_items) == 1
    unresolved = result.unresolved_items[0]
    assert unresolved["type"] == "RoadUnresolved"
    assert unresolved["code"] == "road_anchor_unresolved"
    assert unresolved["reason_code"] == "anchor_missing"
    assert unresolved["target_id"] == "road-new-unproven"
    assert "ROAD_ENDPOINT_PROVENANCE_MISSING" in unresolved["diagnostic_codes"]
    assert result.task_results[0].target_id == "road-new-unproven"
    assert result.task_results[0].status == "failed"
    assert result.task_results[0].diagnostics[0]["code"] == "road_anchor_unresolved"
    assert not (tmp_path / "road" / "road-contract-test" / "stage2_from_parse").exists()


def test_worker_keeps_nonformal_diagnostic_layers_for_failed_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.materialization import road_generator

    target_id = "road-route-failed-diagnostic"
    state = _execution_state(
        [
            {
                "target_id": target_id,
                "action": "new",
                "road_planning_kind": "new_corridor",
                "start_endpoint": _endpoint(
                    "start", "place://failed-start", (116.0, 24.8)
                ).model_dump(mode="json"),
                "end_endpoint": _endpoint(
                    "end", "place://failed-end", (116.02, 24.82)
                ).model_dump(mode="json"),
            }
        ],
        _Workspace(_workspace_payload()),
    )
    diagnostic_layer = {
        "layerType": "road_rejected_target_candidates",
        "data": {
            "type": "FeatureCollection",
            "features": [
                _line_feature(
                    "rejected",
                    [[116.0, 24.8], [116.02, 24.82]],
                    target_id=target_id,
                    screening_status="rejected_hard_constraint",
                )
            ],
        },
    }
    monkeypatch.setattr(
        road_generator,
        "execute_road_planning_from_agent_state",
        lambda _state: {
            "ran": True,
            "reason": "No feasible target route",
            "road_target_count": 1,
            "layout_layers": [diagnostic_layer],
            "unresolved_items": [
                {
                    "target_id": target_id,
                    "diagnostic_codes": ["ROAD_ALL_CANDIDATES_REJECTED"],
                    "message": "All target routes were rejected.",
                }
            ],
        },
    )

    result = _road_worker(state)

    assert result.task_results[0].status == "failed"
    assert result.layers == [diagnostic_layer]
    assert result.unresolved_items[0]["code"] == "road_route_failed"


def test_worker_preserves_unresolved_target_in_mixed_existing_and_new_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.domain.materialization import road_generator

    monkeypatch.setattr(road_generator, "_road_output_root", lambda: tmp_path / "road")
    state = _execution_state(
        [
            {
                "target_id": "road-existing-ready",
                "action": "repair",
                "road_planning_kind": "existing_road_intervention",
                "existing_road_segment_ids": ["E000001"],
            },
            {
                "target_id": "road-new-unproven-mixed",
                "action": "new",
                "road_planning_kind": "new_corridor",
                "connects": ["全村", "村外"],
                "candidate_bsms": ["PARCEL-001"],
            },
        ],
        _Workspace(_workspace_payload()),
    )

    result = _road_worker(state)

    assert any(layer["layerType"] == "planned_road" for layer in result.layers)
    assert [item["target_id"] for item in result.unresolved_items] == [
        "road-new-unproven-mixed"
    ]
    by_target = {item.target_id: item for item in result.task_results}
    assert by_target["road-existing-ready"].status == "succeeded"
    assert by_target["road-new-unproven-mixed"].status == "failed"
    assert by_target["road-new-unproven-mixed"].diagnostics[0]["code"] == (
        "road_anchor_unresolved"
    )
