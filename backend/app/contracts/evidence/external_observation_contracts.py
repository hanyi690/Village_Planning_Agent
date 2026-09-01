"""Contracts for cached map-provider observations.

An external observation is provenance-bearing source evidence.  It is not a
local GIS feature, a WorldEntity, or executable planning geometry.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.contracts.evidence.provider_attempt import ProviderAttempt


ExternalObservationStatus = Literal[
    "success_nonempty",
    "success_empty",
    "missing",
    "missing_capability",
    "failed",
    "not_attempted",
]

SpatialEvidenceRole = Literal[
    "feature_location",
    "administrative_anchor",
    "coarse_geocode",
    "name_only",
    "missing",
]

_WGS84_CRS_ALIASES = frozenset(
    {
        "wgs84",
        "wgs-84",
        "epsg:4326",
        "epsg4326",
        "crs84",
        "urn:ogc:def:crs:ogc:1.3:crs84",
        "urn:ogc:def:crs:epsg::4326",
    }
)


def normalize_coordinate_crs(value: Any) -> str:
    return "".join(str(value or "").casefold().split())


def is_wgs84_equivalent_crs(value: Any) -> bool:
    return normalize_coordinate_crs(value) in _WGS84_CRS_ALIASES


def has_explicit_wgs84_direct_contract(value: Any) -> bool:
    contract = str(value or "").casefold().strip()
    if not contract or "compatible" in contract:
        return False
    normalized = normalize_coordinate_crs(contract)
    if normalized in _WGS84_CRS_ALIASES:
        return True
    return any(
        token in contract
        for token in ("coord_type=wgs84", "wgs84 direct", "wgs84直出", "direct wgs84")
    )


class ExternalObservation(BaseModel):
    """One normalized provider record kept independently from the Bundle."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    provider: str
    stage: str
    operation: str = ""
    status: ExternalObservationStatus = "success_nonempty"
    attempted: bool = True
    scope_bucket: str = "unknown_scope"
    admin_match: dict[str, bool] = Field(default_factory=dict)
    observed_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    observed_type: str = ""
    location_wgs84: tuple[float, float] | None = None
    location_native: tuple[float, float] | None = None
    coordinate_contract: str = ""
    observed_at: datetime | None = None
    collected_at: datetime | None = None
    provider_timestamp: datetime | None = None
    run_created_at: datetime | None = None
    coordinate_source_crs: str = ""
    coordinate_target_crs: str = ""
    coordinate_transform: str = ""
    coordinate_trust_status: Literal[
        "verified_direct",
        "verified_transformed",
        "unverified",
        "missing",
    ] = "unverified"
    spatial_evidence_role: SpatialEvidenceRole = "name_only"
    geometry: dict[str, Any] | None = None
    geometry_semantics: str = "point_observation"
    raw_response_ref: str = ""
    source_record_ref: str = ""
    request_key: str = ""
    query_name: str = ""
    cluster_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("location_wgs84", "location_native", mode="before")
    @classmethod
    def _validate_coordinate_pair(
        cls,
        value: Any,
    ) -> tuple[float, float] | None:
        if value is None:
            return None
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise ValueError("coordinate must be a pair")
        try:
            lon, lat = (float(item) for item in value)
        except (TypeError, ValueError):
            raise ValueError("coordinate pair must contain numbers") from None
        if not (math.isfinite(lon) and math.isfinite(lat)):
            raise ValueError("coordinate pair must be finite")
        if not (-180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0):
            raise ValueError("coordinate pair is outside lon/lat bounds")
        return (lon, lat)

    @model_validator(mode="after")
    def _validate_coordinate_trust(self) -> "ExternalObservation":
        has_coordinates = self.location_wgs84 is not None or self.location_native is not None
        if not has_coordinates:
            object.__setattr__(self, "coordinate_trust_status", "missing")
            object.__setattr__(self, "spatial_evidence_role", "missing")
            return self
        if self.coordinate_target_crs and not is_wgs84_equivalent_crs(
            self.coordinate_target_crs
        ):
            object.__setattr__(self, "coordinate_trust_status", "unverified")
            return self
        if self.coordinate_trust_status == "verified_direct":
            valid = (
                self.location_wgs84 is not None
                and is_wgs84_equivalent_crs(self.coordinate_source_crs)
                and is_wgs84_equivalent_crs(self.coordinate_target_crs)
                and has_explicit_wgs84_direct_contract(self.coordinate_contract)
            )
            if not valid:
                object.__setattr__(self, "coordinate_trust_status", "unverified")
        elif self.coordinate_trust_status == "verified_transformed":
            transform = self.coordinate_transform.casefold()
            valid = (
                self.location_native is not None
                and self.location_wgs84 is not None
                and bool(self.coordinate_source_crs.strip())
                and is_wgs84_equivalent_crs(self.coordinate_target_crs)
                and bool(self.coordinate_transform.strip())
                and ("wgs84" in transform or "wgs-84" in transform)
            )
            if not valid:
                object.__setattr__(self, "coordinate_trust_status", "unverified")
        return self


