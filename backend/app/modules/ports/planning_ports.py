"""Typed container for injected dependency-inversion ports.

Replaces the untyped ``ports: dict[str, Any]`` field on ``PlanningContext``
so downstream modules consume typed Protocols instead of dict lookups.

Only Protocols live here (interfaces); implementations are injected by the
context factory in ``app.services.context``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.modules.ports.artifact_store import ArtifactStorePort
from app.modules.ports.bundle_assembly import BundleAssemblyPort
from app.modules.ports.context_provider import ContextProviderPort
from app.modules.ports.gazetteer import GazetteerPort
from app.modules.ports.nomenclature_registry import NomenclatureRegistryPort
from app.modules.ports.road_planner import RoadPlannerPort
from app.modules.ports.semantic_query import SemanticQueryPort
from app.modules.ports.spatial_query import SpatialQueryPort
from app.modules.ports.zone_allocator import ZoneAllocatorPort


@dataclass
class PlanningPorts:
    """Typed bundle of optional injected port implementations."""

    artifact_store: ArtifactStorePort | None = None
    context_provider: ContextProviderPort | None = None
    semantic_query: SemanticQueryPort | None = None
    spatial_query: SpatialQueryPort | None = None
    gazetteer: GazetteerPort | None = None
    nomenclature_registry: NomenclatureRegistryPort | None = None
    bundle_assembly: BundleAssemblyPort | None = None
    zone_allocator: ZoneAllocatorPort | None = None
    road_planner: RoadPlannerPort | None = None

    @property
    def has_artifact_store(self) -> bool:
        return self.artifact_store is not None


__all__ = ["PlanningPorts"]
