"""
依赖计算器

计算维度的 Wave 波次（基于同层依赖关系）。
Wave = 1 + max(wave of dependencies within same layer)
"""

from typing import Dict, List, Set

from .loader import PlanningConfig, PhaseConfig, DimensionConfig


def calculate_waves(phase: PhaseConfig) -> Dict[str, int]:
    """
    计算阶段内所有维度的执行波次

    Args:
        phase: 阶段配置

    Returns:
        Dict[str, int]: 维度键 -> 波次映射
    """
    waves: Dict[str, int] = {}

    # 按依赖顺序迭代计算
    for dim in phase.dimensions:
        wave = _calculate_dimension_wave(dim, waves, set())
        waves[dim.key] = wave

    return waves


def _calculate_dimension_wave(
    dim: DimensionConfig,
    waves: Dict[str, int],
    visited: Set[str]
) -> int:
    """
    计算单个维度的波次（递归）

    Args:
        dim: 维度配置
        waves: 已计算的波次映射
        visited: 已访问的维度集合（防止循环依赖）

    Returns:
        int: 波次值
    """
    if dim.key in visited:
        # 循环依赖，返回默认值
        return 1

    visited.add(dim.key)

    # 无同层依赖
    if not dim.depends_on:
        return 1

    # 计算所有依赖的波次
    max_dep_wave = 0
    for dep_key in dim.depends_on:
        if dep_key in waves:
            max_dep_wave = max(max_dep_wave, waves[dep_key])
        else:
            # 依赖尚未计算，递归计算（这种情况不应该发生，因为按顺序迭代）
            max_dep_wave = max(max_dep_wave, 1)

    return 1 + max_dep_wave


def get_wave_dimensions(phase: PhaseConfig, wave: int) -> List[str]:
    """
    获取指定波次的维度列表

    Args:
        phase: 阶段配置
        wave: 波次（1, 2, 3...）

    Returns:
        List[str]: 维度键列表
    """
    waves = calculate_waves(phase)
    return [key for key, w in waves.items() if w == wave]


def get_total_waves(phase: PhaseConfig) -> int:
    """
    获取阶段的总波次数

    Args:
        phase: 阶段配置

    Returns:
        int: 最大波次值
    """
    waves = calculate_waves(phase)
    if not waves:
        return 0
    return max(waves.values())


def get_downstream_dependencies(
    config: PlanningConfig,
    phase_id: str,
    dimension_key: str
) -> List[str]:
    """
    获取指定维度的下游依赖（直接依赖此维度的维度）

    Args:
        config: 规划配置
        phase_id: 阶段 ID
        dimension_key: 维度键

    Returns:
        List[str]: 下游维度键列表
    """
    downstream = []
    phase = None
    for p in config.phases:
        if p.id == phase_id:
            phase = p
            break

    if not phase:
        return downstream

    for dim in phase.dimensions:
        if dimension_key in dim.depends_on:
            downstream.append(dim.key)

    return downstream


def get_impact_tree(
    config: PlanningConfig,
    phase_id: str,
    dimension_key: str
) -> Dict[int, List[str]]:
    """
    获取维度修改的影响树

    当维度修改时，需要级联更新所有下游维度，按波次分组。

    Args:
        config: 规划配置
        phase_id: 阶段 ID
        dimension_key: 维度键

    Returns:
        Dict[int, List[str]: 波次 -> 受影响的维度列表
    """
    impact_tree: Dict[int, List[str]] = {}
    phase = None
    for p in config.phases:
        if p.id == phase_id:
            phase = p
            break

    if not phase:
        return impact_tree

    # 获取所有下游依赖（递归）
    all_downstream = _get_all_downstream(phase, dimension_key, set())

    # 计算各下游维度的波次并分组
    waves = calculate_waves(phase)
    for dim_key in all_downstream:
        wave = waves.get(dim_key, 1)
        if wave not in impact_tree:
            impact_tree[wave] = []
        impact_tree[wave].append(dim_key)

    return impact_tree


def _get_all_downstream(
    phase: PhaseConfig,
    dimension_key: str,
    visited: Set[str]
) -> List[str]:
    """
    递归获取所有下游依赖

    Args:
        phase: 阶段配置
        dimension_key: 维度键
        visited: 已访问的维度集合

    Returns:
        List[str]: 所有下游维度键列表
    """
    if dimension_key in visited:
        return []

    visited.add(dimension_key)
    downstream = []

    for dim in phase.dimensions:
        if dimension_key in dim.depends_on:
            downstream.append(dim.key)
            # 递归获取此下游维度的下游
            downstream.extend(_get_all_downstream(phase, dim.key, visited))

    return downstream