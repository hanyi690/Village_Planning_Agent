"""Builder registry: @kg_builder decorator, _KG_BUILDERS, BuildContext.

Usage:
    @kg_builder("water", entity_type="WaterBody")
    def _add_water_bodies(self, features, *, gis_type_ref, entry, ctx):
        ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional

_KG_BUILDERS: dict[str, Callable] = {}


def kg_builder(gis_type_ref: str, *, entity_type: str | None = None):
    def decorator(fn: Callable) -> Callable:
        _KG_BUILDERS[gis_type_ref] = fn
        if entity_type:
            fn._kg_entity_type = entity_type
        return fn
    return decorator


def get_builder(gis_type_ref: str) -> Callable | None:
    return _KG_BUILDERS.get(gis_type_ref)


@dataclass
class BuildContext:
    village_name: str
    bbox: Optional[tuple[float, float, float, float]] = None
    constraint_index: Any = None
    provenance: dict[str, Any] = field(default_factory=dict)


def _get_bundle_features(bundle, entry) -> list:
    if entry is None or entry.bundle_target is None:
        return []
    group_name = entry.bundle_target.group
    key_name = entry.bundle_target.key
    group = getattr(bundle, group_name, None)
    if group is None:
        return []
    return list(getattr(group, key_name, []))