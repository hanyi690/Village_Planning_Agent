"""Production acceptance contracts for the DATA runtime."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class DataProductionAcceptancePolicy(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_admission_ms: float = Field(default=2000, gt=0)
    max_context_bootstrap_ms: float = Field(default=10000, gt=0)
    max_evidence_retrieval_ms: float = Field(default=3000, gt=0)
    recovery_point_minutes: int = Field(default=15, ge=1, le=1440)
    recovery_time_minutes: int = Field(default=30, ge=1, le=1440)
    required_permissions: tuple[str, ...] = ("owner_read_write", "process_exclusive_writer")
    forbidden_legacy_paths: tuple[str, ...] = (
        "output/map_validation",
        "output/amap_validation",
        "output/bundle_cache",
        "output/intent_cache",
        "backend/app/application/sessions/session_bundle.py",
        "backend/app/infrastructure/storage/bundle_store.py",
        "backend/app/data/catalog/external_anchors.py",
        "backend/app/infrastructure/evidence_runtime/retrievers/bundle_retriever.py",
    )


class DataSecurityScanResult(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["PASS", "FAIL"]
    checked_files: int = Field(ge=0)
    permission_violations: tuple[str, ...] = ()
    secret_findings: tuple[str, ...] = ()
    legacy_path_findings: tuple[str, ...] = ()


class DataSLOMeasurement(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    admission_ms: float = Field(ge=0)
    context_bootstrap_ms: float = Field(ge=0)
    evidence_retrieval_ms: float = Field(ge=0)
    status: Literal["PASS", "FAIL"]


class DataDisasterRecoveryCheck(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    replay_status: Literal["PASS", "FAIL"]
    stale_parent_status: Literal["PASS", "FAIL"]
    invalidation_status: Literal["PASS", "FAIL"]
    provider_crash_recovery_status: Literal["PASS", "FAIL"]
    rpo_minutes: float = Field(ge=0)
    rto_minutes: float = Field(ge=0)


class DataProductionAcceptanceReport(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    status: Literal["PASS", "FAIL"]
    security: DataSecurityScanResult
    slo: DataSLOMeasurement
    disaster_recovery: DataDisasterRecoveryCheck
    wm_consumable: bool
    evidence_consumable: bool
    failures: tuple[str, ...] = ()


__all__ = [
    "DataDisasterRecoveryCheck",
    "DataProductionAcceptancePolicy",
    "DataProductionAcceptanceReport",
    "DataSecurityScanResult",
    "DataSLOMeasurement",
]
