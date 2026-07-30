"""Builder registry: @kg_builder decorator, _KG_BUILDERS, BuildContext.

Usage:
    @kg_builder("water", entity_type="WaterBody", layer=1, order=30)
    def add_water_bodies(kg, features, *, gis_type_ref, entry, ctx):
        ...
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional


@dataclass
class BuilderSpec:
    gis_type_ref: str
    fn: Callable
    entity_type: str | None = None
    layer: int = 1
    order: int = 0


_KG_BUILDERS: dict[str, BuilderSpec] = {}


def kg_builder(gis_type_ref: str, *, entity_type: str | None = None,
               layer: int = 1, order: int = 0):
    def decorator(fn: Callable) -> Callable:
        _KG_BUILDERS[gis_type_ref] = BuilderSpec(
            gis_type_ref=gis_type_ref, fn=fn,
            entity_type=entity_type, layer=layer, order=order,
        )
        if entity_type:
            fn._kg_entity_type = entity_type
        return fn
    return decorator


def get_builder(gis_type_ref: str) -> Callable | None:
    spec = _KG_BUILDERS.get(gis_type_ref)
    return spec.fn if spec else None


def _ordered_builders() -> list[BuilderSpec]:
    return sorted(_KG_BUILDERS.values(), key=lambda s: (s.layer, s.order))


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
    val = group.get(key_name) if hasattr(group, "get") else getattr(group, key_name, [])
    if val is None:
        return []
    if isinstance(val, list):
        return list(val)
    return [val]