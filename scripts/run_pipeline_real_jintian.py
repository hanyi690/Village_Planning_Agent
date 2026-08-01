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

from scripts.experiments.framework.config import (
    DEFAULT_CONSTRAINTS,
    DEFAULT_TASK_DESCRIPTION,
    JINTIAN_VILLAGE_DATA,
    ensure_cascade_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(name)s] %(levelname)s: %(message)s")


async def _open_session_kg(session_id: str) -> None:
    from app.modules.data.catalog import DataCatalog
    from app.modules.kg import open_kg_session

    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")
    bundle = await DataCatalog().load_village_bundle_async(village_name)
    snapshot = open_kg_session(
        session_id=session_id,
        village_name=bundle.village_name or village_name,
        bundle=bundle,
    )
    logger.info("[Runner] KG session opened: v%d (%d triples, cache_hit=%s)",
                snapshot.version, snapshot.triple_count, snapshot.cache_hit)


async def _run_graph(session_id: str, listener) -> None:
    """Port of scripts/experiments/cascade/baseline.py:_run_graph."""
    from app.agent.state import get_layer_dimensions, get_layer_name
    from app.database.operations import create_planning_session_async
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager
    from app.utils.sse_publisher import SSEPublisher
    from app.utils.stats_collector import StatsCollector

    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")
    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")

    stats = StatsCollector.get_instance()
    stats.start_session(session_id, "金田村规划")

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name="金田村规划",
        village_data=village_data,
        village_name=village_name,
        task_description=DEFAULT_TASK_DESCRIPTION,
        constraints=DEFAULT_CONSTRAINTS,
        session_id=session_id,
        stream_mode=True,
        step_mode=False,
    )

    await create_planning_session_async({
        "session_id": session_id,
        "project_name": "金田村规划",
        "village_data": village_data,
        "village_name": village_name,
        "task_description": DEFAULT_TASK_DESCRIPTION,
        "constraints": DEFAULT_CONSTRAINTS,
        "config": {"village_name": village_name},
    })

    sse_manager.init_session(session_id, {"session_id": session_id, "project_name": "金田村规划"})
    sse_manager.set_execution_active(session_id, True)
    await listener.connect()

    SSEPublisher.send_layer_start(
        session_id=session_id, layer=1,
        layer_name=get_layer_name(1),
        dimension_count=len(get_layer_dimensions(1)),
    )

    task = asyncio.create_task(
        PlanningRuntimeService._trigger_planning_execution(session_id, initial_state)
    )

    for layer in [1, 2, 3]:
        event = await listener.wait_for_any_event(
            event_types=["layer_completed", "error"],
            timeout=1200,
            filter_func=lambda e, l=layer: (
                e.get("type") == "error"
                or e.get("data", {}).get("layer") == l
            ),
        )
        if event.get("type") == "error":
            raise RuntimeError(f"Layer {layer} failed: {event.get('data', {}).get('message', 'unknown')}")
        logger.info("[Runner] Layer %d completed", layer)

    await task
    await listener.disconnect()


async def _summarize(session_id: str) -> Dict[str, Any]:
    from app.modules.kg.memory import load_memory_state

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


async def main(session_id: str, skip_verify: bool) -> None:
    from app.services.runtime import PlanningRuntimeService
    from scripts.experiments.framework.sse_listener import InProcessEventListener

    ensure_cascade_dirs()
    await PlanningRuntimeService.ensure_initialized()

    session_id = session_id or f"explore_kgenrich_{uuid.uuid4().hex[:8]}"
    logger.info("[Runner] session_id=%s", session_id)

    await _open_session_kg(session_id)
    listener = InProcessEventListener(session_id)
    await _run_graph(session_id, listener)
    summary = await _summarize(session_id)

    print("\n" + "=" * 60)
    print(f"[Runner] session={session_id}")
    for r, info in summary["rounds"].items():
        print(f"  round{r}: {info['annotations']} annotations {info['names']}")
    print("=" * 60)

    if not skip_verify:
        subprocess.run(
            [sys.executable, str(script_dir / "verify_explore_kgenrich.py"), "--session-id", session_id],
            check=False,
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--session-id", default="")
    parser.add_argument("--skip-verify", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.session_id or None, args.skip_verify))
