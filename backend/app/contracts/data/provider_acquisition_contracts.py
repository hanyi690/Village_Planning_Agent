"""Immutable DATA-owned contracts for remote provider acquisition."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.contracts.data.boundary_contracts import BoundaryScopeArtifact


ProviderName = Literal["amap", "tencent", "tianditu"]


def _digest(value: Any) -> str:
    raw = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return "sha256:" + hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ProviderAcquisitionPlan(BaseModel):
    """Reproducible spatial input for one DATA-owned provider acquisition run.

    This is deliberately different from EvidenceQueryPlan.  DATA describes
    how an already-authorized acquisition is executed and persisted; Evidence
    decides why a requirement is queried and when the result is sufficient.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    acquisition_ref: str = Field(min_length=1)
    provider: ProviderName
    stage: str = Field(min_length=1)
    boundary_ref: str = Field(min_length=1)
    boundary_digest: str = Field(min_length=1)
    query_geometry_digest: str = Field(min_length=1)
    normalized_crs: str = Field(min_length=1)
    provider_request_crs: str = Field(min_length=1)
    post_filter_crs: str = "EPSG:4326"
    geometry: dict[str, Any]
    bbox_wgs84: tuple[float, float, float, float]
    expansion_m: float = 0.0
    coverage_policy: str = Field(min_length=1)


def build_provider_acquisition_plan(
    boundary_scope: BoundaryScopeArtifact,
    *,
    provider: ProviderName,
    stage: str = "01_admin_scope",
    geometry: dict[str, Any] | None = None,
    expansion_m: float = 0.0,
    coverage_policy: str = "bounded_cache_with_explicit_partial_status",
) -> ProviderAcquisitionPlan:
    """Compile an acquisition plan without reading a filesystem boundary."""

    selected_geometry = dict(geometry or boundary_scope.geometry)
    coordinates = selected_geometry.get("coordinates")
    if not coordinates:
        raise ValueError("provider acquisition geometry is empty")
    from shapely.geometry import shape

    bounds = tuple(float(value) for value in shape(selected_geometry).bounds)
    if len(bounds) != 4:
        raise ValueError("provider acquisition geometry has no WGS84 bounds")
    provider_crs = {
        "amap": "GCJ-02",
        "tencent": "WGS84",
        "tianditu": "WGS84",
    }[provider]
    query_geometry_digest = _digest(selected_geometry)
    material = {
        "provider": provider,
        "stage": stage,
        "boundary_ref": boundary_scope.scope_ref,
        "boundary_digest": boundary_scope.boundary_digest,
        "query_geometry_digest": query_geometry_digest,
        "geometry": selected_geometry,
        "expansion_m": expansion_m,
    }
    return ProviderAcquisitionPlan(
        acquisition_ref="provider-acquisition:" + _digest(material)[7:31],
        provider=provider,
        stage=stage,
        boundary_ref=boundary_scope.scope_ref,
        boundary_digest=boundary_scope.boundary_digest,
        query_geometry_digest=query_geometry_digest,
        normalized_crs=boundary_scope.normalized_crs,
        provider_request_crs=provider_crs,
        geometry=selected_geometry,
        bbox_wgs84=bounds,
        expansion_m=expansion_m,
        coverage_policy=coverage_policy,
    )


__all__ = [
    "ProviderAcquisitionPlan",
    "ProviderName",
    "build_provider_acquisition_plan",
]
