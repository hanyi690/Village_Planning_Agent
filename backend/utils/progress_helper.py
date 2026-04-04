"""
Progress calculation utilities
进度计算工具
"""

from typing import Optional, Dict, Any


def calculate_progress(
    phase: Optional[str] = None,
    completion_status: Optional[Dict[str, Any]] = None,
    current_layer: Optional[int] = None,
) -> float:
    """
    Calculate progress percentage from phase and completion status
    根据阶段和完成状态计算进度百分比

    Args:
        phase: Current phase ("init", "layer1", "layer2", "layer3", "completed")
        completion_status: Dict with layer completion flags {"layer1": bool, ...}
        current_layer: (deprecated) Direct layer number, use phase instead

    Returns:
        Progress percentage (0-100)

    Examples:
        >>> calculate_progress("layer1", {})
        33.33
        >>> calculate_progress("layer2", {"layer1": True})
        66.67
        >>> calculate_progress("completed", {"layer1": True, "layer2": True, "layer3": True})
        100.0
    """
    # Handle deprecated single-parameter call
    if current_layer is not None and phase is None:
        if not current_layer or current_layer >= 4:
            return 100.0
        return (current_layer / 3) * 100

    # New multi-parameter logic
    if phase == "completed":
        return 100.0

    if not phase or phase == "init":
        return 0.0

    # Map phase to layer number
    layer_map = {"layer1": 1, "layer2": 2, "layer3": 3}
    layer_num = layer_map.get(phase, 0)

    if layer_num == 0:
        return 0.0

    # Calculate progress considering completed layers
    completed_count = 0
    if completion_status:
        completed_count = sum(1 for i in range(1, layer_num) if completion_status.get(f"layer{i}", False))

    # Progress: completed layers + current layer progress
    base_progress = (completed_count / 3) * 100
    current_layer_progress = (1 / 3) * 100 if layer_num <= 3 else 0

    return min(base_progress + current_layer_progress, 100.0)
