"""Real-data EXPLORE KG-enrichment runner for 金田村.

Runs the full planning graph (L1/L2/L3) with the wave-end PARSE binding
extraction enabled (completion node hook), a session KG opened up front, and
memory state persisted per round.

Usage:
    python scripts/run_pipeline_real_jintian.py [--session-id SID] [--skip-verify]
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any, Dict

script_dir = Path(__file__).resolve().parent
project_root = script_dir.parent.resolve()
backend_root = project_root / "backend"
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from scripts.runtime_support.jintian import (
    DEFAULT_CONSTRAINTS,
    DEFAULT_TASK_DESCRIPTION,
    JINTIAN_VILLAGE_DATA,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


async def _create_planning_session(session_id: str) -> None:
    """Create the session record before bundle/KG initialization.

    ``ensure_session_kg`` is snapshot-first: when a session already has a
    persisted bundle it restores that bundle, otherwise it builds one from the
    session metadata.  The old runner opened the KG before creating the
    session, which forced the first build through the village-wide catalog and
    dropped source-aware session provenance.  Keeping this small initializer
    separate also makes the ordering explicit for bounded acceptance tests.
    """
    from app.database.operations import create_planning_session_async

    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")
    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")
    await create_planning_session_async({
        "session_id": session_id,
        "project_name": "金田村规划",
        "village_data": village_data,
        "village_name": village_name,
        "task_description": DEFAULT_TASK_DESCRIPTION,
        "constraints": DEFAULT_CONSTRAINTS,
        "config": {"village_name": village_name},
    })


async def _open_session_kg(session_id: str) -> None:
    from app.infrastructure.kg.session_kg import ensure_session_kg

    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")
    snapshot = await ensure_session_kg(session_id, village_name=village_name)
    if snapshot is None:
        raise RuntimeError(f"Unable to build a non-empty session KG for {village_name}")
    logger.info("[Runner] KG session opened: v%s (%s triples, cache_hit=%s)",
                snapshot.get("version"), snapshot.get("triple_count"), snapshot.get("cache_hit"))


async def _run_graph(session_id: str, listener) -> Dict[str, Any]:
    """Run the current root graph and observe its layer events."""
    from app.workflow.layers.phase_machine import get_layer_dimensions, get_layer_name
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.workflow.plan_state.state_factory import StateFactory
    from app.infrastructure.events.sse_publisher import SSEPublisher

    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")

    initial_state = StateFactory.create(
        project_name="金田村规划",
        village_name=village_name,
        session_id=session_id,
        stream_mode=True,
        step_mode=False,
    )

    await listener.connect()

    SSEPublisher.send_layer_start(
        session_id=session_id, layer=1,
        layer_name=get_layer_name(1),
        dimension_count=len(get_layer_dimensions(1)),
    )

    task = asyncio.create_task(
        PlanningRuntimeService.trigger_planning_execution(session_id, initial_state)
    )

    try:
        for layer in [1, 2, 3]:
            event = await listener.wait_for_any_event(
                event_types=[
                    "layer_completed",
                    "error",
                    "human_review_paused",
                ],
                timeout=1200,
                filter_func=lambda e, l=layer: (
                    e.get("type") in {"error", "human_review_paused"}
                    or e.get("data", {}).get("layer") == l
                ),
            )
            event_type = event.get("type")
            if event_type == "error":
                raise RuntimeError(
                    f"Layer {layer} failed: "
                    f"{event.get('data', {}).get('message', 'unknown')}"
                )
            if event_type == "human_review_paused":
                data = event.get("data", {})
                logger.warning(
                    "[Runner] Planning paused for human review at %s",
                    data.get("paused_stage") or data.get("stage") or f"layer{layer}",
                )
                return {
                    "status": "paused",
                    "paused_stage": data.get("paused_stage") or data.get("stage"),
                    "event_id": data.get("event_id"),
                    "item_count": data.get("item_count", len(data.get("items") or [])),
                }
            logger.info("[Runner] Layer %d completed", layer)

        await task
        return {"status": "completed"}
    finally:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        await listener.disconnect()


async def _shutdown_runtime() -> None:
    """Release graph, provider, database, and KG resources before exit."""
    from app.database import dispose_async_engine, shutdown_database
    from app.infrastructure.kg.session_kg import shutdown_session_kg_process_pool
    from app.infrastructure.llm.instructor_client import close_cached_clients
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService

    cleanup_steps = (
        ("runtime tasks", PlanningRuntimeService.shutdown),
        ("provider clients", close_cached_clients),
        ("database engine", dispose_async_engine),
        ("database connections", shutdown_database),
    )
    for label, cleanup in cleanup_steps:
        try:
            await cleanup()
        except Exception:  # noqa: BLE001 - continue releasing independent resources
            logger.exception("[Runner] Failed to release %s", label)

    try:
        await asyncio.to_thread(shutdown_session_kg_process_pool)
    except Exception:  # noqa: BLE001 - process cleanup must not hide the run result
        logger.exception("[Runner] Failed to release Session KG worker pool")


async def _summarize(session_id: str) -> Dict[str, Any]:
    from app.infrastructure.kg.memory import load_memory_state

    summary: Dict[str, Any] = {"session_id": session_id, "rounds": {}}
    for round_num in [1, 2, 3]:
        store = load_memory_state(session_id, round_num)
        anns = list(store.entity_annotations.values())
        summary["rounds"][round_num] = {
            "annotations": len(anns),
            "names": sorted({a.description[:16] for a in anns if a.description}),
        }
        logger.info("[Runner] Round %d: %d annotations", round_num, len(anns))
    return summary


async def _main_impl(session_id: str, skip_verify: bool) -> None:
    from app.infrastructure.runtime.planning_runtime_service import PlanningRuntimeService
    from app.infrastructure.paths import session_run_dir
    from scripts.audit_planning_layer_quality import audit_planning_layer_quality
    from scripts.runtime_support.sse_listener import InProcessEventListener

    await PlanningRuntimeService.ensure_initialized()

    session_id = session_id or f"explore_kgenrich_{uuid.uuid4().hex[:8]}"
    logger.info("[Runner] session_id=%s", session_id)

    await _create_planning_session(session_id)
    await _open_session_kg(session_id)
    listener = InProcessEventListener(session_id)
    execution = await _run_graph(session_id, listener)
    summary = await _summarize(session_id)
    summary["execution"] = execution
    quality = audit_planning_layer_quality(session_run_dir(session_id))

    print("\n" + "=" * 60)
    print(f"[Runner] session={session_id}")
    for r, info in summary["rounds"].items():
        print(f"  round{r}: {info['annotations']} annotations {info['names']}")
    print(f"  execution_status: {execution['status']}")
    if execution["status"] == "paused":
        print(f"  paused_stage: {execution.get('paused_stage')}")
        print(f"  human_review_items: {execution.get('item_count', 0)}")
    print(f"  planning_status: {quality.status}")
    print(f"  first_zero_stage: {quality.first_zero_stage}")
    print(f"  non_baseline_feature_count: {quality.non_baseline_feature_count}")
    print(f"  planning_overlay_feature_count: {quality.planning_overlay_feature_count}")
    print(f"  artifact_files: {quality.artifact_files}")
    print("=" * 60)

    if not skip_verify:
        subprocess.run(
            [sys.executable, str(script_dir / "verify_explore_kgenrich.py"), "--session-id", session_id],
            check=False,
        )


async def main(session_id: str, skip_verify: bool) -> None:
    try:
        await _main_impl(session_id, skip_verify)
    finally:
        await _shutdown_runtime()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.session_id or None, args.skip_verify))
