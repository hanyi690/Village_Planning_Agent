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

    # Get completed dimensions from baseline
    completed_dims = []
    for layer_key in ["layer1", "layer2", "layer3"]:
        completed_dims.extend(baseline_state.get("completed_dimensions", {}).get(layer_key, []))

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
    timeout: int = 600
) -> Dict[str, Any]:
    """
    Execute scenario using actual planning runtime.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)
        baseline_session_id: Session ID from baseline run
        timeout: Maximum wait time

    Returns:
        Experiment results
    """
    from backend.services.review_service import review_service
    from backend.services.checkpoint_service import checkpoint_service

    config = get_scenario_config(scenario_name)
    target_dimension = config["target_dimension"]
    feedback = config["feedback"]

    logger.info(f"[Scenario] Executing {scenario_name} with runtime")
    logger.info(f"[Scenario] Baseline session: {baseline_session_id}")

    # Get baseline state
    baseline_state = await checkpoint_service.get_state(baseline_session_id)
    if not baseline_state:
        raise ValueError(f"Baseline session not found: {baseline_session_id}")

    # Get completed dimensions
    completed_dims = []
    for layer_key in ["layer1", "layer2", "layer3"]:
        completed_dims.extend(baseline_state.get("completed_dimensions", {}).get(layer_key, []))

    # Calculate impact tree (before execution)
    impact_tree = calculate_impact_tree(target_dimension)
    wave_allocation = calculate_wave_allocation([target_dimension], completed_dims)

    # Execute reject
    logger.info(f"[Scenario] Executing reject: {target_dimension}")

    reject_response = await review_service.reject(
        session_id=baseline_session_id,
        feedback=feedback,
        dimensions=[target_dimension],
    )

    logger.info(f"[Scenario] Reject response: {reject_response}")

    # Wait for revision completion
    state = await wait_for_revision_completion(baseline_session_id, timeout)

    # Extract results
    revision_history = state.get("revision_history", [])
    updated_reports = state.get("reports", {})

    # Build SSE events from revision history
    sse_events = []
    for entry in revision_history:
        sse_events.append({
            "type": "dimension_revised",
            "session_id": baseline_session_id,
            "dimension_key": entry.get("dimension"),
            "dimension_name": entry.get("dimension_name"),
            "layer": entry.get("layer"),
            "wave": entry.get("wave", 0),
            "revision_type": "目标维度修复" if entry.get("is_target") else "级联更新",
            "timestamp": entry.get("timestamp"),
        })

    sse_events.append({
        "type": "revision_completed",
        "session_id": baseline_session_id,
        "revised_dimensions": [e.get("dimension_key") for e in sse_events],
        "timestamp": datetime.now().isoformat(),
    })

    return {
        "session_id": baseline_session_id,
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


async def wait_for_revision_completion(session_id: str, timeout: int = 600) -> Dict[str, Any]:
    """
    Wait for revision completion.

    Args:
        session_id: Session identifier
        timeout: Maximum wait time

    Returns:
        Final state
    """
    from backend.services.checkpoint_service import checkpoint_service

    start_time = datetime.now()
    check_interval = 5

    while True:
        elapsed = (datetime.now() - start_time).total_seconds()
        if elapsed > timeout:
            logger.warning(f"[Scenario] Timeout after {elapsed}s")
            break

        state = await checkpoint_service.get_state(session_id)
        if state:
            need_revision = state.get("need_revision", False)
            revision_history = state.get("revision_history", [])

            if not need_revision and len(revision_history) > 0:
                logger.info(f"[Scenario] Revision completed: {len(revision_history)} dimensions")
                return state

        await asyncio.sleep(check_interval)

    return await checkpoint_service.get_state(session_id) or {}


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

async def run_scenario(scenario_name: str, timeout: int = 600, use_mock: bool = True):
    """
    Run scenario experiment.

    Args:
        scenario_name: Scenario name (scenario1 or scenario2)
        timeout: Maximum wait time
        use_mock: Whether to use mock data
    """
    ensure_output_dirs()

    if scenario_name not in SCENARIOS:
        raise ValueError(f"Unknown scenario: {scenario_name}. Available: {list(SCENARIOS.keys())}")

    logger.info("=" * 60)
    logger.info(f"[Scenario] Starting {scenario_name} experiment")
    logger.info("=" * 60)

    # Load baseline state
    baseline_file = BASELINE_DIR / "session_id.json"
    if not baseline_file.exists():
        logger.warning("[Scenario] Baseline not found, running baseline first...")
        from scripts.experiments.run_baseline import run_baseline
        await run_baseline(timeout=timeout, use_mock=use_mock)

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
    args = parser.parse_args()

    asyncio.run(run_scenario(scenario_name=args.scenario, timeout=args.timeout, use_mock=args.mock))


if __name__ == "__main__":
    main()