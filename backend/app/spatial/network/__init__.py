"""Road-network construction and future road-planning services.

Typed wrapper for the typed workspace (NetworkIndex) plus the
road-network construction / future road-planning service layer.
"""

from typing import Any

from .schemas import (
    LocationConfirmationConfig,
    LocationConfirmationResult,
    CandidateScoringConfig,
    CandidateScoringResult,
    NetworkBuildConfig,
    NetworkBuildResult,
    PlanComparisonConfig,
    PlanComparisonResult,
    PlanningNodeBuildConfig,
    PlanningNodeBuildResult,
    RoadEdgeRecord,
    RoadNodeRecord,
    RoadPlanningConfig,
    RoadPlanningResult,
    SpatialBindingConfig,
    SpatialBindingResult,
    Stage2StructureConfig,
    Stage2StructureResult,
)

from .network_index import NetworkIndex, build_network_from_workspace


def __getattr__(name: str) -> Any:
    """Load the CLI-capable builder lazily to keep ``python -m`` warning-free."""
    if name in {"RoadNetworkBuilder", "build_road_network"}:
        from .network_builder import RoadNetworkBuilder, build_road_network

        return {
            "RoadNetworkBuilder": RoadNetworkBuilder,
            "build_road_network": build_road_network,
        }[name]
    if name == "structure_road_requirements":
        from .text_structurer import structure_road_requirements

        return structure_road_requirements
    if name in {"generate_location_confirmation_workflow", "apply_location_confirmations"}:
        from .location_confirmation import (
            apply_location_confirmations,
            generate_location_confirmation_workflow,
        )

        return {
            "generate_location_confirmation_workflow": generate_location_confirmation_workflow,
            "apply_location_confirmations": apply_location_confirmations,
        }[name]
    if name == "bind_road_spatial_requirements":
        from .spatial_binder import bind_road_spatial_requirements

        return bind_road_spatial_requirements
    if name == "build_planning_nodes":
        from .planning_nodes import build_planning_nodes

        return build_planning_nodes
    if name == "validate_stage2_6_outputs":
        from .stage2_6_validator import validate_stage2_6_outputs

        return validate_stage2_6_outputs
    if name in {"prepare_road_candidate", "prepare_road_candidates"}:
        from .road_candidate_preparation import (
            prepare_road_candidate,
            prepare_road_candidates,
        )

        return {
            "prepare_road_candidate": prepare_road_candidate,
            "prepare_road_candidates": prepare_road_candidates,
        }[name]
    if name == "RDFLibKGSpatialRetryAdapter":
        from .kg_rdflib_adapter import RDFLibKGSpatialRetryAdapter

        return RDFLibKGSpatialRetryAdapter
    if name in {
        "build_planning_nodes_with_kg_retry_adapter",
        "build_planning_nodes_with_kg_retry_response",
        "normalise_kg_retry_response",
    }:
        from .kg_retry import (
            build_planning_nodes_with_kg_retry_adapter,
            build_planning_nodes_with_kg_retry_response,
            normalise_kg_retry_response,
        )

        return {
            "build_planning_nodes_with_kg_retry_adapter": build_planning_nodes_with_kg_retry_adapter,
            "build_planning_nodes_with_kg_retry_response": build_planning_nodes_with_kg_retry_response,
            "normalise_kg_retry_response": normalise_kg_retry_response,
        }[name]
    if name == "run_stage4_road_planning":
        from .planner import run_stage4_road_planning

        return run_stage4_road_planning
    if name == "score_road_candidates":
        from .evaluator import score_road_candidates

        return score_road_candidates
    if name == "compare_road_plans":
        from .comparison_evaluator import compare_road_plans

        return compare_road_plans
    raise AttributeError(name)

__all__ = [
    "NetworkBuildConfig",
    "NetworkBuildResult",
    "NetworkIndex",
    "PlanComparisonConfig",
    "PlanComparisonResult",
    "LocationConfirmationConfig",
    "LocationConfirmationResult",
    "CandidateScoringConfig",
    "CandidateScoringResult",
    "PlanningNodeBuildConfig",
    "PlanningNodeBuildResult",
    "RoadEdgeRecord",
    "RoadNetworkBuilder",
    "RoadNodeRecord",
    "RoadPlanningConfig",
    "RoadPlanningResult",
    "SpatialBindingConfig",
    "SpatialBindingResult",
    "Stage2StructureConfig",
    "Stage2StructureResult",
    "build_network_from_workspace",
    "build_road_network",
    "apply_location_confirmations",
    "generate_location_confirmation_workflow",
    "bind_road_spatial_requirements",
    "build_planning_nodes",
    "validate_stage2_6_outputs",
    "prepare_road_candidate",
    "prepare_road_candidates",
    "RDFLibKGSpatialRetryAdapter",
    "build_planning_nodes_with_kg_retry_adapter",
    "build_planning_nodes_with_kg_retry_response",
    "normalise_kg_retry_response",
    "run_stage4_road_planning",
    "score_road_candidates",
    "compare_road_plans",
    "structure_road_requirements",
]
