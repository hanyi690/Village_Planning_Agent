"""Inspect or resume one persisted LangGraph session after process restart."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from uuid import uuid4
from pathlib import Path
from typing import Any


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    interrupt = state.get("human_interrupt") or {}
    items = list(interrupt.get("items") or state.get("human_review_items") or [])
    refs = dict(state.get("artifact_refs") or {})
    gate_routes = {}
    for key in (
        "parse_gate", "ground_gate", "select_gate", "validate_gate",
        "reconcile_gate", "deliver_gate",
    ):
        gate = state.get(key)
        if isinstance(gate, dict):
            gate_routes[key] = gate.get("feedback_route") or (
                "PASS" if gate.get("passed") is True else None
            )
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.modules.schema.contracts.workflow_contracts import GateDecision

    for stage in ("l3", "l2", "l1"):
        if not refs.get(f"{stage}_gate"):
            continue
        try:
            gate = load_artifact(state, f"{stage}_gate", GateDecision)
        except Exception:
            continue
        gate_routes[f"{stage}_gate"] = gate.feedback_route or (
            "PASS" if gate.passed is True else None
        )
    return {
        "session_id": state.get("session_id"),
        "phase": state.get("phase"),
        "current_stage": state.get("current_stage"),
        "next_stage": state.get("next_stage"),
        "paused_stage": interrupt.get("paused_stage") or state.get("paused_stage"),
        "event_id": interrupt.get("event_id") or state.get("human_review_event_id"),
        "human_review_resume_consumed": bool(state.get("human_review_resume_consumed")),
        "delivery_status": state.get("delivery_status"),
        "fatal_error": state.get("fatal_error"),
        "artifact_keys": sorted(refs),
        "artifact_refs": {
            key: {
                "digest": value.get("digest"),
                "descriptor_digest": value.get("descriptor_digest"),
                "schema_id": value.get("schema_id"),
                "schema_version": value.get("schema_version"),
                "parent_digests": value.get("parent_digests", []),
                "branch_id": value.get("branch_id"),
            }
            for key, value in sorted(refs.items())
            if isinstance(value, dict)
        },
        "gate_routes": gate_routes,
        "counts": {
            "spatial_refs": len(state.get("spatial_refs") or []),
            "remaining_targets": len(state.get("remaining_target_ids") or []),
            "deferred_targets": len(state.get("deferred_target_ids") or []),
        },
        "review_item_count": len(items),
        "review_items_preview": items[:8],
    }


async def _run(args: argparse.Namespace) -> int:
    db_path = args.database.resolve()
    run_root = args.run_root.resolve()
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    if not run_root.is_dir():
        raise FileNotFoundError(run_root)

    os.environ["BACKEND_RUN_TMP_DIR"] = str(run_root)

    import app.database.engine as engine

    engine.DB_PATH = db_path
    engine.async_engine = None
    engine.AsyncSessionLocal = None
    engine._checkpointer = None
    engine._checkpointer_initialized = False
    engine._checkpointers_by_loop.clear()

    from app.services.runtime import PlanningRuntimeService

    PlanningRuntimeService._checkpointer = None
    PlanningRuntimeService._graph = None
    import app.workflow.stages.execute as execute_stage
    execute_stage._execute_subgraph = None
    PlanningRuntimeService._initialized = False
    PlanningRuntimeService._lock = None

    try:
        await PlanningRuntimeService.initialize()
        if args.history:
            history = []
            config = PlanningRuntimeService.get_thread_config(args.session_id)
            async for historical in PlanningRuntimeService._checkpointer.alist(
                config,
                limit=args.history_limit,
            ):
                checkpoint = historical.checkpoint or {}
                values = dict(checkpoint.get("channel_values") or {})
                next_nodes = sorted(
                    key.removeprefix("branch:to:")
                    for key, value in values.items()
                    if key.startswith("branch:to:") and value is not None
                )
                history.append({
                    "checkpoint_id": (
                        historical.config.get("configurable", {}).get("checkpoint_id", "")
                    ),
                    "created_at": checkpoint.get("ts"),
                    "phase": values.get("phase"),
                    "paused_stage": values.get("paused_stage"),
                    "artifact_keys": sorted((values.get("artifact_refs") or {}).keys()),
                    "next": next_nodes,
                    "metadata": historical.metadata,
                })
            print(json.dumps({"history": history}, ensure_ascii=False, indent=2, default=str))
            return 0

        if args.checkpoint_id:
            snapshot = await PlanningRuntimeService._graph.aget_state(
                PlanningRuntimeService.get_thread_config(
                    args.session_id,
                    checkpoint_id=args.checkpoint_id,
                )
            )
        else:
            snapshot = await PlanningRuntimeService.aget_state(args.session_id)
        state = dict(snapshot.values) if snapshot and snapshot.values else {}
        if not state:
            print(json.dumps({"error": "checkpoint_not_found"}, ensure_ascii=False))
            return 2
        from app.infrastructure.reports.report_store import ReportStore

        reports = await ReportStore.get_instance().get_layer_reports_with_sources(
            args.session_id,
            layer=3,
        )
        from app.contracts.program import PlanningClaimSet

        report_summary = {}
        for dimension, record in sorted(reports.items()):
            try:
                claim_set = PlanningClaimSet.model_validate_json(record.get("content") or "")
                report_summary[dimension] = {
                    "version": record.get("version"),
                    "report_id": record.get("report_id"),
                    "content_chars": len(record.get("content") or ""),
                    "claims": len(claim_set.claims),
                    "claims_with_evidence": sum(bool(item.evidence_refs) for item in claim_set.claims),
                    "diagnostics": list(claim_set.diagnostics),
                }
            except Exception as exc:
                report_summary[dimension] = {
                    "version": record.get("version"),
                    "report_id": record.get("report_id"),
                    "content_chars": len(record.get("content") or ""),
                    "claims": 0,
                    "claims_with_evidence": 0,
                    "diagnostics": [f"invalid_planning_claim_set:{type(exc).__name__}"],
                }
        selected_report = reports.get(args.show_report) if args.show_report else None
        print(json.dumps(
            {
                "before": {
                    **_summary(state),
                    "graph_next": list(snapshot.next or ()),
                    "graph_tasks": [
                        {
                            "id": getattr(task, "id", ""),
                            "name": getattr(task, "name", ""),
                            "error": str(getattr(task, "error", "") or ""),
                            "interrupt_count": len(getattr(task, "interrupts", ()) or ()),
                        }
                        for task in (snapshot.tasks or ())
                    ],
                },
                "l3_reports": report_summary,
                "selected_report": selected_report,
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        ))

        if args.continue_run:
            if not snapshot.next:
                raise RuntimeError("the latest checkpoint has no pending graph node")
            has_pending_interrupt = any(
                getattr(task, "interrupts", ())
                for task in (snapshot.tasks or ())
            )
            if has_pending_interrupt:
                raise RuntimeError("active HUMAN checkpoints require --action and --event-id")
            from app.infrastructure.kg.session_kg import ensure_session_kg

            raw_version = (state.get("context_ref") or {}).get("version") or state.get("context_version")
            bundle_version = int(raw_version) if str(raw_version or "").isdigit() else None
            await ensure_session_kg(
                args.session_id,
                force=bundle_version is not None,
                bundle_version=bundle_version,
            )
            await PlanningRuntimeService._trigger_planning_execution(
                args.session_id,
                checkpoint_id=args.checkpoint_id,
                state_values=state,
                replay_from_stage=args.replay_from_stage,
                branch_id=args.branch_id or f"resume-{uuid4().hex[:16]}",
            )
            continued = await PlanningRuntimeService.aget_state_values(args.session_id) or {}
            print(json.dumps({"after": _summary(continued)}, ensure_ascii=False, indent=2, default=str))
            return 0

        if args.action is None:
            return 0

        interrupt = state.get("human_interrupt") or {}
        event_id = args.event_id or interrupt.get("event_id") or state.get("human_review_event_id")
        if not event_id:
            raise RuntimeError("the active checkpoint has no HUMAN event_id")
        decision = {
            "action": args.action,
            "feedback": args.feedback,
            "dimensions": list(args.dimensions or []),
        }
        if args.deferred_target_ids:
            decision.update({
                "acknowledge_unresolved_spatial_references": True,
                "defer_unresolved_spatial_references": True,
                "deferred_target_ids": list(dict.fromkeys(args.deferred_target_ids)),
            })
        await PlanningRuntimeService.resume_from_interrupt(
            args.session_id,
            decision,
            expected_event_id=str(event_id),
        )
        resumed = await PlanningRuntimeService.aget_state_values(args.session_id) or {}
        print(json.dumps({"after": _summary(resumed)}, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        await engine.shutdown_database()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", required=True, type=Path)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--action", choices=("approve", "retry", "reject"))
    parser.add_argument("--event-id")
    parser.add_argument("--feedback", default="operator checkpoint resume")
    parser.add_argument("--dimensions", nargs="*", default=[])
    parser.add_argument("--deferred-target-ids", nargs="*", default=[])
    parser.add_argument("--show-report")
    parser.add_argument("--continue-run", action="store_true")
    parser.add_argument("--checkpoint-id")
    parser.add_argument("--replay-from-stage")
    parser.add_argument(
        "--branch-id",
        help="new immutable artifact branch for historical checkpoint continuation",
    )
    parser.add_argument("--history", action="store_true")
    parser.add_argument("--history-limit", type=int, default=80)
    return parser


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_run(_parser().parse_args())))
