"""Declaration-only contracts for remote DATA sources.

Remote services are not DATA products at admission time.  Admission proves
that a bounded provider run *may* be scheduled; a provider run must later
publish an immutable observation/raster product with its own coverage proof.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Literal, Mapping

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field, field_validator, model_validator


RemoteSourceKind = Literal[
    "api_vector",
    "wfs",
    "mapserver",
    "wmts",
    "remote_raster",
]

_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_SECRET_WORDS = ("token=", "apikey=", "api_key=", "password=", "secret=", "authorization=")
_ALLOWED_DEFAULT_HOSTS = {
    "guangdong.tianditu.gov.cn",
    "t0.tianditu.gov.cn",
    "t1.tianditu.gov.cn",
    "t2.tianditu.gov.cn",
    "t3.tianditu.gov.cn",
    "t4.tianditu.gov.cn",
    "t5.tianditu.gov.cn",
    "t6.tianditu.gov.cn",
    "t7.tianditu.gov.cn",
}


class RemoteAdmissionLimits(BaseModel):
    """Finite provider-run budget declared before a remote fetch."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_requests: int = Field(default=100, ge=1, le=10000)
    max_records: int = Field(default=50000, ge=1, le=1000000)
    min_zoom: int = Field(default=1, ge=0, le=24)
    max_zoom: int = Field(default=18, ge=0, le=24)

    @model_validator(mode="after")
    def zoom_range_is_ordered(self) -> "RemoteAdmissionLimits":
        if self.max_zoom < self.min_zoom:
            raise ValueError("max_zoom must be >= min_zoom")
        return self


