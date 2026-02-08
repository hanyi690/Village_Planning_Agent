"""
Progress calculation utilities
进度计算工具
"""

from typing import Optional


def calculate_progress(current_layer: Optional[int]) -> float:
    """
    Calculate progress percentage from current layer
    根据当前层级计算进度百分比

    Args:
        current_layer: Current layer number (1-3), None, or >=4

    Returns:
        Progress percentage (0-100)

    Examples:
        >>> calculate_progress(1)
        33.33
        >>> calculate_progress(2)
        66.67
        >>> calculate_progress(3)
        100.0
        >>> calculate_progress(4)
        100.0
        >>> calculate_progress(None)
        100.0
    """
    if not current_layer or current_layer >= 4:
        return 100.0
    return (current_layer / 3) * 100
