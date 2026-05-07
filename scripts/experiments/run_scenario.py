"""
Scenario Run Script
场景执行脚本

从基线状态恢复，执行驳回操作，记录级联修复过程。

使用方法:
    python scripts/experiments/run_scenario.py --scenario scenario1 [--timeout 600]
    python scripts/experiments/run_scenario.py --scenario scenario2 [--timeout 600]

输出:
    - experiment_config.json
    - impact_tree.json
    - wave_allocation.json
    - sse_events.json
    - revision_history.json
    - dimension_diffs/*.json
"""

import asyncio
import json
import logging
import sys
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.experiments.config import (
    BASELINE_DIR,
    SCENARIO1_DIR,
    SCENARIO2_DIR,
    SCENARIOS,
    ensure_output_dirs,
    get_scenario_config,
    get_output_dir,
)
from scripts.experiments.layer_checkpoint_utils import (
    restore_from_checkpoint,
    load_layer_checkpoint,
    verify_restoration_consistency,
    compute_state_fingerprint,
)

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


# ============================================
# Impact Tree Calculator
# ============================================

def calculate_impact_tree(target_dimension: str) -> Dict[int, List[str]]:
    """
    Calculate impact tree for a target dimension.

    Uses dimension_metadata.get_impact_tree() to calculate downstream dependencies.

    Args:
        target_dimension: Target dimension key

    Returns:
        {wave: [dimension_keys]} grouped by wave
    """
    from src.config.dimension_metadata import get_impact_tree

    tree = get_impact_tree(target_dimension)

    # Add target dimension as wave 0
    full_tree = {0: [target_dimension]}
    for wave, dims in tree.items():
        full_tree[wave] = dims

    return full_tree


def calculate_wave_allocation(
    target_dimensions: List[str],
    completed_dimensions: List[str]
) -> Dict[int, List[str]]:
    """
    Calculate wave allocation for revision.

    Uses dimension_metadata.get_revision_wave_dimensions() to calculate.

    Args:
        target_dimensions: Target dimension keys
        completed_dimensions: Completed dimension keys

    Returns:
        {wave: [dimension_keys]} grouped by wave
    """
    from src.config.dimension_metadata import get_revision_wave_dimensions

    return get_revision_wave_dimensions(target_dimensions, completed_dimensions)


def get_dimension_metadata(dimension_key: str) -> Dict[str, Any]:
    """Get metadata for a dimension."""
    from src.config.dimension_metadata import get_dimension_config, get_dimension_layer

    config = get_dimension_config(dimension_key)
    layer = get_dimension_layer(dimension_key)

    return {
        "key": dimension_key,
        "name": config.get("name", dimension_key) if config else dimension_key,
        "layer": layer,
        "description": config.get("description", "") if config else "",
    }


# ============================================
# Checkpoint Restoration
# ============================================

async def restore_baseline_checkpoint(
    baseline_session_id: str,
    restore_layer: int = 3,  # 级联更新实验应从 Layer3 完成态恢复
    scenario_name: str = "",
) -> Dict[str, Any]:
    """
    Restore baseline checkpoint for cascade consistency experiment.

    级联更新实验必须从 Layer3 完成态恢复，然后触发驳回，
    这样才能观察下游维度的级联更新效果。

    Args:
        baseline_session_id: Baseline session ID
        restore_layer: Layer to restore from (default 3 for cascade experiments)
        scenario_name: Scenario name (for new session prefix)

    Returns:
        Restoration result with new_session_id
    """
    logger.info(f"[Scenario] Restoring baseline checkpoint from Layer {restore_layer} (completed state)")

    # Load layer checkpoint from baseline output
    checkpoint_data = load_layer_checkpoint(BASELINE_DIR, restore_layer)
    if not checkpoint_data:
        raise ValueError(f"Layer {restore_layer} checkpoint not found in {BASELINE_DIR}")

    target_checkpoint_id = checkpoint_data.get("checkpoint_id", "")
    if not target_checkpoint_id:
        # Fallback: use baseline session ID directly
        logger.warning(f"[Scenario] No checkpoint_id found, using baseline session directly")
        return {
            "new_session_id": baseline_session_id,
            "restored_state": {},
            "source_checkpoint_id": "",
            "baseline_session_id": baseline_session_id,
            "restore_layer": restore_layer,
        }

    # Restore from checkpoint (use restore_layer, not target_dimension's layer)
    restoration_result = await restore_from_checkpoint(
        baseline_session_id=baseline_session_id,
        target_checkpoint_id=target_checkpoint_id,
        target_layer=restore_layer,  # 从 Layer3 完成态恢复
        new_session_prefix=scenario_name,
    )

    logger.info(f"[Scenario] Restored to new session: {restoration_result.get('new_session_id')}")
    return restoration_result