class RemoteSourceAdmissionRequest(BaseModel):
    """Closed declaration accepted without contacting the remote endpoint."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    source_id: str = Field(min_length=1, max_length=200)
    kind: RemoteSourceKind
    endpoint: AnyHttpUrl
    provider: str = Field(min_length=1, max_length=100)
    layer: str = Field(default="", max_length=200)
    boundary_ref: str = Field(min_length=1, max_length=300)
    boundary_digest: str
    query_geometry_digest: str
    crs_contract: str = Field(min_length=1, max_length=500)
    capabilities: tuple[str, ...] = Field(min_length=1)
    auth_ref: str = Field(default="", max_length=300)
    limits: RemoteAdmissionLimits = Field(default_factory=RemoteAdmissionLimits)
    allowed_hosts: tuple[str, ...] = ()

    @field_validator("boundary_digest", "query_geometry_digest")
    @classmethod
    def digest_is_sha256(cls, value: str) -> str:
        value = str(value).strip().lower()
        if not _DIGEST.fullmatch(value):
            raise ValueError("digest must be sha256:<64 lowercase hex chars>")
        return value

    @field_validator("capabilities")
    @classmethod
    def capabilities_are_closed(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(sorted({str(item).strip().casefold() for item in value if str(item).strip()}))
        if not normalized:
            raise ValueError("at least one capability is required")
        if any(len(item) > 100 for item in normalized):
            raise ValueError("capability is too long")
        return normalized

    @field_validator("auth_ref")
    @classmethod
    def auth_is_reference_only(cls, value: str) -> str:
        normalized = str(value or "").strip()
        lowered = normalized.casefold()
        if any(word in lowered for word in _SECRET_WORDS):
            raise ValueError("auth_ref must not contain credential material")
        if normalized and not (normalized.startswith("env://") or normalized.startswith("credential://")):
            raise ValueError("auth_ref must be an env:// or credential:// reference")
        return normalized

    @field_validator("crs_contract")
    @classmethod
    def crs_contract_is_explicit(cls, value: str) -> str:
        normalized = " ".join(str(value).split())
        folded = normalized.casefold()
        if "unknown" in folded or "guess" in folded or "target" not in folded:
            raise ValueError("crs_contract must explicitly declare a target CRS")
        if "wgs84" not in folded and "epsg:4326" not in folded:
            raise ValueError("remote query CRS contract must name WGS84/EPSG:4326 target")
        return normalized

    @model_validator(mode="after")
    def endpoint_policy_is_closed(self) -> "RemoteSourceAdmissionRequest":
        if self.endpoint.scheme.casefold() != "https":
            raise ValueError("remote admission requires HTTPS")
        host = (self.endpoint.host or "").casefold().rstrip(".")
        allowed = {item.casefold().rstrip(".") for item in self.allowed_hosts if str(item).strip()}
        if not allowed:
            allowed = _ALLOWED_DEFAULT_HOSTS
        if host not in allowed:
            raise ValueError("remote endpoint host is not allowlisted")
        path = str(self.endpoint)
        if any(word in path.casefold() for word in _SECRET_WORDS):
            raise ValueError("remote endpoint must not contain credential query parameters")
        return self

    @property
    def request_digest(self) -> str:
        payload = self.model_dump(mode="json", exclude={"allowed_hosts"})
        return "sha256:" + hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    @classmethod
    def from_catalog_declaration(
        cls,
        source_id: str,
        declaration: Mapping[str, Any],
        *,
        boundary_ref: str,
        boundary_digest: str,
        query_geometry_digest: str,
        auth_ref: str = "",
    ) -> "RemoteSourceAdmissionRequest":
        """Compile one YAML source declaration without making a network call."""

        driver = str(declaration.get("driver") or "").strip().casefold()
        protocol = str(declaration.get("protocol") or "").strip().casefold()
        kind = {
            "api_vector": "wfs" if protocol == "wfs" else "mapserver",
            "wmts_tile": "wmts",
            "remote_raster": "remote_raster",
        }.get(driver)
        if kind is None:
            raise ValueError(f"source {source_id!r} is not a remote admission kind")
        endpoint = declaration.get("endpoint") or declaration.get("base_url")
        if not endpoint:
            raise ValueError(f"source {source_id!r} must declare endpoint explicitly")
        layer_values = declaration.get("layers") or ()
        capabilities = [protocol or driver]
        capabilities.extend(
            str(item.get("layer_type") or item.get("name") or "")
            for item in layer_values
            if isinstance(item, Mapping)
        )
        return cls(
            source_id=source_id,
            kind=kind,
            endpoint=endpoint,
            provider=str(declaration.get("provider") or declaration.get("connection") or ""),
            layer=str(declaration.get("layer") or declaration.get("service_id") or ""),
            boundary_ref=boundary_ref,
            boundary_digest=boundary_digest,
            query_geometry_digest=query_geometry_digest,
            crs_contract=f"source={declaration.get('crs') or ''}; target=WGS84/EPSG:4326",
            capabilities=tuple(item for item in capabilities if item),
            auth_ref=auth_ref,
            limits=RemoteAdmissionLimits(
                min_zoom=int((declaration.get("zoom_range") or [1, 18])[0]),
                max_zoom=int((declaration.get("zoom_range") or [1, 18])[-1]),
            ),
        )


class RemoteSourceAdmissionReceipt(BaseModel):
    """Immutable proof that a remote provider run may be scheduled."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    receipt_id: str = Field(min_length=1)
    request_digest: str
    source_id: str
    kind: RemoteSourceKind
    provider: str
    status: Literal["ADMITTED", "QUARANTINED", "REJECTED"]
    provider_run_required: bool = True
    boundary_ref: str
    boundary_digest: str
    query_geometry_digest: str
    crs_contract: str
    capability_contract: tuple[str, ...]
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("request_digest", "boundary_digest", "query_geometry_digest")
    @classmethod
    def receipt_digest_is_sha256(cls, value: str) -> str:
        if not _DIGEST.fullmatch(str(value).strip().lower()):
            raise ValueError("receipt digest must be sha256:<64 lowercase hex chars>")
        return str(value).strip().lower()


__all__ = [
    "RemoteAdmissionLimits",
    "RemoteSourceAdmissionReceipt",
    "RemoteSourceAdmissionRequest",
    "RemoteSourceKind",
]
