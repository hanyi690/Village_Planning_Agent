"""
依赖计算器

计算维度的 Wave 波次（基于同层依赖关系）。
"""

from typing import Dict, List, Set, Optional

from .loader import PlanningConfig, PhaseConfig, DimensionConfig, _get_cached_config


def calculate_waves(phase: PhaseConfig) -> Dict[str, int]:
    """计算阶段内所有维度的执行波次"""
    waves: Dict[str, int] = {}

    for dim in phase.dimensions:
        wave = _calculate_dimension_wave(dim, waves, set())
        waves[dim.key] = wave

    return waves


def _calculate_dimension_wave(
    dim: DimensionConfig,
    waves: Dict[str, int],
    visited: Set[str]
) -> int:
    """计算单个维度的波次（递归）"""
    if dim.key in visited:
        return 1

    visited.add(dim.key)

    if not dim.depends_on:
        return 1

    max_dep_wave = 0
    for dep_key in dim.depends_on:
        if dep_key in waves:
            max_dep_wave = max(max_dep_wave, waves[dep_key])
        else:
            max_dep_wave = max(max_dep_wave, 1)

    return 1 + max_dep_wave


def get_wave_dimensions(phase: PhaseConfig, wave: int) -> List[str]:
    """获取指定波次的维度列表"""
    waves = calculate_waves(phase)
    return [key for key, w in waves.items() if w == wave]


def get_total_waves(phase: PhaseConfig) -> int:
    """获取阶段的总波次数"""
    waves = calculate_waves(phase)
    if not waves:
        return 0
    return max(waves.values())


def get_downstream_dependencies(
    config: PlanningConfig,
    phase_id: str,
    dimension_key: str
) -> List[str]:
    """获取指定维度的下游依赖"""
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
    """获取维度修改的影响树"""
    impact_tree: Dict[int, List[str]] = {}
    phase = None
    for p in config.phases:
        if p.id == phase_id:
            phase = p
            break

    if not phase:
        return impact_tree

    all_downstream = _get_all_downstream(phase, dimension_key, set())

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
    """递归获取所有下游依赖"""
    if dimension_key in visited:
        return []

    visited.add(dimension_key)
    downstream = []

    for dim in phase.dimensions:
        if dimension_key in dim.depends_on:
            downstream.append(dim.key)
            downstream.extend(_get_all_downstream(phase, dim.key, visited))

    return downstream


def get_downstream_dependencies_compat(dimension_key: str) -> List[str]:
    """获取依赖指定维度的所有下游维度"""
    config = _get_cached_config()
    downstream = []

    for phase in config.phases:
        for dim in phase.dimensions:
            if dimension_key in dim.depends_on:
                downstream.append(dim.key)
            if dimension_key in dim.layer_depends_on:
                downstream.append(dim.key)
            if dimension_key in dim.phase_depends_on:
                downstream.append(dim.key)

    return downstream


def get_impact_tree_compat(dimension_key: str) -> Dict[int, List[str]]:
    """获取维度修改后的影响树"""
    impact_tree: Dict[int, List[str]] = {}
    visited = {dimension_key}
    current_wave_dims = [dimension_key]
    wave = 0

    while current_wave_dims:
        next_wave_dims = []
        for dim in current_wave_dims:
            downstream = get_downstream_dependencies_compat(dim)
            for dep_dim in downstream:
                if dep_dim not in visited:
                    visited.add(dep_dim)
                    next_wave_dims.append(dep_dim)

        if next_wave_dims:
            wave += 1
            chain = get_full_dependency_chain()
            sorted_dims = sorted(
                next_wave_dims,
                key=lambda d: chain.get(d, {}).get("wave", 1)
            )
            impact_tree[wave] = sorted_dims

        current_wave_dims = next_wave_dims

    return impact_tree


def get_next_revision_wave(
    impact_tree: Dict[int, List[str]],
    completed_dims: List[str]
) -> Optional[List[str]]:
    """获取修订影响树中下一个待执行的波次"""
    for wave in sorted(impact_tree.keys()):
        wave_dims = impact_tree[wave]
        if not all(d in completed_dims for d in wave_dims):
            return wave_dims
    return None