# ============================================
# Mock Scenario Execution
# ============================================

async def mock_execute_scenario(
    scenario_name: str,
    baseline_state: Dict[str, Any],
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Mock scenario execution for testing.

    Simulates reject operation and cascade revision without actual runtime.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)
        baseline_state: Baseline state from run_baseline
        timeout: Maximum wait time

    Returns:
        Experiment results
    """
    config = get_scenario_config(scenario_name)
    target_dimension = config["target_dimension"]
    feedback = config["feedback"]

    logger.info(f"[Scenario] Executing {scenario_name}: {config['name']}")
    logger.info(f"[Scenario] Target dimension: {target_dimension}")

    # Get completed dimensions from baseline (compatible with both dict and list formats)
    completed_dims_raw = baseline_state.get("completed_dimensions", {})
    completed_dims = []

    if isinstance(completed_dims_raw, dict):
        for layer_key in ["layer1", "layer2", "layer3"]:
            completed_dims.extend(completed_dims_raw.get(layer_key, []))
    elif isinstance(completed_dims_raw, list):
        completed_dims = completed_dims_raw
    else:
        # Fallback: derive from reports
        reports = baseline_state.get("reports", {})
        for layer_key in ["layer1", "layer2", "layer3"]:
            layer_reports = reports.get(layer_key, {})
            completed_dims.extend(layer_reports.keys())

    # Calculate impact tree
    impact_tree = calculate_impact_tree(target_dimension)
    wave_allocation = calculate_wave_allocation([target_dimension], completed_dims)

    # Save impact tree
    output_dir = get_output_dir(scenario_name)

    impact_data = {
        "target_dimension": target_dimension,
        "impact_tree": impact_tree,
        "total_downstream": sum(len(dims) for dims in impact_tree.values()),
        "max_wave": max(impact_tree.keys()),
        "dimension_metadata": {dim: get_dimension_metadata(dim) for dims in impact_tree.values() for dim in dims},
    }

    wave_data = {
        "target_dimension": target_dimension,
        "wave_allocation": wave_allocation,
        "completed_dimensions": completed_dims,
        "total_waves": max(wave_allocation.keys()) if wave_allocation else 0,
        "pending_dimensions": sum(len(dims) for dims in wave_allocation.values()),
    }

    # Generate mock SSE events
    sse_events = []
    session_id = f"{scenario_name}_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # Event 1: Reject received
    sse_events.append({
        "type": "reject_received",
        "session_id": session_id,
        "target_dimension": target_dimension,
        "feedback": feedback,
        "timestamp": datetime.now().isoformat(),
    })

    # Event 2-4: Dimension revisions (mock)
    for wave, dims in wave_allocation.items():
        for dim in dims:
            dim_meta = get_dimension_metadata(dim)
            sse_events.append({
                "type": "dimension_revised",
                "session_id": session_id,
                "dimension_key": dim,
                "dimension_name": dim_meta["name"],
                "layer": dim_meta["layer"],
                "wave": wave,
                "revision_type": "目标维度修复" if dim == target_dimension else "级联更新",
                "timestamp": datetime.now().isoformat(),
            })

    # Event 5: Revision completed
    sse_events.append({
        "type": "revision_completed",
        "session_id": session_id,
        "revised_dimensions": [dim for dims in wave_allocation.values() for dim in dims],
        "timestamp": datetime.now().isoformat(),
    })

    # Generate mock revision history
    revision_history = []
    baseline_reports = baseline_state.get("reports", {})

    for wave, dims in wave_allocation.items():
        for dim in dims:
            layer = get_dimension_metadata(dim)["layer"]
            layer_key = f"layer{layer}"
            original_content = baseline_reports.get(layer_key, {}).get(dim, "")

            # Mock revised content (for testing)
            if dim == target_dimension:
                revised_content = f"[修订] {original_content[:200] if original_content else 'Mock revised content'}..."
            else:
                revised_content = f"[级联更新] {original_content[:200] if original_content else 'Mock cascade updated content'}..."

            revision_history.append({
                "dimension": dim,
                "dimension_name": get_dimension_metadata(dim)["name"],
                "layer": layer,
                "wave": wave,
                "is_target": dim == target_dimension,
                "old_content": original_content[:500] if original_content else "",
                "new_content": revised_content,
                "timestamp": datetime.now().isoformat(),
            })

    return {
        "session_id": session_id,
        "scenario_name": scenario_name,
        "config": config,
        "impact_data": impact_data,
        "wave_data": wave_data,
        "sse_events": sse_events,
        "revision_history": revision_history,
    }


# ============================================
# Actual Scenario Execution
# ============================================

async def execute_scenario_with_runtime(
    scenario_name: str,
    baseline_session_id: str,
    timeout: int = 600,
    use_checkpoint_restore: bool = True,
    use_sse: bool = True,
    poll_interval: int = 5,
) -> Dict[str, Any]:
    """
    Execute scenario using actual planning runtime.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)
        baseline_session_id: Session ID from baseline run
        timeout: Maximum wait time in seconds
        use_checkpoint_restore: Whether to restore from checkpoint before execution
        use_sse: Use SSE mode for waiting (default True)
        poll_interval: Polling interval in seconds (only for polling mode)

    Returns:
        Experiment results
    """
    from backend.services.review_service import review_service
    from backend.services.checkpoint_service import checkpoint_service

    config = get_scenario_config(scenario_name)
    target_dimension = config["target_dimension"]
    target_layer = config["target_layer"]
    feedback = config["feedback"]

    logger.info(f"[Scenario] Executing {scenario_name} with runtime")
    logger.info(f"[Scenario] Monitor mode: {'SSE' if use_sse else 'Polling'}")
    logger.info(f"[Scenario] Baseline session: {baseline_session_id}")
    logger.info(f"[Scenario] Target layer: {target_layer}, dimension: {target_dimension}")
    logger.info(f"[Scenario] Use checkpoint restore: {use_checkpoint_restore}")
    logger.info(f"[Scenario] SSE mode: {use_sse}")

    # Determine execution session ID
    execution_session_id = baseline_session_id
    restoration_info = {}

    if use_checkpoint_restore:
        # Restore from Layer3 completed state (not target_layer!)
        # 级联更新实验需要从完成态恢复，才能观察驳回后的级联更新效果
        try:
            restoration_result = await restore_baseline_checkpoint(
                baseline_session_id=baseline_session_id,
                restore_layer=3,  # Always restore from Layer3 completed state
                scenario_name=scenario_name,
            )
            execution_session_id = restoration_result.get("new_session_id", baseline_session_id)
            restoration_info = restoration_result

            logger.info(f"[Scenario] Restored session: {execution_session_id}")

            # Verify restoration consistency if checkpoint was used
            if restoration_result.get("source_checkpoint_id"):
                # Verify against Layer3 checkpoint
                checkpoint_data = load_layer_checkpoint(BASELINE_DIR, 3)
                if checkpoint_data:
                    restored_state = await checkpoint_service.get_state(execution_session_id)
                    if restored_state:
                        try:
                            verify_restoration_consistency(restored_state, checkpoint_data, 3)
                            logger.info(f"[Scenario] Consistency verified: fingerprint match")
                        except ValueError as e:
                            logger.warning(f"[Scenario] Consistency check failed: {e}")
        except Exception as e:
            logger.warning(f"[Scenario] Checkpoint restore failed: {e}, using baseline session directly")
            execution_session_id = baseline_session_id

    # Get state for execution
    execution_state = await checkpoint_service.get_state(execution_session_id)
    if not execution_state:
        raise ValueError(f"Execution session not found: {execution_session_id}")

    # Get completed dimensions (compatible with both dict and list formats)
    completed_dims_raw = execution_state.get("completed_dimensions", {})
    completed_dims = []

    if isinstance(completed_dims_raw, dict):
        # 分层字典格式 {layer1: [...], layer2: [...], layer3: [...]}
        for layer_key in ["layer1", "layer2", "layer3"]:
            completed_dims.extend(completed_dims_raw.get(layer_key, []))
    elif isinstance(completed_dims_raw, list):
        # 扁平列表格式（兼容旧数据）
        completed_dims = completed_dims_raw
    else:
        # 无数据或异常格式，从 reports 推导
        from src.config.dimension_metadata import get_dimension_layer
        reports = execution_state.get("reports", {})
        for layer_key in ["layer1", "layer2", "layer3"]:
            layer_reports = reports.get(layer_key, {})
            completed_dims.extend(layer_reports.keys())

    # Calculate impact tree (before execution)
    impact_tree = calculate_impact_tree(target_dimension)
    wave_allocation = calculate_wave_allocation([target_dimension], completed_dims)

    # DEBUG: Log completed dimensions
    logger.info(f"[Scenario] completed_dims_raw type: {type(completed_dims_raw)}")
    logger.info(f"[Scenario] completed_dims count: {len(completed_dims)}")
    logger.info(f"[Scenario] completed_dims: {completed_dims}")
    logger.info(f"[Scenario] wave_allocation: {wave_allocation}")

    # Execute reject
    logger.info(f"[Scenario] Executing reject on session: {execution_session_id}")
    logger.info(f"[Scenario] Target: {target_dimension}")

    reject_response = await review_service.reject(
        session_id=execution_session_id,
        feedback=feedback,
        dimensions=[target_dimension],
    )

    logger.info(f"[Scenario] Reject response: {reject_response}")

    # Trigger revision execution (critical step!)
    # reject 只设置状态，需要 resume_execution 触发级联更新
    from backend.services.planning_runtime_service import PlanningRuntimeService
    await PlanningRuntimeService.resume_execution(execution_session_id)
    logger.info(f"[Scenario] Resume execution triggered for revision")

    # Wait for revision completion
    state = await wait_for_revision_completion(execution_session_id, timeout, use_sse=use_sse, poll_interval=poll_interval)

    # Extract results
    revision_history = state.get("revision_history", [])
    updated_reports = state.get("reports", {})

    # Build SSE events from revision history
    sse_events = []
    for entry in revision_history:
        sse_events.append({
            "type": "dimension_revised",
            "session_id": execution_session_id,
            "dimension_key": entry.get("dimension"),
            "dimension_name": entry.get("dimension_name"),
            "layer": entry.get("layer"),
            "wave": entry.get("wave", 0),
            "revision_type": "目标维度修复" if entry.get("is_target") else "级联更新",
            "timestamp": entry.get("timestamp"),
        })

    sse_events.append({
        "type": "revision_completed",
        "session_id": execution_session_id,
        "revised_dimensions": [e.get("dimension_key") for e in sse_events],
        "timestamp": datetime.now().isoformat(),
    })

    return {
        "session_id": execution_session_id,
        "baseline_session_id": baseline_session_id,
        "restoration_info": restoration_info,
        "scenario_name": scenario_name,
        "config": config,
        "impact_data": {
            "target_dimension": target_dimension,
            "impact_tree": impact_tree,
            "total_downstream": sum(len(dims) for dims in impact_tree.values()),
            "max_wave": max(impact_tree.keys()),
        },
        "wave_data": {
            "target_dimension": target_dimension,
            "wave_allocation": wave_allocation,
            "total_waves": max(wave_allocation.keys()) if wave_allocation else 0,
        },
        "sse_events": sse_events,
        "revision_history": revision_history,
        "updated_reports": updated_reports,
    }


async def wait_for_revision_completion(
    session_id: str,
    timeout: int = 600,
    use_sse: bool = True,
    poll_interval: int = 5,
) -> Dict[str, Any]:
    """
    Wait for revision completion.

    SSE模式（推荐）：
    - 事件驱动等待 revision_completed 事件
    - 几乎无延迟

    Polling模式（后备）：
    - 使用 wait_for_write=True 确保获取最新 checkpoint
    - 检查 need_revision 和 last_revised_dimensions

    Args:
        session_id: Session identifier
        timeout: Maximum wait time
        use_sse: Use SSE mode (default True)
        poll_interval: Polling interval in seconds (only for polling mode)

    Returns:
        Final state
    """
    from backend.services.checkpoint_service import checkpoint_service

    if use_sse:
        return await wait_for_revision_completion_sse(session_id, timeout)
    else:
        return await wait_for_revision_completion_polling(session_id, timeout, poll_interval)


async def wait_for_revision_completion_sse(
    session_id: str,
    timeout: int = 600,
) -> Dict[str, Any]:
    """
    使用 SSE 事件驱动等待 revision 完成。

    Args:
        session_id: Session identifier
        timeout: Maximum wait time

    Returns:
        Final state
    """
    from backend.services.checkpoint_service import checkpoint_service
    from scripts.experiments.sse_listener import SSEEventListener

    logger.info(f"[Scenario] Waiting for revision (SSE mode, timeout={timeout}s)")

    listener = SSEEventListener(session_id)
    await listener.connect()

    try:
        # 等待 revision_completed 事件
        await listener.wait_for_revision_completion(timeout=timeout)

        logger.info("[Scenario] Revision completed (SSE event received)")

        # 获取最终状态
        state = await checkpoint_service.get_state(session_id, wait_for_write=True)
        return state or {}

    except asyncio.TimeoutError:
        logger.warning(f"[Scenario] SSE timeout after {timeout}s")
        return await checkpoint_service.get_state(session_id) or {}

    finally:
        await listener.disconnect()


async def wait_for_revision_completion_polling(
    session_id: str,
    timeout: int = 600,
    poll_interval: int = 5,
) -> Dict[str, Any]:
    """
    使用轮询等待 revision 完成。

    关键改进：
    - 使用 wait_for_write=True 确保获取最新 checkpoint 状态
    - 检查 last_revised_dimensions 作为额外完成标志（revision_node 设置）
    - 添加 poll_interval 参数控制轮询频率

    Args:
        session_id: Session identifier
        timeout: Maximum wait time in seconds
        poll_interval: Polling interval in seconds

    Returns:
        Final state with revision_history and reports
    """
    from backend.services.checkpoint_service import checkpoint_service

    start_time = datetime.now()

    logger.info(f"[Scenario] Waiting for revision (polling mode, interval={poll_interval}s, timeout={timeout}s)")

    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout:
            logger.warning(f"[Scenario] Polling timeout after {elapsed:.1f}s")
            break

        # 使用 wait_for_write=True 确保获取最新 checkpoint 状态
        state = await checkpoint_service.get_state(session_id, wait_for_write=True)
        if state:
            need_revision = state.get("need_revision", False)
            revision_history = state.get("revision_history", [])
            last_revised_dimensions = state.get("last_revised_dimensions", [])

            # 检查 revision 完成条件：
            # 1. need_revision=False（revision_node 已完成）
            # 2. revision_history 或 last_revised_dimensions 有内容
            if not need_revision:
                if len(revision_history) > 0:
                    logger.info(f"[Scenario] Revision completed: {len(revision_history)} history entries")
                    return state
                elif len(last_revised_dimensions) > 0:
                    logger.info(f"[Scenario] Revision completed: {len(last_revised_dimensions)} revised dimensions")
                    return state
                else:
                    # need_revision=False 但无 revision 结果，可能是初始状态
                    logger.debug(f"[Scenario] need_revision=False but no revision results yet, continuing...")

            # 每 30 秒打印进度日志
            if elapsed > 0 and elapsed % 30 < poll_interval:
                logger.info(f"[Scenario] Polling progress: {elapsed:.1f}s elapsed, "
                           f"need_revision={need_revision}, "
                           f"revision_history_count={len(revision_history)}, "
                           f"last_revised_count={len(last_revised_dimensions)}")

        await asyncio.sleep(poll_interval)

    # Timeout: 返回当前状态（可能部分完成）
    final_state = await checkpoint_service.get_state(session_id, wait_for_write=True) or {}
    logger.warning(f"[Scenario] Polling timeout, returning current state: "
                  f"revision_history={len(final_state.get('revision_history', []))}, "
                  f"last_revised={len(final_state.get('last_revised_dimensions', []))}")
    return final_state


# ============================================
# Result Saving
# ============================================

def save_scenario_results(results: Dict[str, Any], output_dir: Path):
    """
    Save scenario results to output directory.

    Args:
        results: Experiment results
        output_dir: Output directory path
    """
    # Save config
    config_data = {
        "session_id": results.get("session_id"),
        "scenario_name": results.get("scenario_name"),
        "config": results.get("config"),
        "created_at": datetime.now().isoformat(),
    }
    with open(output_dir / "experiment_config.json", "w", encoding="utf-8") as f:
        json.dump(config_data, f, indent=2, ensure_ascii=False)

    # Save impact tree
    with open(output_dir / "impact_tree.json", "w", encoding="utf-8") as f:
        json.dump(results.get("impact_data", {}), f, indent=2, ensure_ascii=False)

    # Save wave allocation
    with open(output_dir / "wave_allocation.json", "w", encoding="utf-8") as f:
        json.dump(results.get("wave_data", {}), f, indent=2, ensure_ascii=False)

    # Save SSE events
    with open(output_dir / "sse_events.json", "w", encoding="utf-8") as f:
        json.dump(results.get("sse_events", []), f, indent=2, ensure_ascii=False)

    # Save revision history
    with open(output_dir / "revision_history.json", "w", encoding="utf-8") as f:
        json.dump(results.get("revision_history", []), f, indent=2, ensure_ascii=False)

    # Save dimension diffs
    diffs_dir = output_dir / "dimension_diffs"
    diffs_dir.mkdir(exist_ok=True)

    for entry in results.get("revision_history", []):
        dim = entry.get("dimension")
        diff_data = {
            "dimension": dim,
            "dimension_name": entry.get("dimension_name"),
            "layer": entry.get("layer"),
            "wave": entry.get("wave"),
            "is_target": entry.get("is_target"),
            "old_content": entry.get("old_content"),
            "new_content": entry.get("new_content"),
            "timestamp": entry.get("timestamp"),
        }
        with open(diffs_dir / f"{dim}.json", "w", encoding="utf-8") as f:
            json.dump(diff_data, f, indent=2, ensure_ascii=False)

    logger.info(f"[Scenario] Saved results to {output_dir}")


# ============================================
# Main Entry Point
# ============================================

async def run_scenario(
    scenario_name: str,
    timeout: int = 600,
    use_mock: bool = False,
    use_sse: bool = True,
    poll_interval: int = 5,
):
    """
    Run scenario experiment.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)
        timeout: Maximum wait time in seconds
        use_mock: Whether to use mock data
        use_sse: Use SSE mode (default True, use polling for experiments)
        poll_interval: Polling interval in seconds (only for polling mode)
    """
    ensure_output_dirs()

    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(SCENARIOS.keys())}")

    logger.info("=" * 60)
    logger.info(f"[Scenario] Starting {scenario_name} experiment")
    logger.info(f"[Scenario] Monitor mode: {'SSE' if use_sse else 'Polling (interval=' + str(poll_interval) + 's)'}")
    logger.info("=" * 60)

    # Load baseline state
    baseline_file = BASELINE_DIR / "session_id.json"
    if not baseline_file.exists():
        logger.warning("[Scenario] Baseline not found, running baseline first...")
        from scripts.experiments.run_baseline import run_baseline
        await run_baseline(timeout=timeout, use_mock=use_mock, use_sse=use_sse)

    with open(baseline_file, "r", encoding="utf-8") as f:
        baseline_meta = json.load(f)

    # Load full baseline state
    baseline_state = {"session_id": baseline_meta.get("session_id")}
    for layer in [1, 2, 3]:
        layer_file = BASELINE_DIR / f"layer{layer}_reports.json"
        if layer_file.exists():
            with open(layer_file, "r", encoding="utf-8") as f:
                layer_data = json.load(f)
            baseline_state["reports"] = baseline_state.get("reports", {})
            baseline_state["reports"][f"layer{layer}"] = layer_data.get("reports", {})
            baseline_state["completed_dimensions"] = baseline_state.get("completed_dimensions", {})
            baseline_state["completed_dimensions"][f"layer{layer}"] = layer_data.get("completed_dimensions", [])

    try:
        if use_mock:
            results = await mock_execute_scenario(
                scenario_name=scenario_name,
                baseline_state=baseline_state,
                timeout=timeout,
            )
        else:
            results = await execute_scenario_with_runtime(
                scenario_name=scenario_name,
                baseline_session_id=baseline_meta.get("session_id"),
                timeout=timeout,
                use_sse=use_sse,
                poll_interval=poll_interval,
            )

        # Save results
        output_dir = get_output_dir(scenario_name)
        save_scenario_results(results, output_dir)

        logger.info("=" * 60)
        logger.info(f"[Scenario] {scenario_name} completed")
        logger.info(f"[Scenario] Session ID: {results.get('session_id')}")
        logger.info(f"[Scenario] Revised dimensions: {len(results.get('revision_history', []))}")
        logger.info("=" * 60)

        return results

    except Exception as e:
        logger.error(f"[Scenario] Failed: {e}", exc_info=True)
        raise


def main():
    """CLI entry point."""
    import argparse
    parser = argparse.ArgumentParser(description="Run scenario experiment")
    parser.add_argument("--scenario", required=True, choices=["scenario1", "scenario2"], help="Scenario name")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds")
    parser.add_argument("--mock", action="store_true", help="Use mock data for testing")
    parser.add_argument("--use-polling", action="store_true",
                        help="Use polling mode instead of SSE (recommended for experiments)")
    parser.add_argument("--poll-interval", type=int, default=5,
                        help="Polling interval in seconds (only for polling mode)")
    args = parser.parse_args()

    asyncio.run(run_scenario(
        scenario_name=args.scenario,
        timeout=args.timeout,
        use_mock=args.mock,
        use_sse=not args.use_polling,
        poll_interval=args.poll_interval,
    ))


if __name__ == "__main__":
    main()