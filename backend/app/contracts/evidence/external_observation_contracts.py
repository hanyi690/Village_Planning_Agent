"""Contracts for cached map-provider observations.

An external observation is provenance-bearing source evidence.  It is not a
local GIS feature, a WorldEntity, or executable planning geometry.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ExternalObservation(BaseModel):
    """One normalized provider record kept independently from the Bundle."""

    model_config = ConfigDict(extra="forbid")

    observation_id: str
    provider: str
    stage: str
    operation: str = ""
    status: str = "success_nonempty"
    attempted: bool = True
    scope_bucket: str = "unknown_scope"
    observed_name: str = ""
    aliases: list[str] = Field(default_factory=list)
    observed_type: str = ""
    location_wgs84: tuple[float, float] | None = None
    location_native: tuple[float, float] | None = None
    coordinate_contract: str = ""
    geometry: dict[str, Any] | None = None
    geometry_semantics: str = "point_observation"
    raw_response_ref: str = ""
    source_record_ref: str = ""
    request_key: str = ""
    query_name: str = ""
    cluster_id: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("location_wgs84", "location_native")
    @classmethod
    def _validate_coordinate_pair(
        cls,
        value: tuple[float, float] | None,
    ) -> tuple[float, float] | None:
        if value is None:
            return None
        lon, lat = value
        if not (-180.0 <= float(lon) <= 180.0 and -90.0 <= float(lat) <= 90.0):
            raise ValueError("coordinate pair is outside lon/lat bounds")
        return (float(lon), float(lat))


class ExternalObservationSnapshot(BaseModel):
    """Immutable-by-convention session view of cached observations."""

    model_config = ConfigDict(extra="forbid")

    snapshot_id: str
    project_name: str = ""
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    observations: list[ExternalObservation] = Field(default_factory=list)
    provider_runs: list[dict[str, Any]] = Field(default_factory=list)
    excluded_counts: dict[str, int] = Field(default_factory=dict)
    complete: bool = False
    digest: str = ""

    def model_post_init(self, __context: Any) -> None:
        if self.digest:
            return
        payload = {
            "project_name": self.project_name,
            "observations": [
                item.model_dump(mode="json") for item in self.observations
            ],
            "provider_runs": self.provider_runs,
            "excluded_counts": self.excluded_counts,
            "complete": self.complete,
        }
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


__all__ = ["ExternalObservation", "ExternalObservationSnapshot"]