def get_analysis_to_concept_mapping() -> Dict[str, List[str]]:
    """获取现状分析到规划思路的映射"""
    config = _get_cached_config()
    mapping = {}
    phase2 = None
    for phase in config.phases:
        if phase.id == "layer2":
            phase2 = phase
            break

    if phase2:
        for dim in phase2.dimensions:
            mapping[dim.key] = dim.layer_depends_on

    return mapping


def get_concept_to_detailed_mapping() -> Dict[str, List[str]]:
    """获取规划思路到详细规划的映射"""
    config = _get_cached_config()
    mapping = {}
    phase3 = None
    for phase in config.phases:
        if phase.id == "layer3":
            phase3 = phase
            break

    if phase3:
        for dim in phase3.dimensions:
            mapping[dim.key] = dim.phase_depends_on

    return mapping


def get_full_dependency_chain() -> Dict[str, Dict]:
    """获取完整的三层依赖关系映射"""
    config = _get_cached_config()
    chain = {}

    for phase in config.phases:
        layer = int(phase.id.replace("layer", ""))
        waves = calculate_waves(phase)

        for dim in phase.dimensions:
            chain[dim.key] = {
                "layer": layer,
                "layer_depends_on": dim.layer_depends_on,
                "phase_depends_on": dim.phase_depends_on,
                "depends_on_same_layer": dim.depends_on,
                "wave": waves.get(dim.key, 1)
            }

    return chain


def get_full_dependency_chain_func(dimension_key: str) -> Dict:
    """获取单个维度的依赖链"""
    chain = get_full_dependency_chain()
    return chain.get(dimension_key, {})


def get_execution_wave(dimension_key: str) -> int:
    """获取维度所属的执行波次"""
    chain = get_full_dependency_chain()
    if dimension_key in chain:
        return chain[dimension_key].get("wave", 1)
    return 1


def check_detailed_dependencies_ready(
    dimension_key: str,
    completed_dimensions: List[str]
) -> bool:
    """检查详细规划维度的依赖是否就绪"""
    chain = get_full_dependency_chain()
    if dimension_key not in chain:
        return True

    deps = chain[dimension_key]
    completed_set = set(completed_dimensions)

    for dep in deps.get("layer_depends_on", []):
        if dep not in completed_set:
            return False

    for dep in deps.get("phase_depends_on", []):
        if dep not in completed_set:
            return False

    for dep in deps.get("depends_on_same_layer", []):
        if dep not in completed_set:
            return False

    return True


def get_revision_wave_dimensions(
    target_dimensions: List[str],
    completed_dimensions: List[str]
) -> Dict[int, List[str]]:
    """获取修复任务中当前可执行的维度"""
    completed_set = set(completed_dimensions)
    all_impact_dims: Dict[str, int] = {}

    for target_dim in target_dimensions:
        if target_dim not in all_impact_dims:
            all_impact_dims[target_dim] = 0

        impact_tree = get_impact_tree_compat(dimension_key=target_dim)
        for wave, dims in impact_tree.items():
            for dim in dims:
                if dim not in all_impact_dims:
                    all_impact_dims[dim] = wave
                else:
                    all_impact_dims[dim] = max(all_impact_dims[dim], wave)

    pending_dims = {dim: wave for dim, wave in all_impact_dims.items()
                    if dim in completed_set}

    result: Dict[int, List[str]] = {}
    for dim, wave in pending_dims.items():
        if wave not in result:
            result[wave] = []
        result[wave].append(dim)

    chain = get_full_dependency_chain()
    for w in result:
        result[w] = sorted(result[w], key=lambda d: chain.get(d, {}).get("wave", 1))

    return result


def get_wave_config() -> Dict[int, Dict]:
    """获取波次配置"""
    chain = get_full_dependency_chain()
    waves = {}

    for key, deps in chain.items():
        layer = deps.get("layer", 1)
        wave = deps.get("wave", 1)

        if layer >= 2:
            if wave not in waves:
                waves[wave] = {
                    "dimensions": [],
                    "description": f"Wave {wave}"
                }
            waves[wave]["dimensions"].append(key)

    for wave_num in sorted(waves.keys()):
        if wave_num == 1:
            waves[wave_num]["description"] = f"第一波次：{len(waves[wave_num]['dimensions'])}个独立维度并行执行"
        else:
            waves[wave_num]["description"] = f"第{wave_num}波次：依赖前序波次的维度"

    return waves