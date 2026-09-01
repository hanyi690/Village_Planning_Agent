"""Typed container for injected dependency-inversion ports.

Replaces the untyped ``ports: dict[str, Any]`` field on ``PlanningContext``
so downstream modules consume typed Protocols instead of dict lookups.

Only Protocols live here (interfaces); implementations are injected by the
context factory in ``app.infrastructure.context_runtime.manager``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.contracts.ports.bundle_assembly import BundleAssemblyPort
from app.contracts.ports.context import ContextProviderPort
from app.contracts.ports.gazetteer import GazetteerPort
from app.contracts.ports.nomenclature_registry import NomenclatureRegistryPort
from app.contracts.ports.road_planner import RoadPlannerPort
from app.contracts.ports.semantic_query import SemanticQueryPort
from app.contracts.ports.spatial_query import SpatialQueryPort
from app.contracts.ports.zone_allocator import ZoneAllocatorPort
from app.contracts.ports.world_model import WorldModelCommitPort, WorldModelPort


@dataclass
class PlanningPorts:
    """Typed bundle of optional injected port implementations."""

    context_provider: ContextProviderPort | None = None
    semantic_query: SemanticQueryPort | None = None
    spatial_query: SpatialQueryPort | None = None
    gazetteer: GazetteerPort | None = None
    nomenclature_registry: NomenclatureRegistryPort | None = None
    bundle_assembly: BundleAssemblyPort | None = None
    zone_allocator: ZoneAllocatorPort | None = None
    road_planner: RoadPlannerPort | None = None
    world_model: WorldModelPort | None = None
    world_model_commit: WorldModelCommitPort | None = None

__all__ = ["PlanningPorts"]
