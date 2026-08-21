"""Provider-neutral protocols for evidence and validation adapters.

Re-exports are lazy (PEP 562 ``__getattr__``) so importing a single submodule
(e.g. ``app.contracts.ports.planning_ports``) does not eagerly pull the
evidence/domain chain through ``adjustment`` — that chain would create an
import cycle with ``app.infrastructure.context.planning_context``.  ``from
app.contracts.ports import <Name>`` and ``import *`` still work via
``__getattr__``.
"""

from __future__ import annotations

import importlib as _importlib

__all__ = [
    "AdjustmentExecutionResult",
    "BundleAssemblyPort",
    "ContextProviderPort",
    "ExternalSearchPort",
    "GazetteerPort",
    "MediaEvidencePort",
    "NomenclatureRegistryPort",
    "PlanningContextProvider",
    "PlanningPorts",
    "RoadPlannerPort",
    "SemanticQueryPort",
    "SpatialQueryPort",
    "ValidationAdjustmentExecutor",
    "VisualEvidencePort",
    "WorkerInput",
    "WorkerResult",
    "ZoneAllocatorPort",
]

_MODULE_MAP = {
    "AdjustmentExecutionResult": "adjustment",
    "ValidationAdjustmentExecutor": "adjustment",
    "BundleAssemblyPort": "bundle_assembly",
    "ContextProviderPort": "context",
    "PlanningContextProvider": "context",
    "ExternalSearchPort": "external_search",
    "GazetteerPort": "gazetteer",
    "MediaEvidencePort": "media_evidence",
    "VisualEvidencePort": "media_evidence",
    "NomenclatureRegistryPort": "nomenclature_registry",
    "PlanningPorts": "planning_ports",
    "RoadPlannerPort": "road_planner",
    "SemanticQueryPort": "semantic_query",
    "SpatialQueryPort": "spatial",
    "WorkerInput": "workers",
    "WorkerResult": "workers",
    "ZoneAllocatorPort": "zone_allocator",
}


def __getattr__(name: str) -> object:
    module_name = _MODULE_MAP.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = _importlib.import_module(f"{__name__}.{module_name}")
    return getattr(module, name)
