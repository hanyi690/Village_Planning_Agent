"""
Baseline Run Script
基线运行脚本

启动完整规划流程，等待全部28维度生成完成，保存报告和检查点历史。

性能优化（SSE模式）：
- 使用 SSE 事件驱动替代轮询，实现与前端一致的响应速度
- 无 step_mode 暂停开销，自动推进

使用方法:
    python scripts/experiments/run_baseline.py [--timeout 1800]
    python scripts/experiments/run_baseline.py --use-polling  # 使用轮询模式（后备）

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
from scripts.experiments.layer_checkpoint_utils import (
    wait_for_all_layers,
    save_all_layer_checkpoints,
    compute_state_fingerprint,
    save_layer_checkpoint,
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
    from starlette.background import BackgroundTasks

    logger.info(f"[Baseline] Starting planning runtime: {project_name}")

    # Create BackgroundTasks for script mode
    background_tasks = BackgroundTasks()

    # Start session (step_mode=False for automatic progression)
    # Pass full status report content, not just village name
    result = await PlanningRuntimeService.start_session(
        project_name=project_name,
        village_data=village_data.get("status_report", ""),
        village_name=village_data.get("village_name", "金田村"),
        step_mode=False,  # Auto-progress through layers
        background_tasks=background_tasks,
    )

    session_id = result.get("task_id")
    logger.info(f"[Baseline] Session started: {session_id}")

    # Execute background tasks manually (since we're not in FastAPI context)
    await background_tasks()

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


async def run_planning_runtime_with_layer_checkpoints(
    project_name: str,
    village_data: Dict,
    output_dir: Path,
    timeout_per_layer: int = 600,
    use_sse: bool = True,
) -> Dict[str, Any]:
    """
    Run planning flow with layer-level checkpoint capture.

    SSE模式（推荐）：
    - step_mode=False 自动推进
    - SSE 事件驱动等待 layer 完成
    - 无暂停开销，与前端一致响应速度

    轮询模式（后备）：
    - step_mode=True 暂停捕获
    - 轮询检测 layer 完成
    - auto_resume 自动恢复

    Args:
        project_name: Project name
        village_data: Village configuration data
        output_dir: Output directory for checkpoints
        timeout_per_layer: Timeout for each layer in seconds
        use_sse: Use SSE event-driven mode (default True)

    Returns:
        Complete session state with layer checkpoint info
    """
    from backend.services.planning_runtime_service import PlanningRuntimeService
    from starlette.background import BackgroundTasks

    mode_str = "SSE" if use_sse else "polling"
    logger.info(
        f"[Baseline] Starting planning runtime with layer checkpoints ({mode_str} mode): {project_name}"
    )

    # Create BackgroundTasks for script mode
    background_tasks = BackgroundTasks()

    # SSE模式使用 step_mode=False 自动推进，轮询模式使用 step_mode=True
    step_mode = not use_sse

    # SSE 模式：先启动 listener，再启动 session
    # 这确保 listener 在后台执行开始前就准备好接收事件
    sse_listener = None
    if use_sse:
        from scripts.experiments.sse_listener import SSEEventListener
        # 预先启动 listener（使用临时 session_id 前缀，后续更新）
        sse_listener = SSEEventListener("pending", base_url="http://localhost:8000")
        await sse_listener.connect()
        logger.info("[Baseline] SSE listener pre-connected")

    # Start session
    result = await PlanningRuntimeService.start_session(
        project_name=project_name,
        village_data=village_data.get("status_report", ""),
        village_name=village_data.get("village_name", "金田村"),
        step_mode=step_mode,
        background_tasks=background_tasks,
    )

    session_id = result.get("task_id")
    logger.info(
        f"[Baseline] Session started: {session_id} (step_mode={step_mode})"
    )

    # Update SSE listener with actual session_id
    if use_sse and sse_listener:
        sse_listener.session_id = session_id
        # 重新连接到正确的 session 流
        await sse_listener.disconnect()
        sse_listener = SSEEventListener(session_id, base_url="http://localhost:8000")
        await sse_listener.connect()
        logger.info(f"[Baseline] SSE listener reconnected to session {session_id}")

    # Execute background tasks (SSE listener is already connected)
    await background_tasks()

    # Wait for all layers with checkpoint capture
    all_layers_snapshot = await wait_for_all_layers(
        session_id=session_id,
        timeout_per_layer=timeout_per_layer,
        use_sse=use_sse,
        listener=sse_listener if use_sse else None,
    )

    # Save layer checkpoints
    save_all_layer_checkpoints(all_layers_snapshot, output_dir)

    # Get final state
    from backend.services.checkpoint_service import checkpoint_service
    final_state = await checkpoint_service.get_state(session_id, wait_for_write=True) or {}

    return {
        "session_id": session_id,
        "project_name": project_name,
        "layer_checkpoints": all_layers_snapshot.get("layer_checkpoints", {}),
        "final_checkpoint_id": all_layers_snapshot.get("final_checkpoint_id", ""),
        "state_fingerprint": all_layers_snapshot.get("state_fingerprint", ""),
        **final_state,
    }


# ============================================
# Report Saving
# ============================================

def save_reports(state: Dict[str, Any], output_dir: Path, layer_checkpoints: Dict[str, Any] = None):
    """
    Save reports to output directory.

    Args:
        state: Session state
        output_dir: Output directory path
        layer_checkpoints: Optional layer checkpoint info from wait_for_all_layers
    """
    session_id = state.get("session_id", "unknown")
    reports = state.get("reports", {})
    completed_dimensions = state.get("completed_dimensions", {})

    # Compute state fingerprint
    state_fingerprint = compute_state_fingerprint(state)

    # Save session metadata
    session_meta = {
        "session_id": session_id,
        "project_name": state.get("project_name", ""),
        "phase": state.get("phase", ""),
        "created_at": datetime.now().isoformat(),
        "state_fingerprint": state_fingerprint,
        "final_checkpoint_id": state.get("final_checkpoint_id", ""),
    }
    with open(output_dir / "session_id.json", "w", encoding="utf-8") as f:
        json.dump(session_meta, f, indent=2, ensure_ascii=False)
    logger.info(f"[Baseline] Saved session_id.json")

    # Save layer reports with checkpoint metadata
    for layer in [1, 2, 3]:
        layer_key = f"layer{layer}"
        layer_reports = reports.get(layer_key, {})
        layer_completed = completed_dimensions.get(layer_key, [])

        # Get checkpoint info if available
        checkpoint_id = ""
        checkpoint_timestamp = ""
        if layer_checkpoints and layer_key in layer_checkpoints:
            cp_info = layer_checkpoints[layer_key]
            checkpoint_id = cp_info.get("checkpoint_id", "")
            checkpoint_timestamp = cp_info.get("timestamp", "")

        layer_data = {
            "layer": layer,
            "checkpoint_id": checkpoint_id,
            "checkpoint_saved_at": checkpoint_timestamp,
            "state_fingerprint": state_fingerprint,
            "reports": layer_reports,
            "completed_dimensions": layer_completed,
            "report_count": len(layer_reports),
            "total_chars": sum(len(v) for v in layer_reports.values()) if layer_reports else 0,
        }
        with open(output_dir / f"layer{layer}_reports.json", "w", encoding="utf-8") as f:
            json.dump(layer_data, f, indent=2, ensure_ascii=False)
        logger.info(f"[Baseline] Saved layer{layer}_reports.json: {len(layer_reports)} dimensions")

    # Save checkpoints summary with layer checkpoints structure
    checkpoints_summary = {
        "session_id": session_id,
        "layer_checkpoints": {},
        "final_checkpoint_id": state.get("final_checkpoint_id", ""),
        "state_fingerprint": state_fingerprint,
        "collected_at": datetime.now().isoformat(),
    }
    # Add layer checkpoint info
    if layer_checkpoints:
        for layer_key, cp_info in layer_checkpoints.items():
            checkpoints_summary["layer_checkpoints"][layer_key] = {
                "checkpoint_id": cp_info.get("checkpoint_id", ""),
                "phase": cp_info.get("phase", ""),
                "timestamp": cp_info.get("timestamp", ""),
                "state_fingerprint": cp_info.get("state_fingerprint", ""),
            }
    else:
        checkpoints_summary["note"] = "Layer checkpoints not captured"

    with open(output_dir / "checkpoints.json", "w", encoding="utf-8") as f:
        json.dump(checkpoints_summary, f, indent=2, ensure_ascii=False)


# ============================================
# Main Entry Point
# ============================================

async def run_baseline(
    timeout: int = 1800,
    use_mock: bool = False,
    capture_layer_checkpoints: bool = True,
    use_sse: bool = True,
):
    """
    Run baseline experiment.

    Args:
        timeout: Maximum wait time in seconds (or per-layer if capture_layer_checkpoints=True)
        use_mock: Whether to use mock data (for testing without full runtime)
        capture_layer_checkpoints: Whether to capture checkpoint at each layer completion
        use_sse: Use SSE event-driven mode (default True, recommended)
    """
    ensure_output_dirs()

    project_name = "金田村基线实验"

    logger.info("=" * 60)
    logger.info("[Baseline] Starting baseline experiment")
    logger.info(f"[Baseline] Capture layer checkpoints: {capture_layer_checkpoints}")
    logger.info(f"[Baseline] SSE mode: {use_sse}")
    logger.info("=" * 60)

    try:
        if use_mock:
            state = await mock_run_planning_flow(
                project_name=project_name,
                village_data=JINTIAN_VILLAGE_DATA,
                timeout=timeout,
            )
            layer_checkpoints = None
        elif capture_layer_checkpoints:
            # Use new function with layer-level checkpoint capture
            state = await run_planning_runtime_with_layer_checkpoints(
                project_name=project_name,
                village_data=JINTIAN_VILLAGE_DATA,
                output_dir=BASELINE_DIR,
                timeout_per_layer=timeout // 3 if timeout > 0 else 600,
                use_sse=use_sse,
            )
            layer_checkpoints = state.get("layer_checkpoints", {})
        else:
            # Use original function (no layer checkpoint capture)
            state = await run_planning_runtime(
                project_name=project_name,
                village_data=JINTIAN_VILLAGE_DATA,
                timeout=timeout,
            )
            layer_checkpoints = None

        # Save reports
        save_reports(state, BASELINE_DIR, layer_checkpoints)

        logger.info("=" * 60)
        logger.info("[Baseline] Baseline experiment completed")
        logger.info(f"[Baseline] Session ID: {state.get('session_id', 'unknown')}")
        if layer_checkpoints:
            for layer_key, cp in layer_checkpoints.items():
                logger.info(f"[Baseline] {layer_key} checkpoint: {cp.get('checkpoint_id', 'N/A')}")
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
    parser.add_argument("--no-layer-checkpoints", action="store_true",
                        help="Disable layer-level checkpoint capture")
    parser.add_argument("--use-polling", action="store_true",
                        help="Use polling mode instead of SSE (fallback)")
    args = parser.parse_args()

    asyncio.run(run_baseline(
        timeout=args.timeout,
        use_mock=args.mock,
        capture_layer_checkpoints=not args.no_layer_checkpoints,
        use_sse=not args.use_polling,
    ))


if __name__ == "__main__":
    main()