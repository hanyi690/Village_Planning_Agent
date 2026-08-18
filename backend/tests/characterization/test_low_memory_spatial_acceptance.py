from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from backend.scripts.low_memory_spatial_acceptance import (
    DEFAULT_MAX_DB_BYTES,
    _last_json_document,
    build_resume_command,
    main,
    preflight_replay,
    run_bounded_replay,
)


def _db(path: Path, size: int = 128) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as handle:
        handle.truncate(size)
    return path


def test_preflight_rejects_large_business_clone_without_opening_sqlite(tmp_path: Path) -> None:
    checkpoint = _db(tmp_path / "checkpoints.db")
    business = _db(tmp_path / "village_planning.db", DEFAULT_MAX_DB_BYTES + 1)
    run_root = tmp_path / ".run-tmp" / "acceptance"
    run_root.mkdir(parents=True)

    result = preflight_replay(
        checkpoint,
        business,
        run_root,
        inspect_processes=False,
        require_run_tmp=False,
    )

    assert result.status == "rejected"
    assert any("business database exceeds limit" in item for item in result.violations)


def test_preflight_rejects_live_data_database_path(tmp_path: Path) -> None:
    checkpoint = _db(tmp_path / "checkpoints.db")
    live_root = tmp_path / "data" / "database"
    live_root.mkdir(parents=True)
    business = _db(live_root / "village_planning.db")
    run_root = tmp_path / ".run-tmp" / "acceptance"
    run_root.mkdir(parents=True)

    result = preflight_replay(
        checkpoint,
        business,
        run_root,
        inspect_processes=False,
        require_run_tmp=False,
    )

    assert result.status == "rejected"
    assert any(
        item in result.violations
        for item in (
            "live data/database path is forbidden",
            "village_planning.db outside .run-tmp is forbidden",
        )
    )


def test_resume_command_uses_clone_paths_and_never_defaults_to_live_db(tmp_path: Path) -> None:
    command = build_resume_command(
        checkpoint_db=tmp_path / "checkpoints.db",
        business_db=tmp_path / "business.db",
        run_root=tmp_path / "run",
        session_id="session-1",
        checkpoint_id="checkpoint-1",
        replay_from_stage="target_projection",
        subgraph_entry="target_projection",
        branch_id="resume-low-memory",
    )

    assert "--business-database" in command
    assert str(tmp_path / "business.db") in command
    assert "data/database/village_planning.db" not in " ".join(command)
    assert "--disable-ground-report-llm" in command


def test_child_replay_is_cleaned_up_in_finally(tmp_path: Path) -> None:
    marker = tmp_path / "child-finished"
    code = (
        "import time; "
        f"open({str(marker)!r}, 'w').write('started'); "
        "time.sleep(30)"
    )
    result = run_bounded_replay(
        [sys.executable, "-c", code],
        cwd=tmp_path,
        timeout_seconds=1,
    )

    assert result.status == "timeout"
    assert result.cleanup["terminated"] is True
    assert result.returncode is not None
    assert marker.is_file()


def test_last_json_document_reads_pretty_resume_output() -> None:
    text = "log line\n" + json.dumps({"before": {"count": 1}}, indent=2)
    text += "\n" + json.dumps({"after": {"count": 2}}, indent=2)

    assert _last_json_document(text) == {"after": {"count": 2}}


def test_artifact_audit_writes_requested_report(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    report_path = tmp_path / "audit.json"

    # A missing run has a deterministic no-planning result, but the CLI must
    # still persist it when --report is requested so acceptance never relies
    # on transient stdout.
    exit_code = main([
        "--audit-run-dir", str(run_dir / "missing-branch"),
        "--report", str(report_path),
    ])

    assert exit_code == 2
    payload = json.loads(report_path.read_text(encoding="utf-8"))
    assert payload["mode"] == "artifact_audit"
    assert payload["status"] == "no_planning_output"
