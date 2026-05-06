"""
Baseline Run Script
基线运行脚本

启动完整规划流程，等待全部28维度生成完成，保存报告和检查点历史。

使用方法:
    python scripts/experiments/run_baseline.py [--timeout 1800]

输出:
    - baseline/session_id.json
    - baseline/layer1_reports.json
    - baseline/layer2_reports.json
    - baseline/layer3_reports.json
    - baseline/checkpoints.json
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    BASELINE_DIR,
    JINTIAN_VILLAGE_DATA,
    ensure_output_dirs,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Mock Planning Runtime (for testing)
# ============================================

async def mock_run_planning_flow(project_name: str, village_data: Dict, timeout: int = 1800) -> Dict[str, Any]:
    """
    Mock planning flow execution for testing.

    In production, this would call PlanningRuntimeService.start_session.
    For testing, we use a simulated flow that reads existing reports.

    Args:
        project_name: Project name
        village_data: Village configuration data
        timeout: Maximum wait time in seconds

    Returns:
        Session state with reports and completion status
    """
    logger.info(f"[Baseline] Starting mock planning flow: {project_name}")

    # Try to load existing jintian reports (fallback for testing)
    reports_dir = Path(__file__).parent.parent.parent / "docs"

    reports = {"layer1": {}, "layer2": {}, "layer3": {}}
    completed_dimensions = {"layer1": [], "layer2": [], "layer3": []}

    # Load layer reports if available
    for layer in [1, 2, 3]:
        report_path = reports_dir / f"layer{layer}_完整报告.md"
        if report_path.exists():
            with open(report_path, "r", encoding="utf-8") as f:
                content = f.read()
            # Store as a single dimension for now (mock)
            reports[f"layer{layer}"]["full_report"] = content
            completed_dimensions[f"layer{layer}"] = ["full_report"]
            logger.info(f"[Baseline] Loaded layer{layer} report: {len(content)} chars")

    # Generate session ID
    session_id = f"baseline_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    return {
        "session_id": session_id,
        "project_name": project_name,
        "phase": "completed",
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        "pause_after_step": False,
    }


async def run_planning_runtime(project_name: str, village_data: Dict, timeout: int = 1800) -> Dict[str, Any]:
    """
    Run actual planning flow using PlanningRuntimeService.

    Args:
        project_name: Project name
        village_data: Village configuration data
        timeout: Maximum wait time in seconds

    Returns:
        Session state with reports and completion status
    """
    from backend.services.planning_runtime_service import PlanningRuntimeService

    logger.info(f"[Baseline] Starting planning runtime: {project_name}")

    # Start session (step_mode=False for automatic progression)
    session_id = await PlanningRuntimeService.start_session(
        project_name=project_name,
        village_data=village_data.get("village_name", "金田村"),
        step_mode=False,  # Auto-progress through layers
    )

    logger.info(f"[Baseline] Session started: {session_id}")

    # Wait for completion
    state = await wait_for_completion(session_id, timeout)

    return {
        "session_id": session_id,
        "project_name": project_name,
        **state,
    }


async def wait_for_completion(session_id: str, timeout: int = 1800) -> Dict[str, Any]:
    """
    Wait for planning session to complete all layers.

    Args:
        session_id: Session identifier
        timeout: Maximum wait time in seconds

    Returns:
        Final state snapshot
    """
    from backend.services.checkpoint_service import checkpoint_service

    logger.info(f"[Baseline] Waiting for completion (timeout={timeout}s)")

    start_time = datetime.now()
    check_interval = 10  # seconds

    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout:
            logger.warning(f"[Baseline] Timeout reached after {elapsed}s")
            break

        state = await checkpoint_service.get_state(session_id)
        if state:
            phase = state.get("phase", "init")
            logger.info(f"[Baseline] Current phase: {phase} (elapsed={elapsed:.0f}s)")

            # Check if all layers completed
            if phase == "completed":
                logger.info("[Baseline] All layers completed!")
                return state

        await asyncio.sleep(check_interval)

    # Return last known state
    return await checkpoint_service.get_state(session_id) or {}


# ============================================
# Report Saving
# ============================================

def save_reports(state: Dict[str, Any], output_dir: Path):
    """
    Save reports to output directory.

    Args:
        state: Session state
        output_dir: Output directory path
    """
    session_id = state.get("session_id", "unknown")
    reports = state.get("reports", {})
    completed_dimensions = state.get("completed_dimensions", {})

    # Save session metadata
    session_meta = {
        "session_id": session_id,
        "project_name": state.get("project_name", ""),
        "phase": state.get("phase", ""),
        "created_at": datetime.now().isoformat(),
    }
    with open(output_dir / "session_id.json", "w", encoding="utf-8") as f:
        json.dump(session_meta, f, indent=2, ensure_ascii=False)
    logger.info(f"[Baseline] Saved session_id.json")

    # Save layer reports
    for layer in [1, 2, 3]:
        layer_key = f"layer{layer}"
        layer_reports = reports.get(layer_key, {})
        layer_completed = completed_dimensions.get(layer_key, [])

        layer_data = {
            "layer": layer,
            "reports": layer_reports,
            "completed_dimensions": layer_completed,
            "report_count": len(layer_reports),
            "total_chars": sum(len(v) for v in layer_reports.values()) if layer_reports else 0,
        }
        with open(output_dir / f"layer{layer}_reports.json", "w", encoding="utf-8") as f:
            json.dump(layer_data, f, indent=2, ensure_ascii=False)
        logger.info(f"[Baseline] Saved layer{layer}_reports.json: {len(layer_reports)} dimensions")

    # Save checkpoints summary
    checkpoints_summary = {
        "session_id": session_id,
        "collected_at": datetime.now().isoformat(),
        "note": "Checkpoint history should be extracted from database",
    }
    with open(output_dir / "checkpoints.json", "w", encoding="utf-8") as f:
        json.dump(checkpoints_summary, f, indent=2, ensure_ascii=False)


# ============================================
# Main Entry Point
# ============================================

async def run_baseline(timeout: int = 1800, use_mock: bool = False):
    """
    Run baseline experiment.

    Args:
        timeout: Maximum wait time in seconds
        use_mock: Whether to use mock data (for testing without full runtime)
    """
    ensure_output_dirs()

    project_name = "金田村基线实验"

    logger.info("=" * 60)
    logger.info("[Baseline] Starting baseline experiment")
    logger.info("=" * 60)

    try:
        if use_mock:
            state = await mock_run_planning_flow(
                project_name=project_name,
                village_data=JINTIAN_VILLAGE_DATA,
                timeout=timeout,
            )
        else:
            state = await run_planning_runtime(
                project_name=project_name,
                village_data=JINTIAN_VILLAGE_DATA,
                timeout=timeout,
            )

        # Save reports
        save_reports(state, BASELINE_DIR)

        logger.info("=" * 60)
        logger.info("[Baseline] Baseline experiment completed")
        logger.info(f"[Baseline] Session ID: {state.get('session_id', 'unknown')}")
        logger.info("=" * 60)

        return state

    except Exception as e:
        logger.error(f"[Baseline] Failed: {e}", exc_info=True)
        raise


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Run baseline experiment")
    parser.add_argument("--timeout", type=int, default=1800, help="Timeout in seconds")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing")
    args = parser.parse_args()

    asyncio.run(run_baseline(timeout=args.timeout, use_mock=args.mock))


if __name__ == "__main__":
    main()