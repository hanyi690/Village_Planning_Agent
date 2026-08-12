"""Phase machine: PlanningPhase enum + layer/phase/wave conversion helpers.

Migrated from agent/state.py per docs/architecture/agent-graph.md §5.
"""

import operator
from enum import Enum
from typing import Dict, List, Optional

from app.config import get_layer_dimensions as _get_layer_dimensions, get_wave_config
from app.modules.schema.layers import LAYER_NAMES, LAYER_NAMES_BY_NUMBER, get_layer_name

DEFAULT_RAG_LAYER_CONFIG = {1: True, 2: False, 3: True}


# ==========================================
# 阶段枚举
# ==========================================

class PlanningPhase(Enum):
    """规划阶段"""
    INIT = "init"
    LAYER1 = "layer1"
    LAYER2 = "layer2"
    LAYER3 = "layer3"
    POST_L3 = "post_l3"


# ==========================================
# 维度配置常量
# ==========================================

LAYER_DIMENSIONS: Dict[int, List[str]] = {
    1: _get_layer_dimensions(1),
    2: _get_layer_dimensions(2),
    3: _get_layer_dimensions(3),
}


def _build_wave_dimensions() -> Dict[int, Dict[int, List[str]]]:
    """构建波次维度映射"""
    waves: Dict[int, Dict[int, List[str]]] = {1: {1: []}, 2: {}, 3: {}}
    waves[1][1] = LAYER_DIMENSIONS[1]

    wave_config = get_wave_config()
    for wave_num, cfg in wave_config.items():
        for dim in cfg.get("dimensions", []):
            if dim in LAYER_DIMENSIONS[2]:
                layer = 2
            elif dim in LAYER_DIMENSIONS[3]:
                layer = 3
            else:
                continue
            if wave_num not in waves[layer]:
                waves[layer][wave_num] = []
            waves[layer][wave_num].append(dim)
    return waves


WAVE_DIMENSIONS: Dict[int, Dict[int, List[str]]] = _build_wave_dimensions()

TOTAL_WAVES: Dict[int, int] = {
    layer: max(waves.keys()) if waves else 1
    for layer, waves in WAVE_DIMENSIONS.items()
}
TOTAL_WAVES[1] = 1

PHASE_ORDER: List[str] = [
    PlanningPhase.INIT.value, PlanningPhase.LAYER1.value,
    PlanningPhase.LAYER2.value, PlanningPhase.LAYER3.value,
    PlanningPhase.POST_L3.value,
]

PHASE_DESCRIPTIONS: Dict[str, str] = {
    PlanningPhase.INIT.value: "初始化阶段",
    PlanningPhase.LAYER1.value: "现状分析阶段",
    PlanningPhase.LAYER2.value: "规划思路阶段",
    PlanningPhase.LAYER3.value: "详细规划阶段",
    PlanningPhase.POST_L3.value: "空间规划执行与交付",
}


# ==========================================
# 辅助函数
# ==========================================

def _phase_to_layer(phase: str) -> Optional[int]:
    """phase 转 layer"""
    simple_map = {
        PlanningPhase.INIT.value: 0,
        PlanningPhase.LAYER1.value: 1,
        PlanningPhase.LAYER2.value: 2,
        PlanningPhase.LAYER3.value: 3,
    }
    if phase in simple_map:
        return simple_map[phase]
    if phase.startswith("layer") and "_" in phase:
        try:
            num = int(phase.split("_")[0].replace("layer", ""))
            if num in [1, 2, 3]:
                return num
        except (ValueError, IndexError):
            pass
    if phase == PlanningPhase.POST_L3.value:
        return None
    return None


def _layer_to_phase(layer: int) -> str:
    """layer 转 phase"""
    map_ = {1: PlanningPhase.LAYER1.value, 2: PlanningPhase.LAYER2.value, 3: PlanningPhase.LAYER3.value}
    return map_.get(layer, PlanningPhase.INIT.value)


def get_layer_dimensions(layer: int) -> List[str]:
    return LAYER_DIMENSIONS.get(layer, [])


def get_wave_dimensions(layer: int, wave: int) -> List[str]:
    return WAVE_DIMENSIONS.get(layer, {}).get(wave, [])


def get_total_waves(layer: int) -> int:
    return TOTAL_WAVES.get(layer, 1)


def get_next_phase(current_phase: str) -> Optional[str]:
    try:
        idx = PHASE_ORDER.index(current_phase)
        if idx < len(PHASE_ORDER) - 1:
            return PHASE_ORDER[idx + 1]
    except ValueError:
        pass
    return None
