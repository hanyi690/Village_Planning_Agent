"""Read-only planning dependency graph projection."""

from __future__ import annotations

from fastapi import APIRouter

from app.config.dependency import get_full_dependency_chain
from app.config.loader import _get_cached_config


router = APIRouter(prefix="/api/v1", tags=["Stable v1"])


@router.get("/planning/dependency-graph")
async def get_dependency_graph() -> dict[str, object]:
    """Return the declared topic dependency graph used by the planner.

    This is configuration metadata only. It does not infer dependencies from
    report text and it does not claim that any node has been executed.
    """

    config = _get_cached_config()
    chain = get_full_dependency_chain()
    dimensions: list[dict[str, object]] = []
    edges: list[dict[str, str]] = []

    for phase in config.phases:
        layer = int(phase.id.removeprefix("layer"))
        for dimension in phase.dimensions:
            dependency_kinds = (
                [(key, "same_layer") for key in dimension.depends_on]
                + [(key, "layer") for key in dimension.layer_depends_on]
                + [(key, "phase") for key in dimension.phase_depends_on]
            )
            depends_on = [key for key, _ in dependency_kinds]
            dimensions.append(
                {
                    "key": dimension.key,
                    "name": dimension.name,
                    "layer": layer,
                    "wave": chain.get(dimension.key, {}).get("wave", 1),
                    "depends_on": depends_on,
                }
            )
            for source, kind in dependency_kinds:
                edges.append({"source": source, "target": dimension.key, "kind": kind})

    return {
        "schema_version": "1.0",
        "source": "backend/app/config/phases.yaml",
        "dimensions": dimensions,
        "edges": edges,
    }
