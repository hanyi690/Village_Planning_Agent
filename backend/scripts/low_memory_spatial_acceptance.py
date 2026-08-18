"""Run or audit a bounded spatial replay without touching the live database.

This entry point is intentionally conservative.  A replay is an optional,
explicit operation; the default is a read-only preflight.  Checkpoint and
business databases must be clones below the configured size limit and the
business database must live below ``.run-tmp``.  The script never starts the
full Explore graph and only starts the existing checkpoint-resume entry point
when ``--execute-replay`` is supplied.

The child process is terminated in ``finally`` (including its descendants),
so a failed bounded replay cannot leave an old backend process consuming
memory.  The script never terminates unrelated Python or uvicorn processes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import signal
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Sequence


PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = PROJECT_ROOT / "backend"
RUN_TMP_ROOT = PROJECT_ROOT / ".run-tmp"
RESUME_SCRIPT = BACKEND_ROOT / "scripts" / "resume_graph_checkpoint.py"
DEFAULT_MAX_DB_BYTES = 2 * 1024 * 1024 * 1024

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))


class LowMemoryAcceptanceError(RuntimeError):
    """Raised when a replay would violate the bounded-run safety contract."""


@dataclass(frozen=True)
class ReplayPreflight:
    status: str
    checkpoint_db: str
    business_db: str
    run_root: str
    checkpoint_bytes: int = 0
    business_bytes: int = 0
    max_database_bytes: int = DEFAULT_MAX_DB_BYTES
    violations: list[str] = field(default_factory=list)
    active_backend_processes: list[dict[str, Any]] = field(default_factory=list)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ReplayResult:
    status: str
    command: list[str]
    returncode: int | None
    stdout: str = ""
    stderr: str = ""
    summary: dict[str, Any] | None = None
    cleanup: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class SourceAwarePreflight:
    """Read-only readiness report for a source-backed delivery branch.

    This report deliberately sits before the graph runner.  It proves that a
    run has an explicit source bundle and that the three delivery artifacts
    used by the map projection resolve from one CAS root.  It never opens a
    database and never constructs a KG or starts a workflow process.
    """

    status: str
    run_root: str
    source_bundle: str
    source_digest: str = ""
    source_files: list[dict[str, Any]] = field(default_factory=list)
    source_point_count: int = 0
    source_line_count: int = 0
    delivery_status: str = ""
    delivery_ref_keys: list[str] = field(default_factory=list)
    delivery_cas_root: str = ""
    planning_overlay_feature_count: int = 0
    non_baseline_feature_count: int = 0
    violations: list[str] = field(default_factory=list)
    deferred_reasons: list[str] = field(default_factory=list)
    audit: dict[str, Any] = field(default_factory=dict)

    def model_dump(self) -> dict[str, Any]:
        return asdict(self)


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _active_backend_processes() -> list[dict[str, Any]]:
    """List likely stale backend processes without changing process state.

    ``psutil`` is optional in the application environment.  If unavailable,
    preflight remains safe and simply omits this advisory list.
    """

    try:
        import psutil  # type: ignore
    except ImportError:
        return []
    result: list[dict[str, Any]] = []
    current_pid = os.getpid()
    for process in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            pid = int(process.info.get("pid") or 0)
            if pid == current_pid:
                continue
            name = str(process.info.get("name") or "").lower()
            cmdline = " ".join(str(item) for item in (process.info.get("cmdline") or []))
            text = f"{name} {cmdline}".lower()
            if not any(token in text for token in (
                "uvicorn", "resume_graph_checkpoint", "run_pipeline_real_jintian",
            )):
                continue
            result.append({"pid": pid, "name": name, "cmdline": cmdline})
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return result


def preflight_replay(
    checkpoint_db: Path,
    business_db: Path,
    run_root: Path,
    *,
    max_database_bytes: int = DEFAULT_MAX_DB_BYTES,
    require_run_tmp: bool = True,
    inspect_processes: bool = True,
) -> ReplayPreflight:
    """Validate a bounded replay using filesystem metadata only.

    No SQLite connection is opened here.  In particular, a live
    ``data/database/village_planning.db`` is rejected before the application
    imports its database engine.
    """

    checkpoint_db = Path(checkpoint_db).resolve()
    business_db = Path(business_db).resolve()
    run_root = Path(run_root).resolve()
    violations: list[str] = []

    if max_database_bytes <= 0:
        violations.append("max_database_bytes must be positive")
    if not checkpoint_db.is_file():
        violations.append("checkpoint database does not exist")
    if not business_db.is_file():
        violations.append("business database does not exist")
    if not run_root.is_dir():
        violations.append("run root does not exist or is not a directory")
    if checkpoint_db == business_db:
        violations.append("checkpoint and business databases must be separate clones")
    if require_run_tmp and not _within(run_root, RUN_TMP_ROOT):
        violations.append("run root must be below .run-tmp")
    if require_run_tmp and not _within(business_db, RUN_TMP_ROOT):
        violations.append("business database must be below .run-tmp; live DB is forbidden")
    if _within(business_db, PROJECT_ROOT / "data" / "database"):
        violations.append("live data/database path is forbidden")
    if business_db.name.lower() == "village_planning.db" and not _within(business_db, RUN_TMP_ROOT):
        violations.append("village_planning.db outside .run-tmp is forbidden")

    checkpoint_bytes = 0
    business_bytes = 0
    if checkpoint_db.is_file():
        checkpoint_bytes = checkpoint_db.stat().st_size
        if checkpoint_bytes > max_database_bytes:
            violations.append(
                f"checkpoint database exceeds limit: {checkpoint_bytes} > {max_database_bytes}"
            )
    if business_db.is_file():
        business_bytes = business_db.stat().st_size
        if business_bytes > max_database_bytes:
            violations.append(
                f"business database exceeds limit: {business_bytes} > {max_database_bytes}"
            )

    active = _active_backend_processes() if inspect_processes else []
    return ReplayPreflight(
        status="ready" if not violations else "rejected",
        checkpoint_db=str(checkpoint_db),
        business_db=str(business_db),
        run_root=str(run_root),
        checkpoint_bytes=checkpoint_bytes,
        business_bytes=business_bytes,
        max_database_bytes=max_database_bytes,
        violations=violations,
        active_backend_processes=active,
    )


def _terminate_process_tree(process: subprocess.Popen[str]) -> dict[str, Any]:
    """Terminate only the process tree owned by one bounded replay child."""

    pid = int(process.pid)
    details: dict[str, Any] = {"pid": pid, "terminated": False, "method": None}
    try:
        import psutil  # type: ignore
    except ImportError:
        psutil = None  # type: ignore[assignment]

    if psutil is not None:
        try:
            parent = psutil.Process(pid)
            children = parent.children(recursive=True)
            for child in reversed(children):
                child.terminate()
            parent.terminate()
            _, alive = psutil.wait_procs([*children, parent], timeout=3)
            for child in alive:
                child.kill()
            details.update({
                "terminated": True,
                "method": "psutil_process_tree",
                "remaining": [int(item.pid) for item in alive],
            })
            return details
        except (psutil.NoSuchProcess, psutil.Error, OSError):
            details["method"] = "psutil_process_tree_already_gone"
            details["terminated"] = True
            return details

    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T", "/F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            details["method"] = "taskkill_child_tree"
        else:
            os.killpg(pid, signal.SIGTERM)
            details["method"] = "process_group"
        details["terminated"] = True
    except (OSError, ValueError):
        details["method"] = "already_gone"
        details["terminated"] = True
    return details


def _last_json_document(text: str) -> dict[str, Any] | None:
    decoder = json.JSONDecoder()
    candidate: dict[str, Any] | None = None
    candidate_end = -1
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, end = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        absolute_end = index + end
        if absolute_end > candidate_end and isinstance(value, dict):
            candidate = value
            candidate_end = absolute_end
    return candidate


def run_bounded_replay(
    command: Sequence[str],
    *,
    cwd: Path = PROJECT_ROOT,
    timeout_seconds: int = 900,
) -> ReplayResult:
    """Run one explicitly prepared replay command and always clean it up."""

    child: subprocess.Popen[str] | None = None
    cleanup: dict[str, Any] = {"terminated": False, "method": None}
    try:
        creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        child = subprocess.Popen(
            list(command),
            cwd=str(cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=creationflags if os.name == "nt" else 0,
            start_new_session=os.name != "nt",
        )
        try:
            stdout, stderr = child.communicate(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            cleanup = _terminate_process_tree(child)
            stdout, stderr = child.communicate(timeout=10)
            return ReplayResult(
                status="timeout",
                command=list(command),
                returncode=child.returncode,
                stdout=stdout,
                stderr=stderr or str(exc),
                summary=_last_json_document(stdout),
                cleanup=cleanup,
                error=f"bounded replay exceeded {timeout_seconds}s",
            )
        cleanup = _terminate_process_tree(child)
        return ReplayResult(
            status="passed" if child.returncode == 0 else "failed",
            command=list(command),
            returncode=child.returncode,
            stdout=stdout,
            stderr=stderr,
            summary=_last_json_document(stdout),
            cleanup=cleanup,
        )
    except OSError as exc:
        if child is not None:
            cleanup = _terminate_process_tree(child)
        return ReplayResult(
            status="failed",
            command=list(command),
            returncode=child.returncode if child is not None else None,
            cleanup=cleanup,
            error=f"could not start replay: {exc}",
        )
    finally:
        if child is not None and child.poll() is None:
            cleanup = _terminate_process_tree(child)


def build_resume_command(
    *,
    checkpoint_db: Path,
    business_db: Path,
    run_root: Path,
    session_id: str,
    checkpoint_id: str | None,
    event_id: str | None = None,
    action: str | None = None,
    feedback: str = "operator checkpoint resume",
    replay_from_stage: str,
    subgraph_entry: str,
    branch_id: str,
    deferred_target_ids: Sequence[str] = (),
    disable_ground_report_llm: bool = True,
) -> list[str]:
    command = [
        sys.executable,
        str(RESUME_SCRIPT),
        "--database",
        str(checkpoint_db),
        "--business-database",
        str(business_db),
        "--run-root",
        str(run_root),
        "--session-id",
        session_id,
        "--replay-from-stage",
        replay_from_stage,
        "--subgraph-entry",
        subgraph_entry,
        "--branch-id",
        branch_id,
    ]
    if not action:
        command.insert(2, "--continue-run")
    if action:
        command.extend(["--action", action, "--feedback", feedback])
    if event_id:
        command.extend(["--event-id", event_id])
    if checkpoint_id:
        command.extend(["--checkpoint-id", checkpoint_id])
    if disable_ground_report_llm:
        command.append("--disable-ground-report-llm")
    if deferred_target_ids:
        command.append("--deferred-target-ids")
        command.extend(str(item) for item in deferred_target_ids if str(item).strip())
    return command


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint-db", type=Path)
    parser.add_argument("--business-database", type=Path)
    parser.add_argument("--run-root", type=Path)
    parser.add_argument("--session-id")
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--event-id")
    parser.add_argument("--action", choices=("approve", "retry", "reject"))
    parser.add_argument("--feedback", default="operator checkpoint resume")
    parser.add_argument("--branch-id", default="low-memory-acceptance")
    parser.add_argument("--deferred-target-ids", nargs="*", default=[])
    parser.add_argument("--replay-from-stage", default="target_projection")
    parser.add_argument("--subgraph-entry", default="target_projection")
    parser.add_argument("--max-database-bytes", type=int, default=DEFAULT_MAX_DB_BYTES)
    parser.add_argument("--timeout-seconds", type=int, default=900)
    parser.add_argument("--execute-replay", action="store_true")
    parser.add_argument("--preflight-only", action="store_true")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--audit-run-dir", type=Path)
    parser.add_argument("--allow-external-run-root", action="store_true")
    parser.add_argument("--allow-incomplete-hard-relations", action="store_true")
    args = parser.parse_args(argv)

    if args.audit_run_dir:
        from scripts.audit_planning_layer_quality import audit_planning_layer_quality

        report = audit_planning_layer_quality(
            args.audit_run_dir,
            require_complete_hard_relations=not args.allow_incomplete_hard_relations,
        )
        payload = {"mode": "artifact_audit", **report.model_dump()}
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        if args.report:
            _write_report(args.report, payload)
        return 0 if report.status in {"ready", "complete"} else 2

    required = {
        "checkpoint-db": args.checkpoint_db,
        "business-database": args.business_database,
        "run-root": args.run_root,
        "session-id": args.session_id,
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        parser.error("missing required replay arguments: " + ", ".join(missing))

    preflight = preflight_replay(
        args.checkpoint_db,
        args.business_database,
        args.run_root,
        max_database_bytes=args.max_database_bytes,
        require_run_tmp=not args.allow_external_run_root,
    )
    payload: dict[str, Any] = {
        "mode": "preflight",
        "preflight": preflight.model_dump(),
    }
    if preflight.status != "ready" or not args.execute_replay:
        payload["status"] = preflight.status if preflight.status != "ready" else "preflight_only"
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        if args.report:
            _write_report(args.report, payload)
        return 2 if preflight.status != "ready" else 0

    command = build_resume_command(
        checkpoint_db=args.checkpoint_db,
        business_db=args.business_database,
        run_root=args.run_root,
        session_id=args.session_id,
        checkpoint_id=args.checkpoint_id,
        event_id=args.event_id,
        action=args.action,
        feedback=args.feedback,
        replay_from_stage=args.replay_from_stage,
        subgraph_entry=args.subgraph_entry,
        branch_id=args.branch_id,
        deferred_target_ids=args.deferred_target_ids,
    )
    replay = run_bounded_replay(command, timeout_seconds=args.timeout_seconds)
    payload.update({"status": replay.status, "replay": replay.model_dump()})
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    if args.report:
        _write_report(args.report, payload)
    return 0 if replay.status == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
