from __future__ import annotations

from pathlib import Path

from app.contracts.data.production_acceptance_contracts import (
    DataProductionAcceptancePolicy,
    DataSecurityScanResult,
)
from app.modules.data.production_acceptance import (
    evaluate_production_acceptance,
    scan_data_repository,
)


def test_security_scan_rejects_legacy_paths_and_secrets(tmp_path: Path) -> None:
    (tmp_path / "safe.py").write_text("value = 1\n", encoding="utf-8")
    (tmp_path / "output" / "map_validation").mkdir(parents=True)
    (tmp_path / "output" / "map_validation" / "old.json").write_text("{}", encoding="utf-8")
    (tmp_path / "config.py").write_text('api_key = "not-a-real-secret-value"\n', encoding="utf-8")
    result = scan_data_repository(tmp_path)
    assert result.status == "FAIL"
    assert result.legacy_path_findings
    assert result.secret_findings


def test_security_scan_rejects_any_output_cache_or_legacy_bundle_input(tmp_path: Path) -> None:
    (tmp_path / "output" / "run" / "l3-projection-cache").mkdir(parents=True)
    (tmp_path / "output" / "run" / "inputs" / "bundle").mkdir(parents=True)

    result = scan_data_repository(tmp_path)

    assert result.status == "FAIL"
    assert "output/run/l3-projection-cache" in result.legacy_path_findings
    assert "output/run/inputs/bundle" in result.legacy_path_findings


def test_production_acceptance_requires_all_consumers_and_recovery() -> None:
    security = DataSecurityScanResult(status="PASS", checked_files=1)
    report = evaluate_production_acceptance(
        security=security,
        policy=DataProductionAcceptancePolicy(),
        admission_ms=10,
        context_bootstrap_ms=20,
        evidence_retrieval_ms=30,
        replay_status="PASS",
        stale_parent_status="PASS",
        invalidation_status="PASS",
        provider_crash_recovery_status="PASS",
        rpo_minutes=1,
        rto_minutes=2,
        wm_consumable=True,
        evidence_consumable=True,
    )
    assert report.status == "PASS"


def test_production_acceptance_fails_closed_on_slo_or_recovery() -> None:
    security = DataSecurityScanResult(status="PASS", checked_files=1)
    report = evaluate_production_acceptance(
        security=security,
        admission_ms=10_000,
        context_bootstrap_ms=20,
        evidence_retrieval_ms=30,
        replay_status="PASS",
        stale_parent_status="FAIL",
        invalidation_status="PASS",
        provider_crash_recovery_status="PASS",
        rpo_minutes=1,
        rto_minutes=2,
        wm_consumable=True,
        evidence_consumable=True,
    )
    assert report.status == "FAIL"
    assert set(report.failures) == {"slo_failed", "disaster_recovery_failed"}
