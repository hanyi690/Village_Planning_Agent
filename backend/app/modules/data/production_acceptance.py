"""Executable production gates for DATA, WM, Evidence, and recovery."""

from __future__ import annotations

import os
from pathlib import Path
import re
from typing import Iterable

from app.contracts.data.production_acceptance_contracts import (
    DataDisasterRecoveryCheck,
    DataProductionAcceptancePolicy,
    DataProductionAcceptanceReport,
    DataSecurityScanResult,
    DataSLOMeasurement,
)

_SECRET_PATTERN = re.compile(
    r"(?i)(?:api[_-]?key|access[_-]?token|secret|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"
)
_TEXT_SUFFIXES = frozenset({".py", ".yaml", ".yml", ".json", ".toml", ".ini"})
_SCAN_EXCLUDED_PARTS = frozenset({
    ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules",
    ".tox", ".mypy_cache", "tests", "docs", "cache", "artifacts", "run-tmp",
    ".run-tmp", ".tmp", ".codex", ".workbuddy", ".agents", ".docx-qa",
    "graphify-out", "output",
})


def _iter_files(base: Path) -> list[Path]:
    result: list[Path] = []
    for directory, directories, filenames in os.walk(base):
        directories[:] = [name for name in directories if name not in _SCAN_EXCLUDED_PARTS]
        directory_path = Path(directory)
        result.extend(directory_path / name for name in filenames)
    return result


def scan_data_repository(
    root: str | Path,
    *,
    policy: DataProductionAcceptancePolicy | None = None,
) -> DataSecurityScanResult:
    """Scan source/artifact paths without reading provider response bodies."""

    base = Path(root).resolve()
    selected = policy or DataProductionAcceptancePolicy()
    files = _iter_files(base)
    permission_findings: list[str] = []
    secret_findings: list[str] = []
    legacy_findings: list[str] = []
    if not os.access(base, os.R_OK):
        permission_findings.append("repository:not-readable")
    if not os.access(base, os.W_OK):
        permission_findings.append("repository:not-writable")
    for forbidden in selected.forbidden_legacy_paths:
        legacy_path = base / forbidden
        if legacy_path.exists():
            legacy_findings.append(forbidden.replace("\\", "/"))
    output_root = base / "output"
    if output_root.exists():
        for path in output_root.rglob("*"):
            relative = path.relative_to(base).as_posix()
            if "cache" in path.name.casefold():
                legacy_findings.append(relative)
            if (
                path.is_dir()
                and path.name.casefold() == "bundle"
                and path.parent.name.casefold() == "inputs"
            ):
                legacy_findings.append(relative)
    for path in files:
        relative = path.relative_to(base).as_posix()
        if any(relative == item or relative.startswith(item.rstrip("/") + "/") for item in selected.forbidden_legacy_paths):
            legacy_findings.append(relative)
        try:
            mode = path.stat().st_mode
            if os.name != "nt":
                if mode & 0o002:
                    permission_findings.append(f"world-writable:{relative}")
                if mode & 0o020:
                    permission_findings.append(f"group-writable:{relative}")
        except OSError:
            permission_findings.append(f"unstatable:{relative}")
        if path.suffix.casefold() in _TEXT_SUFFIXES and path.stat().st_size <= 2_000_000:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError):
                continue
            for match in _SECRET_PATTERN.finditer(text):
                line = text.count("\n", 0, match.start()) + 1
                secret_findings.append(f"{relative}:{line}")
    status = "PASS" if not (permission_findings or secret_findings or legacy_findings) else "FAIL"
    return DataSecurityScanResult(
        status=status,
        checked_files=len(files),
        permission_violations=tuple(sorted(set(permission_findings))),
        secret_findings=tuple(sorted(set(secret_findings))),
        legacy_path_findings=tuple(sorted(set(legacy_findings))),
    )


def evaluate_production_acceptance(
    *,
    security: DataSecurityScanResult,
    policy: DataProductionAcceptancePolicy | None = None,
    admission_ms: float,
    context_bootstrap_ms: float,
    evidence_retrieval_ms: float,
    replay_status: str,
    stale_parent_status: str,
    invalidation_status: str,
    provider_crash_recovery_status: str,
    rpo_minutes: float,
    rto_minutes: float,
    wm_consumable: bool,
    evidence_consumable: bool,
) -> DataProductionAcceptanceReport:
    selected = policy or DataProductionAcceptancePolicy()
    slo_ok = (
        admission_ms <= selected.max_admission_ms
        and context_bootstrap_ms <= selected.max_context_bootstrap_ms
        and evidence_retrieval_ms <= selected.max_evidence_retrieval_ms
    )
    slo = DataSLOMeasurement(
        admission_ms=admission_ms,
        context_bootstrap_ms=context_bootstrap_ms,
        evidence_retrieval_ms=evidence_retrieval_ms,
        status="PASS" if slo_ok else "FAIL",
    )
    dr_ok = (
        replay_status == "PASS"
        and stale_parent_status == "PASS"
        and invalidation_status == "PASS"
        and provider_crash_recovery_status == "PASS"
        and rpo_minutes <= selected.recovery_point_minutes
        and rto_minutes <= selected.recovery_time_minutes
    )
    disaster_recovery = DataDisasterRecoveryCheck(
        replay_status=replay_status,
        stale_parent_status=stale_parent_status,
        invalidation_status=invalidation_status,
        provider_crash_recovery_status=provider_crash_recovery_status,
        rpo_minutes=rpo_minutes,
        rto_minutes=rto_minutes,
    )
    failures: list[str] = []
    if security.status != "PASS":
        failures.append("security_scan_failed")
    if not slo_ok:
        failures.append("slo_failed")
    if not dr_ok:
        failures.append("disaster_recovery_failed")
    if not wm_consumable:
        failures.append("world_model_not_consumable")
    if not evidence_consumable:
        failures.append("evidence_not_consumable")
    return DataProductionAcceptanceReport(
        status="PASS" if not failures else "FAIL",
        security=security,
        slo=slo,
        disaster_recovery=disaster_recovery,
        wm_consumable=wm_consumable,
        evidence_consumable=evidence_consumable,
        failures=tuple(failures),
    )


__all__ = ["evaluate_production_acceptance", "scan_data_repository"]
