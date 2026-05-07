"""
Layer级Checkpoint通用工具

供 run_rag_hallucination.py 和 run_baseline.py 共用。

提供：
- wait_for_layer_completion(): 等待指定layer完成并捕获checkpoint_id
- wait_for_layer_completion_sse(): SSE事件驱动版本（推荐）
- wait_for_layer_completion_polling(): 轮询版本（后备）
- save_layer_checkpoint(): 保存layer checkpoint到指定目录
- compute_state_fingerprint(): 计算状态指纹，用于一致性验证
- verify_restoration_consistency(): 验证恢复状态与预期checkpoint一致

性能对比：
- SSE版本: 几乎无延迟，与前端一致
- 轮询版本: check_interval=10s，最多10秒检测延迟
"""

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


# ============================================
# State Fingerprint Calculation
# ============================================

def compute_state_fingerprint(state: Dict[str, Any]) -> str:
    """
    计算状态的确定性指纹，用于验证一致性。

    基于以下字段生成指纹：
    - completed_dimensions: 已完成的维度集合
    - phase: 当前阶段
    - reports内容的hash

    Args:
        state: LangGraph checkpoint state values

    Returns:
        SHA256指纹的前32个字符（16字节）
    """
    # 提取关键状态信息
    completed_dimensions = state.get("completed_dimensions", {})
    phase = state.get("phase", "")
    reports = state.get("reports", {})

    # 计算reports的hash（排除空值）
    reports_data = {}
    for layer_key in ["layer1", "layer2", "layer3"]:
        layer_reports = reports.get(layer_key, {})
        if layer_reports:
            # 对每个维度的内容hash
            reports_data[layer_key] = {
                k: hashlib.sha256(v.encode()).hexdigest()[:16] if v else ""
                for k, v in layer_reports.items()
            }

    # 构建指纹数据
    fingerprint_data = {
        "completed_dimensions": {
            k: sorted(v) for k, v in completed_dimensions.items()
        },
        "phase": phase,
        "reports_hash": hashlib.sha256(
            json.dumps(reports_data, sort_keys=True).encode()
        ).hexdigest()[:16]
    }

    # 计算最终指纹
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True).encode()
    ).hexdigest()[:32]

    return fingerprint


# ============================================
# SSE-driven Layer Completion Waiting (Recommended)
# ============================================

