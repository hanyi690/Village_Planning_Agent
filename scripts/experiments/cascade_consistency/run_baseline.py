"""
Baseline Runner - Generate baseline reports for cascade experiment
基线运行器 - 为级联实验生成基线报告

运行完整的规划流程，生成28维度报告作为实验基线。

参考 run_4group_experiment.py 的进程内直接执行 + SSE 事件驱动模式。

Usage:
    python scripts/experiments/cascade_consistency/run_baseline.py
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any

script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent.parent.resolve()
backend_root = (project_root / "backend").resolve()
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

from scripts.experiments.config import (
    BASELINE_DIR,
    JINTIAN_VILLAGE_DATA,
    DEFAULT_TASK_DESCRIPTION,
    DEFAULT_CONSTRAINTS,
    ensure_cascade_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


async def _run_graph(session_id: str, listener) -> str:
    """进程内直接执行规划图，事件驱动等待"""
    from app.services.runtime import PlanningRuntimeService
    from app.services.sse import sse_manager
    from app.utils.sse_publisher import SSEPublisher
    from app.agent.state import get_layer_dimensions, get_layer_name

    village_data = JINTIAN_VILLAGE_DATA.get("status_report", "")
    village_name = JINTIAN_VILLAGE_DATA.get("village_name", "金田村")

    initial_state = PlanningRuntimeService.build_initial_state(
        project_name="金田村基线实验",
        village_data=village_data,
        village_name=village_name,
        task_description=DEFAULT_TASK_DESCRIPTION,
        constraints=DEFAULT_CONSTRAINTS,
        session_id=session_id,
        stream_mode=True,
        step_mode=False,
    )

    sse_manager.init_session(session_id, {
        "session_id": session_id,
        "project_name": "金田村基线实验",
    })
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

    logger.info("[Baseline] Graph execution started (SSE-driven)")

    for layer in [1, 2, 3]:
        event = await listener.wait_for_any_event(
            event_types=["layer_completed", "error"],
            timeout=900,
            filter_func=lambda e, l=layer: (
                e.get("type") == "error"
                or e.get("data", {}).get("layer") == l
            ),
        )
        if event.get("type") == "error":
            raise RuntimeError(f"Layer {layer} failed: {event.get('data', {}).get('message', 'unknown')}")
        logger.info(f"[Baseline] Layer {layer} completed")

    await task
    await listener.disconnect()
    return session_id


async def run_baseline() -> Dict[str, str]:
    from app.services.runtime import PlanningRuntimeService
    from app.services.report_store import ReportStore
    from scripts.experiments.sse_listener import InProcessEventListener

    ensure_cascade_dirs()
    await PlanningRuntimeService.ensure_initialized()

    session_id = f"baseline_{uuid.uuid4().hex[:8]}"
    listener = InProcessEventListener(session_id)

    logger.info(f"[Baseline] Starting: {session_id}")
    await _run_graph(session_id, listener)
    logger.info("[Baseline] Execution complete")

    store = ReportStore.get_instance()
    reports = {}
    for layer in [1, 2, 3]:
        layer_reports = await store.get_layer_reports(session_id, layer)
        reports.update(layer_reports)

    logger.info(f"[Baseline] Retrieved {len(reports)} dimension reports")

    baseline = await PlanningRuntimeService.aget_state(session_id)
    checkpoint_id = baseline.config["configurable"].get("checkpoint_id", "") if baseline else ""

    save_baseline(reports, session_id, checkpoint_id)
    return reports


def save_baseline(reports: Dict[str, str], session_id: str, checkpoint_id: str = ""):
    baseline_file = BASELINE_DIR / "baseline_reports.json"
    baseline_file.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "session_id": session_id,
        "checkpoint_id": checkpoint_id,
        "generated_at": datetime.now().isoformat(),
        "dimension_count": len(reports),
        "reports": reports,
    }

    with open(baseline_file, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"[Baseline] Saved to {baseline_file}")


def main():
    logger.info("=" * 60)
    logger.info("[Baseline] Running baseline experiment")
    logger.info("=" * 60)

    reports = asyncio.run(run_baseline())

    print("\n" + "=" * 60)
    print(f"基线报告生成完成: {len(reports)} 维度")
    print("=" * 60)

    for dim, content in sorted(reports.items()):
        print(f"  {dim}: {len(content)} 字符")


if __name__ == "__main__":
    main()