class ExternalObservationSnapshot(BaseModel):
    """Immutable-by-convention session view of cached observations."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    project_name: str = ""
    administrative_scope: dict[str, str] = Field(default_factory=dict)
    scope_bbox_wgs84: tuple[float, float, float, float] | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observations: list[ExternalObservation] = Field(default_factory=list)
    provider_runs: list[dict[str, Any]] = Field(default_factory=list)
    provider_attempts: tuple[ProviderAttempt, ...] = ()
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    complete: bool = False
    digest: str = ""

    @field_validator("scope_bbox_wgs84")
    @classmethod
    def _validate_scope_bbox(
        cls,
        value: tuple[float, float, float, float] | None,
    ) -> tuple[float, float, float, float] | None:
        if value is None:
            return None
        min_lon, min_lat, max_lon, max_lat = (float(item) for item in value)
        if not (
            -180.0 <= min_lon <= max_lon <= 180.0
            and -90.0 <= min_lat <= max_lat <= 90.0
        ):
            raise ValueError("scope bbox is outside WGS84 bounds")
        return min_lon, min_lat, max_lon, max_lat

    def model_post_init(self, __context: Any) -> None:
        if self.digest:
            return
        payload = canonical_external_observation_payload(
            project_name=self.project_name,
            administrative_scope=self.administrative_scope,
            scope_bbox_wgs84=self.scope_bbox_wgs84,
            observations=self.observations,
            provider_runs=self.provider_runs,
            provider_attempts=self.provider_attempts,
            excluded_counts=self.excluded_counts,
            complete=self.complete,
        )
        digest = hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                default=str,
            ).encode("utf-8")
        ).hexdigest()
        object.__setattr__(self, "digest", f"sha256:{digest}")
        object.__setattr__(
            self,
            "snapshot_id",
            self.snapshot_id or f"external-map-{digest[:16]}",
        )


_SEMANTIC_PATH_KEYS = frozenset({
    "path",
    "cache_root",
    "cache_directory",
    "raw_response_directory",
    "provider_path",
    "absolute_provider_path",
})


def _canonical_semantic_value(value: Any, *, key: str = "") -> Any:
    """Remove machine-specific cache locations while retaining evidence."""

    if isinstance(value, BaseModel):
        value = value.model_dump(mode="json")
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            item_key = str(raw_key)
            if item_key in _SEMANTIC_PATH_KEYS:
                continue
            result[item_key] = _canonical_semantic_value(raw_value, key=item_key)
        return result
    if isinstance(value, (list, tuple, set)):
        return [_canonical_semantic_value(item, key=key) for item in value]
    if key in {"raw_response_ref", "source_record_ref"} and isinstance(value, str):
        candidate = value.replace("\\", "/")
        if Path(candidate).is_absolute():
            return Path(candidate).name
        return candidate
    return value


def canonical_external_observation_payload(
    *,
    project_name: str,
    administrative_scope: Mapping[str, Any],
    scope_bbox_wgs84: Any,
    observations: Iterable[Any],
    provider_runs: Iterable[Mapping[str, Any]],
    excluded_counts: Mapping[str, Any],
    complete: bool,
    provider_attempts: Iterable[Any] = (),
) -> dict[str, Any]:
    """Return the shared semantic identity payload for a cache snapshot."""

    observation_values = [_canonical_semantic_value(item) for item in observations]
    observation_values.sort(
        key=lambda item: json.dumps(item, ensure_ascii=False, sort_keys=True, default=str)
    )
    run_values = [_canonical_semantic_value(item) for item in provider_runs]
    run_values.sort(key=lambda item: (
        str(item.get("provider", "")),
        str(item.get("stage", "")),
        str(item.get("run_id", "")),
    ))
    return {
        "project_name": project_name,
        "administrative_scope": _canonical_semantic_value(administrative_scope),
        "scope_bbox_wgs84": _canonical_semantic_value(scope_bbox_wgs84),
        "observations": observation_values,
        "provider_runs": run_values,
        "provider_attempts": [
            _canonical_semantic_value(item)
            for item in sorted(
                list(provider_attempts),
                key=lambda value: str(
                    getattr(value, "attempt_ref", "")
                    or (value.get("attempt_ref", "") if isinstance(value, Mapping) else "")
                ),
            )
        ],
        "excluded_counts": _canonical_semantic_value(excluded_counts),
        "complete": bool(complete),
    }


__all__ = [
    "ExternalObservation",
    "ExternalObservationSnapshot",
    "ExternalObservationStatus",
    "SpatialEvidenceRole",
    "canonical_external_observation_payload",
    "has_explicit_wgs84_direct_contract",
    "is_wgs84_equivalent_crs",
    "normalize_coordinate_crs",
]
