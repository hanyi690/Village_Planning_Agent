"""Data contracts for deterministic road-network construction."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Mapping, Optional, Tuple


@dataclass(frozen=True)
class NetworkBuildConfig:
    """Configuration for converting road lines into a routable graph."""

    metric_crs: str = "EPSG:4527"
    display_crs: str = "EPSG:4326"
    source_crs_override: Optional[str] = None
    snap_tolerance_m: float = 1.0
    tolerance_scenarios_m: Tuple[float, ...] = (1.0, 3.0, 5.0)
    min_source_length_m: float = 0.5
    min_edge_length_m: float = 0.05
    duplicate_precision_m: float = 0.01
    coordinate_precision_m: float = 0.001
    allow_evaluation_input: bool = False

    def validate(self) -> None:
        if self.snap_tolerance_m <= 0:
            raise ValueError("snap_tolerance_m must be > 0")
        if not self.tolerance_scenarios_m:
            raise ValueError("tolerance_scenarios_m cannot be empty")
        if any(value <= 0 for value in self.tolerance_scenarios_m):
            raise ValueError("all tolerance scenarios must be > 0")
        if self.min_source_length_m < 0 or self.min_edge_length_m < 0:
            raise ValueError("minimum lengths cannot be negative")
        if self.duplicate_precision_m <= 0 or self.coordinate_precision_m <= 0:
            raise ValueError("precision values must be > 0")


@dataclass(frozen=True)
class RoadNodeRecord:
    node_id: str
    x: float
    y: float
    degree: int
    node_type: str
    component_id: str


@dataclass(frozen=True)
class RoadEdgeRecord:
    edge_id: str
    from_node: str
    to_node: str
    length_m: float
    component_id: str
    geometry: Any = field(repr=False)


@dataclass(frozen=True)
class NetworkBuildResult:
    """Paths and in-memory report returned by a completed build."""

    output_dir: Path
    nodes_path: Path
    edges_path: Path
    report_path: Path
    preview_path: Path
    report: Dict[str, Any]


@dataclass(frozen=True)
class Stage2StructureConfig:
    """Inputs and safety settings for evidence-backed demand extraction."""

    demand_workbook: Path
    current_workbook: Optional[Path]
    project_documents: Tuple[Path, ...]
    constraint_documents: Tuple[Path, ...]
    location_sources: Tuple[Path, ...]
    output_dir: Path
    village_name: str = "金田村"
    display_crs: str = "EPSG:4326"

    def validate(self) -> None:
        if not self.demand_workbook.exists():
            raise FileNotFoundError(self.demand_workbook)
        for path in self.project_documents + self.constraint_documents:
            if not path.exists():
                raise FileNotFoundError(path)
        if self.current_workbook is not None and not self.current_workbook.exists():
            raise FileNotFoundError(self.current_workbook)
        for path in self.location_sources:
            if not path.exists():
                raise FileNotFoundError(path)
            normalized = path.as_posix().lower()
            forbidden = (
                "/planned/road.geojson",
                "/project/lines.geojson",
                "/project/points.geojson",
                "/project/polygons.geojson",
            )
            if any(normalized.endswith(value) for value in forbidden):
                raise ValueError(
                    f"evaluation/planned geometry cannot be used for location matching: {path}"
                )


@dataclass(frozen=True)
class Stage2StructureResult:
    """Paths and summary returned by a completed Stage-2 extraction."""

    output_dir: Path
    demand_points_path: Path
    road_projects_path: Path
    road_constraints_path: Path
    report_path: Path
    review_queue_path: Path
    report: Dict[str, Any]


@dataclass(frozen=True)
class LocationConfirmationConfig:
    """Inputs for the Stage-2.5 manual spatial-confirmation workflow."""

    stage2_dir: Path
    output_dir: Path
    boundary_path: Path
    current_road_path: Path
    maplibre_dist_dir: Optional[Path] = None
    display_crs: str = "EPSG:4326"

    def validate(self) -> None:
        required_outputs = (
            "demand_points.geojson",
            "road_projects.json",
            "road_constraints.json",
        )
        for filename in required_outputs:
            path = self.stage2_dir / filename
            if not path.exists():
                raise FileNotFoundError(path)
        if not self.boundary_path.exists():
            raise FileNotFoundError(self.boundary_path)
        if not self.current_road_path.exists():
            raise FileNotFoundError(self.current_road_path)


@dataclass(frozen=True)
class LocationConfirmationResult:
    """Files created by Stage 2.5 task generation or confirmation application."""

    output_dir: Path
    tasks_path: Path
    map_path: Path
    confirmation_template_path: Path
    constraint_template_path: Path
    report_path: Path
    report: Dict[str, Any]


@dataclass(frozen=True)
class PlanningNodeBuildConfig:
    """Inputs for Stage 2.6 planning-entity location and node construction."""

    stage2_dir: Path
    output_dir: Path
    road_edges_path: Path
    boundary_path: Optional[Path] = None
    point_sources: Tuple[Path, ...] = ()
    knowledge_graph_path: Optional[Path] = None
    bundle_geometry_sources: Tuple[Path, ...] = ()
    # Optional Explore -> deterministic Binder artifact.  Stage 2.6 consumes
    # it before its legacy KG/text candidates but keeps all existing gates.
    bound_spatial_entities_path: Optional[Path] = None
    manual_confirmation_path: Optional[Path] = None
    metric_crs: str = "EPSG:4527"
    display_crs: str = "EPSG:4326"
    cluster_distance_m: float = 120.0
    connected_threshold_m: float = 10.0
    near_network_threshold_m: float = 100.0
    low_confidence_threshold: float = 0.65
    min_new_connection_distance_m: float = 40.0
    allow_evaluation_input: bool = False

    def validate(self) -> None:
        required = (
            self.stage2_dir / "demand_points.geojson",
            self.stage2_dir / "road_projects.json",
            self.stage2_dir / "road_constraints.json",
        )
        for path in required:
            if not path.exists():
                raise FileNotFoundError(path)
        if not self.road_edges_path.exists():
            raise FileNotFoundError(self.road_edges_path)
        if self.boundary_path is not None and not self.boundary_path.exists():
            raise FileNotFoundError(self.boundary_path)
        if self.knowledge_graph_path is not None and not self.knowledge_graph_path.exists():
            raise FileNotFoundError(self.knowledge_graph_path)
        if self.bound_spatial_entities_path is not None and not self.bound_spatial_entities_path.exists():
            raise FileNotFoundError(self.bound_spatial_entities_path)
        if self.manual_confirmation_path is not None and not self.manual_confirmation_path.exists():
            raise FileNotFoundError(self.manual_confirmation_path)
        if self.cluster_distance_m <= 0:
            raise ValueError("cluster_distance_m must be > 0")
        if self.connected_threshold_m < 0:
            raise ValueError("connected_threshold_m must be >= 0")
        if self.near_network_threshold_m < self.connected_threshold_m:
            raise ValueError("near_network_threshold_m must be >= connected_threshold_m")
        if not 0 <= self.low_confidence_threshold <= 1:
            raise ValueError("low_confidence_threshold must be between 0 and 1")
        if self.min_new_connection_distance_m < 0:
            raise ValueError("min_new_connection_distance_m must be >= 0")
        forbidden_suffixes = (
            "/planned/road.geojson",
            "/project/lines.geojson",
            "/project/points.geojson",
            "/project/polygons.geojson",
        )
        guarded_paths = (self.road_edges_path,) + self.point_sources + self.bundle_geometry_sources
        for path in guarded_paths:
            normalized = path.as_posix().lower()
            if not self.allow_evaluation_input and any(
                normalized.endswith(suffix) for suffix in forbidden_suffixes
            ):
                raise ValueError(
                    f"planned/evaluation geometry cannot be used by Stage 2.6: {path}"
                )
        for path in self.point_sources:
            if not path.exists():
                raise FileNotFoundError(path)
        for path in self.bundle_geometry_sources:
            if not path.exists():
                raise FileNotFoundError(path)


@dataclass(frozen=True)
class PlanningNodeBuildResult:
    """Files produced by Stage 2.6 before Stage-3/4 road generation."""

    output_dir: Path
    road_intents_path: Path
    kg_updates_path: Path
    spatial_candidates_path: Path
    located_entities_path: Path
    planning_nodes_path: Path
    road_planning_requests_path: Path
    quality_gates_path: Path
    iteration_records_path: Path
    kg_retry_requests_path: Path
    execute_trace_path: Path
    review_queue_path: Path
    human_confirmation_template_path: Path
    report_path: Path
    report: Dict[str, Any]


@dataclass(frozen=True)
class SpatialBindingConfig:
    """Inputs and thresholds for Stage-3 demand/network spatial binding."""

    stage2_dir: Path
    road_edges_path: Path
    output_dir: Path
    stage2_6_dir: Optional[Path] = None
    stage2_5_resolved_dir: Optional[Path] = None
    point_sources: Tuple[Path, ...] = ()
    constraint_layer_sources: Mapping[str, Tuple[Path, ...]] = field(default_factory=dict)
    constraint_layer_filters: Mapping[str, Mapping[str, Tuple[str, ...]]] = field(
        default_factory=dict
    )
    metric_crs: str = "EPSG:4527"
    display_crs: str = "EPSG:4326"
    connected_threshold_m: float = 10.0
    near_network_threshold_m: float = 100.0
    allow_evaluation_input: bool = False

    def validate(self) -> None:
        if self.connected_threshold_m < 0:
            raise ValueError("connected_threshold_m must be >= 0")
        if self.near_network_threshold_m < self.connected_threshold_m:
            raise ValueError(
                "near_network_threshold_m must be >= connected_threshold_m"
            )
        required = (
            self.stage2_dir / "demand_points.geojson",
            self.stage2_dir / "road_projects.json",
            self.stage2_dir / "road_constraints.json",
        )
        for path in required:
            if not path.exists():
                raise FileNotFoundError(path)
        if self.stage2_6_dir is not None:
            stage2_6_required = (
                self.stage2_6_dir / "demand_points.geojson",
                self.stage2_6_dir / "road_projects.json",
                self.stage2_6_dir / "road_constraints.json",
                self.stage2_6_dir / "planning_nodes.geojson",
                self.stage2_6_dir / "road_planning_requests.json",
            )
            if any(path.exists() for path in stage2_6_required):
                for path in stage2_6_required:
                    if not path.exists():
                        raise FileNotFoundError(path)
        if not self.road_edges_path.exists():
            raise FileNotFoundError(self.road_edges_path)
        normalized = self.road_edges_path.as_posix().lower()
        forbidden = ("/planned/road.geojson", "/project/lines.geojson")
        if not self.allow_evaluation_input and any(
            normalized.endswith(value) for value in forbidden
        ):
            raise ValueError(
                f"planned/evaluation road cannot be used for Stage 3: {self.road_edges_path}"
            )
        for path in self.point_sources:
            if not path.exists():
                raise FileNotFoundError(path)
        for paths in self.constraint_layer_sources.values():
            for path in paths:
                if not path.exists():
                    raise FileNotFoundError(path)


@dataclass(frozen=True)
class SpatialBindingResult:
    """Files and report produced by Stage-3 spatial binding."""

    output_dir: Path
    demand_binding_path: Path
    project_binding_path: Path
    project_endpoints_path: Path
    connectors_path: Path
    constraints_path: Path
    unserved_path: Path
    preview_path: Path
    report_path: Path
    report: Dict[str, Any]


@dataclass(frozen=True)
class RoadPlanningConfig:
    """Stage-4 corridor analysis, candidate generation, and screening inputs."""

    road_nodes_path: Path
    road_edges_path: Path
    stage3_dir: Path
    boundary_path: Path
    landuse_path: Path
    output_dir: Path
    hazard_points_path: Optional[Path] = None
    dem_grid_path: Optional[Path] = None
    building_footprints_path: Optional[Path] = None
    metric_crs: str = "EPSG:4527"
    display_crs: str = "EPSG:4326"
    default_speed_kmh: float = 20.0
    network_connection_tolerance_m: float = 2.0
    deadend_search_radius_m: float = 300.0
    component_search_radius_m: float = 2000.0
    hazard_screening_distance_m: float = 100.0
    long_unserved_threshold_m: float = 500.0
    service_buffer_m: float = 300.0
    sharp_turn_angle_deg: float = 60.0
    alternative_offset_ratio: float = 0.2
    alternative_offset_cap_m: float = 250.0
    access_cluster_distance_m: float = 120.0
    min_access_connector_length_m: float = 40.0
    max_deadend_requests: int = 30
    max_component_requests: int = 100
    max_access_cluster_requests: int = 80
    terrain_max_slope_deg: float = 35.0
    terrain_preferred_slope_deg: float = 12.0
    terrain_max_grade_percent: float = 18.0
    minimum_curve_radius_m: float = 15.0
    existing_road_buffer_m: float = 4.0
    assumed_existing_road_width_m: float = 3.5
    default_planned_road_width_m: float = 4.5
    allow_evaluation_input: bool = False

    def validate(self) -> None:
        required = (
            self.road_nodes_path,
            self.road_edges_path,
            self.stage3_dir / "demand_network_binding.geojson",
            self.stage3_dir / "road_project_spatial_binding.json",
            self.stage3_dir / "spatial_constraints.geojson",
            self.boundary_path,
            self.landuse_path,
        )
        for path in required:
            if not path.exists():
                raise FileNotFoundError(path)
        if self.hazard_points_path is not None and not self.hazard_points_path.exists():
            raise FileNotFoundError(self.hazard_points_path)
        if self.dem_grid_path is not None and not self.dem_grid_path.exists():
            raise FileNotFoundError(self.dem_grid_path)
        if self.building_footprints_path is not None and not self.building_footprints_path.exists():
            raise FileNotFoundError(self.building_footprints_path)
        for path in (self.road_nodes_path, self.road_edges_path):
            normalized = path.as_posix().lower()
            if not self.allow_evaluation_input and (
                normalized.endswith("/planned/road.geojson")
                or normalized.endswith("/project/lines.geojson")
            ):
                raise ValueError(f"planned/evaluation road cannot be used for Stage 4: {path}")
        positive_values = {
            "default_speed_kmh": self.default_speed_kmh,
            "network_connection_tolerance_m": self.network_connection_tolerance_m,
            "deadend_search_radius_m": self.deadend_search_radius_m,
            "component_search_radius_m": self.component_search_radius_m,
            "hazard_screening_distance_m": self.hazard_screening_distance_m,
            "long_unserved_threshold_m": self.long_unserved_threshold_m,
            "service_buffer_m": self.service_buffer_m,
            "sharp_turn_angle_deg": self.sharp_turn_angle_deg,
            "alternative_offset_cap_m": self.alternative_offset_cap_m,
            "access_cluster_distance_m": self.access_cluster_distance_m,
            "min_access_connector_length_m": self.min_access_connector_length_m,
            "terrain_max_slope_deg": self.terrain_max_slope_deg,
            "terrain_preferred_slope_deg": self.terrain_preferred_slope_deg,
            "terrain_max_grade_percent": self.terrain_max_grade_percent,
            "minimum_curve_radius_m": self.minimum_curve_radius_m,
            "existing_road_buffer_m": self.existing_road_buffer_m,
            "assumed_existing_road_width_m": self.assumed_existing_road_width_m,
            "default_planned_road_width_m": self.default_planned_road_width_m,
        }
        invalid = [name for name, value in positive_values.items() if value <= 0]
        if invalid:
            raise ValueError(f"Stage-4 positive parameters invalid: {', '.join(invalid)}")
        if not 0 < self.alternative_offset_ratio <= 1:
            raise ValueError("alternative_offset_ratio must be in (0, 1]")
        if self.max_deadend_requests < 0 or self.max_component_requests < 0 or self.max_access_cluster_requests < 0:
            raise ValueError("candidate request limits cannot be negative")
        if self.terrain_preferred_slope_deg > self.terrain_max_slope_deg:
            raise ValueError("terrain_preferred_slope_deg cannot exceed terrain_max_slope_deg")


@dataclass(frozen=True)
class RoadPlanningResult:
    """Stage-4 result paths and summary."""

    output_dir: Path
    network_analysis_path: Path
    diagnostics_path: Path
    accessibility_path: Path
    candidates_path: Path
    segments_path: Path
    evaluations_path: Path
    blocked_requests_path: Path
    preview_path: Path
    report_path: Path
    report: Dict[str, Any]


def _default_candidate_scoring_weights() -> Dict[str, float]:
    return {
        "length": 0.20,
        "slope": 0.15,
        "farmland": 0.15,
        "ecology": 0.15,
        "demolition": 0.10,
        "detour": 0.10,
        "population_benefit": 0.075,
        "accessibility_benefit": 0.075,
    }


@dataclass(frozen=True)
class CandidateScoringConfig:
    """Stage-5 normalized scoring, hard filtering, and expert weights."""

    stage4_dir: Path
    stage3_dir: Path
    road_nodes_path: Path
    road_edges_path: Path
    landuse_path: Path
    output_dir: Path
    weights: Mapping[str, float] = field(default_factory=_default_candidate_scoring_weights)
    metric_crs: str = "EPSG:4527"
    display_crs: str = "EPSG:4326"
    service_buffer_m: float = 300.0
    resident_proximity_m: float = 10.0
    ecology_proximity_m: float = 100.0
    hazard_hard_distance_m: float = 30.0
    hazard_soft_distance_m: float = 100.0
    unreachable_connection_benefit_m: float = 5000.0
    protected_farmland_is_hard: bool = True
    allow_evaluation_input: bool = False

    def validate(self) -> None:
        required = (
            self.stage4_dir / "candidate_roads.geojson",
            self.stage4_dir / "candidate_evaluations.json",
            self.stage3_dir / "demand_network_binding.geojson",
            self.stage3_dir / "spatial_constraints.geojson",
            self.road_nodes_path,
            self.road_edges_path,
            self.landuse_path,
        )
        for path in required:
            if not path.exists():
                raise FileNotFoundError(path)
        for path in (self.road_nodes_path, self.road_edges_path):
            normalized = path.as_posix().lower()
            if not self.allow_evaluation_input and (
                normalized.endswith("/planned/road.geojson")
                or normalized.endswith("/project/lines.geojson")
            ):
                raise ValueError(f"planned/evaluation road cannot be used for Stage 5: {path}")
        expected = set(_default_candidate_scoring_weights())
        if set(self.weights) != expected:
            missing = sorted(expected - set(self.weights))
            extra = sorted(set(self.weights) - expected)
            raise ValueError(f"weight keys mismatch; missing={missing}, extra={extra}")
        if any(float(value) < 0 for value in self.weights.values()):
            raise ValueError("candidate scoring weights cannot be negative")
        if sum(float(value) for value in self.weights.values()) <= 0:
            raise ValueError("candidate scoring weights cannot all be zero")
        positive = (
            self.service_buffer_m,
            self.resident_proximity_m,
            self.ecology_proximity_m,
            self.hazard_hard_distance_m,
            self.hazard_soft_distance_m,
            self.unreachable_connection_benefit_m,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("Stage-5 thresholds must be > 0")
        if self.hazard_soft_distance_m < self.hazard_hard_distance_m:
            raise ValueError("hazard_soft_distance_m must be >= hazard_hard_distance_m")


@dataclass(frozen=True)
class CandidateScoringResult:
    """Stage-5 scored, recommended, rejected, and report artifacts."""

    output_dir: Path
    scored_candidates_path: Path
    details_path: Path
    recommended_path: Path
    recommended_segments_path: Path
    final_plan_preview_path: Path
    rejected_path: Path
    preview_path: Path
    report_path: Path
    report: Dict[str, Any]


@dataclass(frozen=True)
class PlanComparisonConfig:
    """Stage-6 held-out comparison of an algorithm plan and a manual plan."""

    road_nodes_path: Path
    road_edges_path: Path
    algorithm_roads_path: Path
    manual_planned_roads_path: Path
    demand_points_path: Path
    landuse_path: Path
    ecological_protection_path: Path
    farmland_protection_path: Path
    hazard_points_path: Path
    output_dir: Path
    data_mode: str = "production"
    metric_crs: str = "EPSG:4527"
    display_crs: str = "EPSG:4326"
    current_match_buffer_m: float = 5.0
    similarity_buffer_m: float = 20.0
    endpoint_match_m: float = 50.0
    service_buffer_m: float = 100.0
    hazard_buffer_m: float = 100.0
    assumed_road_width_m: float = 4.5
    assumed_speed_kmh: float = 20.0
    assumed_unit_cost_yuan_per_m: float = 3000.0
    unreachable_time_penalty_min: float = 60.0

    def validate(self) -> None:
        for path in (
            self.road_nodes_path,
            self.road_edges_path,
            self.algorithm_roads_path,
            self.manual_planned_roads_path,
            self.demand_points_path,
            self.landuse_path,
            self.ecological_protection_path,
            self.farmland_protection_path,
            self.hazard_points_path,
        ):
            if not path.exists():
                raise FileNotFoundError(path)
        normalized = self.manual_planned_roads_path.as_posix().lower()
        if not normalized.endswith("/planned/road.geojson"):
            raise ValueError(
                "manual_planned_roads_path must explicitly be the held-out planned/road.geojson"
            )
        algorithm_normalized = self.algorithm_roads_path.as_posix().lower()
        if algorithm_normalized.endswith("/planned/road.geojson"):
            raise ValueError("algorithm roads cannot be the held-out manual planned road")
        if self.data_mode not in {"production", "demo_proxy"}:
            raise ValueError("data_mode must be production or demo_proxy")
        positive = (
            self.current_match_buffer_m,
            self.similarity_buffer_m,
            self.endpoint_match_m,
            self.service_buffer_m,
            self.hazard_buffer_m,
            self.assumed_road_width_m,
            self.assumed_speed_kmh,
            self.assumed_unit_cost_yuan_per_m,
            self.unreachable_time_penalty_min,
        )
        if any(value <= 0 for value in positive):
            raise ValueError("all Stage-6 thresholds and assumptions must be > 0")


@dataclass(frozen=True)
class PlanComparisonResult:
    """Stage-6 comparison artifacts and in-memory report."""

    output_dir: Path
    algorithm_roads_path: Path
    manual_new_roads_path: Path
    preview_path: Path
    comparison_table_path: Path
    metrics_path: Path
    report_path: Path
    report: Dict[str, Any]


__all__ = [
    "NetworkBuildConfig",
    "NetworkBuildResult",
    "RoadEdgeRecord",
    "RoadNodeRecord",
    "LocationConfirmationConfig",
    "LocationConfirmationResult",
    "PlanningNodeBuildConfig",
    "PlanningNodeBuildResult",
    "SpatialBindingConfig",
    "SpatialBindingResult",
    "RoadPlanningConfig",
    "RoadPlanningResult",
    "CandidateScoringConfig",
    "CandidateScoringResult",
    "PlanComparisonConfig",
    "PlanComparisonResult",
    "Stage2StructureConfig",
    "Stage2StructureResult",
]