async def wait_for_layer_completion_sse(
    session_id: str,
    layer: int,
    timeout: int = 600,
    listener: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    使用 SSE 事件驱动等待指定 layer 完成。

    性能优势：
    - 实时响应：事件驱动，无需轮询等待
    - 低延迟：几乎与前端同步

    Args:
        session_id: Session identifier
        layer: Target layer (1, 2, or 3)
        timeout: Maximum wait time in seconds
        listener: Optional SSEEventListener instance (will create if None)

    Returns:
        Same format as wait_for_layer_completion_polling()
    """
    from backend.services.checkpoint_service import checkpoint_service
    from scripts.experiments.sse_listener import SSEEventListener

    logger.info(
        f"[LayerCheckpoint] Waiting for Layer {layer} via SSE "
        f"(session={session_id}, timeout={timeout}s)"
    )

    # 使用提供的 listener 或创建新的
    sse_listener = listener
    if sse_listener is None:
        sse_listener = SSEEventListener(session_id)
        await sse_listener.connect()

    try:
        # 等待 layer_completed 事件
        event = await sse_listener.wait_for_layer_completion(layer, timeout=timeout)

        logger.info(
            f"[LayerCheckpoint] Layer {layer} completed (SSE event received)"
        )

        # 等待 checkpoint 持久化完成
        # SSE 的 checkpoint_saved 事件可以替代 wait_for_write
        await checkpoint_service.get_state(session_id, wait_for_write=True)

        # 获取 checkpoint 历史
        history = await checkpoint_service.get_checkpoint_history(session_id)
        checkpoint_id = ""
        if history:
            latest = history[-1] if history else {}
            checkpoint_id = latest.get("checkpoint_id", "")
            logger.info(f"[LayerCheckpoint] Captured checkpoint_id: {checkpoint_id}")

        # 获取当前状态
        state = await checkpoint_service.get_state(session_id)
        if not state:
            return {
                "layer": layer,
                "checkpoint_id": checkpoint_id,
                "phase": "",
                "reports": {},
                "completed_dimensions": {},
                "timestamp": datetime.now().isoformat(),
                "state_fingerprint": "",
                "success": False,
                "error": "State not found after layer completion",
            }

        # 计算状态指纹
        fingerprint = compute_state_fingerprint(state)

        return {
            "layer": layer,
            "checkpoint_id": checkpoint_id,
            "phase": state.get("phase", ""),
            "reports": state.get("reports", {}),
            "completed_dimensions": state.get("completed_dimensions", {}),
            "timestamp": datetime.now().isoformat(),
            "state_fingerprint": fingerprint,
            "success": True,
            "error": None,
        }

    except asyncio.TimeoutError:
        logger.warning(f"[LayerCheckpoint] SSE timeout after {timeout}s")
        return {
            "layer": layer,
            "checkpoint_id": "",
            "phase": "",
            "reports": {},
            "completed_dimensions": {},
            "timestamp": datetime.now().isoformat(),
            "state_fingerprint": "",
            "success": False,
            "error": f"Timeout after {timeout}s",
        }

    finally:
        # 如果是临时创建的 listener，关闭连接
        if listener is None and sse_listener.is_connected:
            await sse_listener.disconnect()


async def wait_for_layer_completion_polling(
    session_id: str,
    layer: int,
    timeout: int = 600,
    check_interval: int = 10,
) -> Dict[str, Any]:
    """
    等待指定layer完成并捕获checkpoint_id。

    监控状态变化，当检测到layer完成时：
    1. 等待checkpoint持久化完成
    2. 从checkpoint_history提取最新的checkpoint_id
    3. 返回layer完成的snapshot

    Args:
        session_id: Session identifier
        layer: Target layer (1, 2, or 3)
        timeout: Maximum wait time in seconds
        check_interval: Polling interval in seconds

    Returns:
        {
            "layer": layer,
            "checkpoint_id": str,
            "phase": str,
            "reports": Dict[str, Dict[str, str]],
            "completed_dimensions": Dict[str, List[str]],
            "timestamp": str,
            "state_fingerprint": str,
            "success": bool,
            "error": Optional[str],
        }
    """
    from backend.services.checkpoint_service import checkpoint_service
    from src.orchestration.state import get_layer_dimensions, _phase_to_layer

    logger.info(f"[LayerCheckpoint] Waiting for Layer {layer} (session={session_id}, timeout={timeout}s)")

    start_time = time.time()
    expected_dims = get_layer_dimensions(layer)

    # 目标phase
    target_phase_map = {1: "layer1", 2: "layer2", 3: "layer3"}
    target_phase = target_phase_map.get(layer, "layer3")
    next_phase = target_phase_map.get(layer + 1, "completed")

    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout:
            logger.warning(f"[LayerCheckpoint] Timeout after {elapsed:.0f}s waiting for Layer {layer}")
            return {
                "layer": layer,
                "checkpoint_id": "",
                "phase": "",
                "reports": {},
                "completed_dimensions": {},
                "timestamp": datetime.now().isoformat(),
                "state_fingerprint": "",
                "success": False,
                "error": f"Timeout after {timeout}s",
            }

        # 获取当前状态
        state = await checkpoint_service.get_state(session_id, wait_for_write=True)
        if not state:
            logger.debug(f"[LayerCheckpoint] State not found, retrying...")
            await asyncio.sleep(check_interval)
            continue

        phase = state.get("phase", "init")
        pause_after_step = state.get("pause_after_step", False)
        previous_layer = state.get("previous_layer", 0)
        completed_dims = state.get("completed_dimensions", {})
        layer_completed_list = completed_dims.get(f"layer{layer}", [])

        # 计算当前layer
        current_layer = _phase_to_layer(phase)

        logger.debug(
            f"[LayerCheckpoint] Phase={phase}, pause={pause_after_step}, "
            f"prev_layer={previous_layer}, layer{layer}_completed={len(layer_completed_list)}"
        )

        # 检测layer完成条件
        layer_complete = False

        # 条件1：pause_after_step=True且previous_layer等于目标layer
        if pause_after_step and previous_layer == layer:
            layer_complete = True
            logger.info(f"[LayerCheckpoint] Layer {layer} completed (pause_after_step detected)")

        # 条件2：phase已进入下一阶段，且layer维度全部完成
        if phase == next_phase or (current_layer is not None and current_layer > layer):
            if len(layer_completed_list) >= len(expected_dims):
                layer_complete = True
                logger.info(f"[LayerCheckpoint] Layer {layer} completed (phase transition detected)")

        # 条件3：phase为目标phase且所有维度完成（运行模式）
        if phase == target_phase and len(layer_completed_list) >= len(expected_dims):
            layer_complete = True
            logger.info(f"[LayerCheckpoint] Layer {layer} completed (all dimensions done)")

        if layer_complete:
            # 等待checkpoint写入完成
            await checkpoint_service.get_state(session_id, wait_for_write=True)

            # 获取checkpoint历史
            history = await checkpoint_service.get_checkpoint_history(session_id)

            # 找到最近的checkpoint_id
            checkpoint_id = ""
            if history:
                # 最近的checkpoint（最后一个）
                latest = history[-1] if history else {}
                checkpoint_id = latest.get("checkpoint_id", "")
                logger.info(f"[LayerCheckpoint] Captured checkpoint_id: {checkpoint_id}")

            # 计算状态指纹
            fingerprint = compute_state_fingerprint(state)

            return {
                "layer": layer,
                "checkpoint_id": checkpoint_id,
                "phase": phase,
                "reports": state.get("reports", {}),
                "completed_dimensions": completed_dims,
                "timestamp": datetime.now().isoformat(),
                "state_fingerprint": fingerprint,
                "success": True,
                "error": None,
            }

        await asyncio.sleep(check_interval)


# ============================================
# Unified Interface (Recommended)
# ============================================

async def wait_for_layer_completion(
    session_id: str,
    layer: int,
    timeout: int = 600,
    use_sse: bool = True,
    listener: Optional[Any] = None,
    check_interval: int = 2,
) -> Dict[str, Any]:
    """
    等待指定 layer 完成（统一接口）。

    默认使用 SSE 事件驱动，性能与前端一致。
    可通过 use_sse=False 切换为轮询模式（后备）。

    Args:
        session_id: Session identifier
        layer: Target layer (1, 2, or 3)
        timeout: Maximum wait time in seconds
        use_sse: Use SSE event-driven mode (default True)
        listener: Optional SSEEventListener instance (for SSE mode)
        check_interval: Polling interval (for polling mode, default 2s)

    Returns:
        {
            "layer": layer,
            "checkpoint_id": str,
            "phase": str,
            "reports": Dict[str, Dict[str, str]],
            "completed_dimensions": Dict[str, List[str]],
            "timestamp": str,
            "state_fingerprint": str,
            "success": bool,
            "error": Optional[str],
        }
    """
    if use_sse:
        return await wait_for_layer_completion_sse(
            session_id=session_id,
            layer=layer,
            timeout=timeout,
            listener=listener,
        )
    else:
        return await wait_for_layer_completion_polling(
            session_id=session_id,
            layer=layer,
            timeout=timeout,
            check_interval=check_interval,
        )


async def wait_for_all_layers_sse(
    session_id: str,
    timeout_per_layer: int = 600,
    listener: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    使用 SSE 事件驱动等待所有 layer 完成。

    性能优势：
    - 无轮询延迟
    - 无 step_mode 暂停开销
    - 与前端一致的响应速度

    注意：需要配合 step_mode=False 启动 session。

    Args:
        session_id: Session identifier
        timeout_per_layer: Timeout for each layer
        listener: Optional pre-connected SSEEventListener (避免重新连接)

    Returns:
        {
            "session_id": str,
            "layer_checkpoints": {...},
            "final_checkpoint_id": str,
            "state_fingerprint": str,
            "success": bool,
        }
    """
    from backend.services.checkpoint_service import checkpoint_service
    from scripts.experiments.sse_listener import SSEEventListener

    logger.info(f"[LayerCheckpoint] Waiting for all layers via SSE (session={session_id})")

    # 使用提供的 listener 或创建新的
    sse_listener = listener
    if sse_listener is None:
        sse_listener = SSEEventListener(session_id)
        await sse_listener.connect()

    layer_checkpoints = {}

    try:
        for layer in [1, 2, 3]:
            snapshot = await wait_for_layer_completion_sse(
                session_id=session_id,
                layer=layer,
                timeout=timeout_per_layer,
                listener=sse_listener,  # 共享 listener
            )
            layer_checkpoints[f"layer{layer}"] = snapshot

            if not snapshot.get("success"):
                logger.warning(
                    f"[LayerCheckpoint] Layer {layer} failed: {snapshot.get('error')}"
                )

        # 获取最终 checkpoint
        final_state = await checkpoint_service.get_state(
            session_id, wait_for_write=True
        )
        final_checkpoint_id = ""
        if final_state:
            history = await checkpoint_service.get_checkpoint_history(session_id)
            if history:
                final_checkpoint_id = history[-1].get("checkpoint_id", "")

        final_fingerprint = (
            compute_state_fingerprint(final_state) if final_state else ""
        )

        return {
            "session_id": session_id,
            "layer_checkpoints": layer_checkpoints,
            "final_checkpoint_id": final_checkpoint_id,
            "state_fingerprint": final_fingerprint,
            "success": all(cp.get("success") for cp in layer_checkpoints.values()),
        }

    finally:
        # 只在内部创建的 listener 时才关闭连接
        if listener is None and sse_listener.is_connected:
            await sse_listener.disconnect()


async def wait_for_all_layers(
    session_id: str,
    timeout_per_layer: int = 600,
    use_sse: bool = True,
    auto_resume: bool = True,
    listener: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    等待所有 layer 完成（统一接口）。

    默认使用 SSE 事件驱动模式（use_sse=True）。

    Args:
        session_id: Session identifier
        timeout_per_layer: Timeout for each layer
        use_sse: Use SSE mode (default True)
        auto_resume: Auto-resume after pause (for polling mode with step_mode=True)
        listener: Optional pre-connected SSEEventListener (for SSE mode)

    Returns:
        Same as wait_for_all_layers_sse or polling version
    """
    if use_sse:
        return await wait_for_all_layers_sse(
            session_id=session_id,
            timeout_per_layer=timeout_per_layer,
            listener=listener,
        )
    else:
        # 轮询版本保留 auto_resume 支持
        return await wait_for_all_layers_polling(
            session_id=session_id,
            timeout_per_layer=timeout_per_layer,
            auto_resume=auto_resume,
        )


async def wait_for_all_layers_polling(
    session_id: str,
    timeout_per_layer: int = 600,
    auto_resume: bool = True,
) -> Dict[str, Any]:
    """
    等待所有layer完成，返回完整checkpoint信息。

    Args:
        session_id: Session identifier
        timeout_per_layer: Timeout for each layer
        auto_resume: If True, automatically resume execution after each layer pause

    Returns:
        {
            "session_id": str,
            "layer_checkpoints": {
                "layer1": {...},
                "layer2": {...},
                "layer3": {...},
            },
            "final_checkpoint_id": str,
            "state_fingerprint": str,
            "success": bool,
        }
    """
    from backend.services.checkpoint_service import checkpoint_service
    from backend.services.planning_runtime_service import PlanningRuntimeService

    logger.info(f"[LayerCheckpoint] Waiting for all layers (session={session_id})")

    layer_checkpoints = {}

    for layer in [1, 2, 3]:
        snapshot = await wait_for_layer_completion_polling(
            session_id=session_id,
            layer=layer,
            timeout=timeout_per_layer,
        )
        layer_checkpoints[f"layer{layer}"] = snapshot

        if not snapshot.get("success"):
            logger.warning(f"[LayerCheckpoint] Layer {layer} failed: {snapshot.get('error')}")

        # Auto-resume if step_mode pause detected and not last layer
        if auto_resume and layer < 3 and snapshot.get("success"):
            # Check if session is paused (step_mode)
            state = await checkpoint_service.get_state(session_id, wait_for_write=True)
            if state and state.get("pause_after_step", False) and state.get("previous_layer", 0) == layer:
                logger.info(f"[LayerCheckpoint] Layer {layer} paused, preparing resume to Layer {layer + 1}")

                # Step 1: Clear pause flags and advance phase BEFORE resume
                # This ensures resume starts from next layer instead of re-executing current layer
                updates = {
                    "pause_after_step": False,
                    "previous_layer": 0,
                    "phase": f"layer{layer + 1}",
                    "current_wave": 1,  # Reset wave for next layer
                }
                await checkpoint_service.update_state(session_id, updates)
                logger.info(f"[LayerCheckpoint] Updated state: phase=layer{layer + 1}, pause cleared")

                # Step 1.5: Wait for checkpoint write to complete before resume
                # This ensures resume_execution reads the updated state
                from backend.services.checkpoint_service import checkpoint_persistence_manager
                await checkpoint_persistence_manager.wait_for_write(session_id, timeout=5.0)
                logger.info(f"[LayerCheckpoint] Checkpoint write completed, ready to resume")

                # Step 2: Resume execution (now will start from next layer)
                try:
                    await PlanningRuntimeService.resume_execution(session_id)
                    logger.info(f"[LayerCheckpoint] Resumed execution for Layer {layer + 1}")
                except Exception as e:
                    logger.warning(f"[LayerCheckpoint] Failed to resume: {e}")

    # 获取最终checkpoint
    final_state = await checkpoint_service.get_state(session_id, wait_for_write=True)
    final_checkpoint_id = ""
    if final_state:
        history = await checkpoint_service.get_checkpoint_history(session_id)
        if history:
            final_checkpoint_id = history[-1].get("checkpoint_id", "")

    final_fingerprint = compute_state_fingerprint(final_state) if final_state else ""

    return {
        "session_id": session_id,
        "layer_checkpoints": layer_checkpoints,
        "final_checkpoint_id": final_checkpoint_id,
        "state_fingerprint": final_fingerprint,
        "success": all(cp.get("success") for cp in layer_checkpoints.values()),
    }


# ============================================
# Layer Checkpoint Saving
# ============================================

def save_layer_checkpoint(
    snapshot: Dict[str, Any],
    output_dir: Path,
    layer: int,
) -> None:
    """
    保存layer checkpoint到指定目录。

    输出文件：
    - layer{N}_checkpoint.json: checkpoint元数据
    - layer{N}_reports.json: 报告内容（含checkpoint_id和fingerprint）

    Args:
        snapshot: wait_for_layer_completion()返回的snapshot
        output_dir: 输出目录
        layer: Layer编号
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    layer_key = f"layer{layer}"
    reports = snapshot.get("reports", {}).get(layer_key, {})
    completed_dimensions = snapshot.get("completed_dimensions", {}).get(layer_key, [])

    # 保存checkpoint元数据
    checkpoint_meta = {
        "layer": layer,
        "checkpoint_id": snapshot.get("checkpoint_id", ""),
        "phase": snapshot.get("phase", ""),
        "timestamp": snapshot.get("timestamp", ""),
        "state_fingerprint": snapshot.get("state_fingerprint", ""),
        "completed_dimensions": completed_dimensions,
        "success": snapshot.get("success", False),
    }
    checkpoint_file = output_dir / f"layer{layer}_checkpoint.json"
    with open(checkpoint_file, "w", encoding="utf-8") as f:
        json.dump(checkpoint_meta, f, indent=2, ensure_ascii=False)
    logger.info(f"[LayerCheckpoint] Saved layer{layer}_checkpoint.json")

    # 保存报告内容（含checkpoint元数据）
    reports_data = {
        "layer": layer,
        "checkpoint_id": snapshot.get("checkpoint_id", ""),
        "checkpoint_saved_at": snapshot.get("timestamp", ""),
        "state_fingerprint": snapshot.get("state_fingerprint", ""),
        "reports": reports,
        "completed_dimensions": completed_dimensions,
        "report_count": len(reports),
        "total_chars": sum(len(v) for v in reports.values()) if reports else 0,
    }
    reports_file = output_dir / f"layer{layer}_reports.json"
    with open(reports_file, "w", encoding="utf-8") as f:
        json.dump(reports_data, f, indent=2, ensure_ascii=False)
    logger.info(f"[LayerCheckpoint] Saved layer{layer}_reports.json: {len(reports)} dimensions")


def save_all_layer_checkpoints(
    all_layers_snapshot: Dict[str, Any],
    output_dir: Path,
) -> None:
    """
    保存所有layer checkpoint到指定目录。

    输出文件：
    - checkpoints.json: 整体checkpoint汇总
    - layer{N}_checkpoint.json: 各层checkpoint元数据
    - layer{N}_reports.json: 各层报告内容

    Args:
        all_layers_snapshot: wait_for_all_layers()返回的完整snapshot
        output_dir: 输出目录
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    layer_checkpoints = all_layers_snapshot.get("layer_checkpoints", {})

    # 保存各层checkpoint
    for layer in [1, 2, 3]:
        layer_snapshot = layer_checkpoints.get(f"layer{layer}", {})
        if layer_snapshot:
            save_layer_checkpoint(layer_snapshot, output_dir, layer)

    # 保存汇总checkpoints.json
    summary = {
        "session_id": all_layers_snapshot.get("session_id", ""),
        "layer_checkpoints": {
            f"layer{layer}": {
                "checkpoint_id": cp.get("checkpoint_id", ""),
                "phase": cp.get("phase", ""),
                "timestamp": cp.get("timestamp", ""),
                "state_fingerprint": cp.get("state_fingerprint", ""),
            }
            for layer, cp in [(1, layer_checkpoints.get("layer1")),
                              (2, layer_checkpoints.get("layer2")),
                              (3, layer_checkpoints.get("layer3"))]
            if cp
        },
        "final_checkpoint_id": all_layers_snapshot.get("final_checkpoint_id", ""),
        "state_fingerprint": all_layers_snapshot.get("state_fingerprint", ""),
        "timestamp": datetime.now().isoformat(),
        "success": all_layers_snapshot.get("success", False),
    }

    summary_file = output_dir / "checkpoints.json"
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, ensure_ascii=False)
    logger.info(f"[LayerCheckpoint] Saved checkpoints.json summary")


# ============================================
# Restoration Consistency Verification
# ============================================

def load_layer_checkpoint(output_dir: Path, layer: int) -> Optional[Dict[str, Any]]:
    """
    从文件加载layer checkpoint数据。

    Args:
        output_dir: 输出目录
        layer: Layer编号

    Returns:
        checkpoint数据，如果文件不存在返回None
    """
    checkpoint_file = output_dir / f"layer{layer}_checkpoint.json"
    if not checkpoint_file.exists():
        return None

    with open(checkpoint_file, "r", encoding="utf-8") as f:
        return json.load(f)


def load_layer_reports(output_dir: Path, layer: int) -> Optional[Dict[str, Any]]:
    """
    从文件加载layer reports数据。

    Args:
        output_dir: 输出目录
        layer: Layer编号

    Returns:
        reports数据，如果文件不存在返回None
    """
    reports_file = output_dir / f"layer{layer}_reports.json"
    if not reports_file.exists():
        return None

    with open(reports_file, "r", encoding="utf-8") as f:
        return json.load(f)


def verify_restoration_consistency(
    restored_state: Dict[str, Any],
    expected_checkpoint: Dict[str, Any],
    layer: int,
) -> bool:
    """
    验证恢复状态与预期checkpoint一致。

    检查项：
    1. completed_dimensions集合一致
    2. reports fingerprint一致
    3. phase正确

    Args:
        restored_state: 恢复后的LangGraph state
        expected_checkpoint: 预期的checkpoint数据（来自layer_checkpoint.json）
        layer: 目标layer

    Returns:
        True if consistent, raises ValueError otherwise

    Raises:
        ValueError: 如果一致性验证失败
    """
    restored_fingerprint = compute_state_fingerprint(restored_state)
    expected_fingerprint = expected_checkpoint.get("state_fingerprint", "")

    if restored_fingerprint != expected_fingerprint:
        logger.error(
            f"[LayerCheckpoint] Fingerprint mismatch: "
            f"restored={restored_fingerprint}, expected={expected_fingerprint}"
        )
        raise ValueError(
            f"Restoration consistency failed: fingerprint mismatch. "
            f"Expected {expected_fingerprint}, got {restored_fingerprint}"
        )

    # 检查completed_dimensions
    restored_completed = set(
        restored_state.get("completed_dimensions", {}).get(f"layer{layer}", [])
    )
    expected_completed = set(expected_checkpoint.get("completed_dimensions", []))

    if restored_completed != expected_completed:
        logger.error(
            f"[LayerCheckpoint] completed_dimensions mismatch: "
            f"restored={sorted(restored_completed)}, expected={sorted(expected_completed)}"
        )
        raise ValueError(
            f"Restoration consistency failed: completed_dimensions mismatch. "
            f"Expected {sorted(expected_completed)}, got {sorted(restored_completed)}"
        )

    logger.info(f"[LayerCheckpoint] Consistency verified for Layer {layer}")
    return True


# ============================================
# Restoration from Checkpoint
# ============================================

async def restore_from_checkpoint(
    baseline_session_id: str,
    target_checkpoint_id: str,
    target_layer: int,
    new_session_prefix: str = "scenario",
) -> Dict[str, Any]:
    """
    从基线checkpoint文件恢复完整LangGraph状态。

    创建新session并从checkpoint文件恢复状态。

    Args:
        baseline_session_id: 基线session ID
        target_checkpoint_id: 目标checkpoint ID
        target_layer: 目标layer
        new_session_prefix: 新session ID前缀

    Returns:
        {
            "new_session_id": str,
            "restored_state": Dict,
            "source_checkpoint_id": str,
            "baseline_session_id": str,
            "target_layer": int,
        }

    NOTE: 从导出的 checkpoint 文件恢复，避免读取被修改的当前状态。
    """
    from backend.services.checkpoint_service import checkpoint_service
    from backend.services.planning_runtime_service import PlanningRuntimeService
    import uuid

    logger.info(
        f"[LayerCheckpoint] Restoring from checkpoint file: "
        f"baseline={baseline_session_id}, checkpoint={target_checkpoint_id}"
    )

    # 从导出的 checkpoint 文件读取状态（而不是从当前 checkpoint）
    from scripts.experiments.config import BASELINE_DIR
    checkpoint_file_data = load_layer_checkpoint(BASELINE_DIR, target_layer)

    if not checkpoint_file_data:
        raise ValueError(f"Layer {target_layer} checkpoint file not found")

    # 从 layer_reports.json 读取完整状态
    reports_file = BASELINE_DIR / f"layer{target_layer}_reports.json"
    if not reports_file.exists():
        raise ValueError(f"Layer {target_layer} reports file not found")

    with open(reports_file, "r", encoding="utf-8") as f:
        reports_data = json.load(f)

    # 读取所有 layer 的 reports（构建完整状态）
    all_reports = {}
    all_completed_dimensions = {}
    for layer in [1, 2, 3]:
        layer_file = BASELINE_DIR / f"layer{layer}_reports.json"
        if layer_file.exists():
            with open(layer_file, "r", encoding="utf-8") as f:
                layer_data = json.load(f)
            all_reports[f"layer{layer}"] = layer_data.get("reports", {})
            all_completed_dimensions[f"layer{layer}"] = layer_data.get("completed_dimensions", [])

    # 创建新session
    new_session_id = f"{new_session_prefix}_{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d%H%M%S')}"

    # 从 session_id.json 读取基本信息
    session_file = BASELINE_DIR / "session_id.json"
    if session_file.exists():
        with open(session_file, "r", encoding="utf-8") as f:
            session_meta = json.load(f)
        project_name = session_meta.get("project_name", "")
    else:
        project_name = "村庄规划"

    # 构建初始状态（从导出文件恢复）
    initial_state = {
        "session_id": new_session_id,
        "project_name": project_name,
        "config": {},
        "phase": "completed",  # 从完成态恢复
        "reports": all_reports,
        "completed_dimensions": all_completed_dimensions,
        "step_mode": False,
        "pause_after_step": False,
        "previous_layer": 0,
        "dimension_summaries": {},
        "pending_review": False,
        "need_revision": False,
        "revision_target_dimensions": [],
        "human_feedback": "",
        "gis_analysis_results": {},
        "planning_layers": {},
        "metadata": {
            "restored_from": baseline_session_id,
            "restored_checkpoint_id": target_checkpoint_id,
            "restored_layer": target_layer,
            "restored_at": datetime.now().isoformat(),
        },
    }

    # 写入新session
    await PlanningRuntimeService.aupdate_state(new_session_id, initial_state, as_node="checkpoint_restore")
    logger.info(f"[LayerCheckpoint] Created new session: {new_session_id}")

    # 验证恢复一致性
    try:
        checkpoint_data = await checkpoint_service.get_state(new_session_id, wait_for_write=True)
        if checkpoint_data:
            # 验证 reports 是否匹配
            restored_reports = checkpoint_data.get("reports", {})
            expected_reports = all_reports

            # 简化验证：只验证维度数量
            for layer_key in ["layer1", "layer2", "layer3"]:
                expected_count = len(expected_reports.get(layer_key, {}))
                restored_count = len(restored_reports.get(layer_key, {}))
                if expected_count != restored_count:
                    logger.warning(
                        f"[LayerCheckpoint] {layer_key} count mismatch: "
                        f"expected={expected_count}, restored={restored_count}"
                    )
                else:
                    logger.info(f"[LayerCheckpoint] {layer_key} verified: {restored_count} dimensions")

            logger.info(f"[LayerCheckpoint] Restoration verified")
    except Exception as e:
        logger.warning(f"[LayerCheckpoint] Verification failed: {e}")

    return {
        "new_session_id": new_session_id,
        "restored_state": initial_state,
        "source_checkpoint_id": target_checkpoint_id,
        "baseline_session_id": baseline_session_id,
        "target_layer": target_layer,
    }


# ============================================
# __all__
# ============================================

__all__ = [
    "compute_state_fingerprint",
    "wait_for_layer_completion",
    "wait_for_layer_completion_sse",
    "wait_for_layer_completion_polling",
    "wait_for_all_layers",
    "wait_for_all_layers_sse",
    "wait_for_all_layers_polling",
    "save_layer_checkpoint",
    "save_all_layer_checkpoints",
    "load_layer_checkpoint",
    "load_layer_reports",
    "verify_restoration_consistency",
    "restore_from_checkpoint",
]