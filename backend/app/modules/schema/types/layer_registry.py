"""Unified GIS layer-type registry -- YAML-only metadata source.

Design (v4.4):
  YAML (gis_layer_registry.yaml) = single source of truth for all metadata.
  No Python-side _TYPE_BINDINGS dict. All model_class_name resolution
  is done via _infer_model_class() in ingest.py.

Adding a new GIS layer type:
  1. Add entry to gis_layer_registry.yaml (full metadata: ingest, bundle_target, kg, etc.)
  2. If it needs a Python model class, add mapping to _infer_model_class() in ingest.py
  3. Restart -- registry auto-builds from YAML at import time.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class IngestSpec(BaseModel):
    adapter: str = "features"
    feature_type: str = ""


class EncodingsSpec(BaseModel):
    dlbm_field: str = ""
    systems: List[str] = Field(default_factory=list)


class SpatialSpec(BaseModel):
    is_constraint: bool = False
    participates: List[str] = Field(default_factory=list)


class Bundletarget(BaseModel):
    group: str = "polygons"
    key: str = ""


class KgSpec(BaseModel):
    entity_type: str = ""
    uri_policy: str = "L1:{type}_{bsm}"


class ValidationSpec(BaseModel):
    required_fields: List[str] = Field(default_factory=list)
    geometry: Dict[str, bool] = Field(default_factory=lambda: {"must_be_valid": True, "dlq_on_error": True})


class GisLayerTypeEntry(BaseModel):
    """One GIS layer type's complete metadata, sourced from YAML."""
    gis_type_ref: str
    geometry_kind: str = ""
    i18n: Dict[str, str] = Field(default_factory=dict)
    group: str = ""
    ingest: Optional[IngestSpec] = None
    encodings: Optional[EncodingsSpec] = None
    spatial: Optional[SpatialSpec] = None
    bundle_target: Optional[Bundletarget] = None
    kg: Optional[KgSpec] = None
    validation: Optional[ValidationSpec] = None
    default_gdb_path: str = ""
    is_reference_layer: bool = False
    description: str = ""


GIS_LAYER_REGISTRY: Dict[str, GisLayerTypeEntry] = {}


def register_gis_layer_type(gis_type_ref: str, meta: dict) -> None:
    entry = GisLayerTypeEntry(
        gis_type_ref=gis_type_ref,
        geometry_kind=meta.get("geometry_kind", ""),
        i18n=meta.get("i18n", {}),
        group=meta.get("group", ""),
        ingest=IngestSpec(**meta["ingest"]) if "ingest" in meta else None,
        encodings=EncodingsSpec(**meta["encodings"]) if "encodings" in meta else None,
        spatial=SpatialSpec(**meta["spatial"]) if "spatial" in meta else None,
        bundle_target=Bundletarget(**meta["bundle_target"]) if "bundle_target" in meta else None,
        kg=KgSpec(**meta["kg"]) if "kg" in meta else None,
        validation=ValidationSpec(**meta["validation"]) if "validation" in meta else None,
        default_gdb_path=meta.get("default_gdb_path", ""),
        is_reference_layer=meta.get("is_reference_layer", False),
        description=meta.get("description", ""),
    )
    GIS_LAYER_REGISTRY[gis_type_ref] = entry


def get_gis_layer_entry(gis_type_ref: str) -> Optional[GisLayerTypeEntry]:
    return GIS_LAYER_REGISTRY.get(gis_type_ref)


def get_all_gis_layer_types() -> List[str]:
    return list(GIS_LAYER_REGISTRY.keys())


def build_registry_from_yaml(yaml_path: Optional[str] = None) -> None:
    if yaml_path is None:
        yaml_path = str(Path(__file__).parent / "gis_layer_registry.yaml")
    try:
        with open(yaml_path, "r", encoding="utf-8") as f:
            yaml_data = yaml.safe_load(f) or {}
    except FileNotFoundError:
        return

    gis_layer_types = yaml_data.get("layer_types", {})
    for gis_type_ref, meta in gis_layer_types.items():
        register_gis_layer_type(gis_type_ref, meta)


build_registry_from_yaml()


__all__ = [
    "GisLayerTypeEntry", "IngestSpec", "EncodingsSpec", "SpatialSpec",
    "Bundletarget", "KgSpec", "ValidationSpec",
    "GIS_LAYER_REGISTRY", "register_gis_layer_type",
    "get_gis_layer_entry", "get_all_gis_layer_types", "build_registry_from_yaml",
]