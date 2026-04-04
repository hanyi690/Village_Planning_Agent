"""
统一规划状态定义

Router Agent 架构核心状态。
"""

import operator
from typing import TypedDict, List, Dict, Any, Optional
from typing_extensions import Annotated
from enum import Enum
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

# 复用 dimension_metadata.py 的波次配置
from ..config.dimension_metadata import (
    get_layer_dimensions as _get_layer_dimensions,
    get_wave_config,
)


class PlanningPhase(Enum):
    """规划阶段枚举"""
    INIT = "init"
    LAYER1 = "layer1"
    LAYER2 = "layer2"
    LAYER3 = "layer3"
    COMPLETED = "completed"


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
    for wave_num, config in wave_config.items():
        for dim in config.get("dimensions", []):
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
    PlanningPhase.INIT.value,
    PlanningPhase.LAYER1.value,
    PlanningPhase.LAYER2.value,
    PlanningPhase.LAYER3.value,
    PlanningPhase.COMPLETED.value
]

# 层级名称映射
LAYER_NAMES: Dict[str, str] = {
    "layer1": "现状分析",
    "layer2": "规划思路",
    "layer3": "详细规划",
}

# 整数键版本（便于直接用 layer number 查询）
LAYER_NAMES_BY_NUMBER: Dict[int, str] = {
    1: "现状分析",
    2: "规划思路",
    3: "详细规划",
}


def get_layer_name(layer: int) -> str:
    """Get layer name by layer number (1-3)"""
    return LAYER_NAMES_BY_NUMBER.get(layer, f"Layer {layer}")

# 阶段描述映射
PHASE_DESCRIPTIONS: Dict[str, str] = {
    PlanningPhase.INIT.value: "初始化阶段，准备开始规划",
    PlanningPhase.LAYER1.value: "现状分析阶段，正在分析村庄现状",
    PlanningPhase.LAYER2.value: "规划思路阶段，正在制定规划方向",
    PlanningPhase.LAYER3.value: "详细规划阶段，正在制定具体方案",
    PlanningPhase.COMPLETED.value: "规划已完成",
}


class PlanningConfig(TypedDict):
    """规划配置"""
    village_data: str
    task_description: str
    constraints: str
    knowledge_cache: Dict[str, str]


class UnifiedPlanningState(TypedDict):
    """
    统一规划状态 - Router Agent 架构核心

    特性：
    1. 单一 State 消灭双写问题
    2. Checkpoint 完整记录聊天+规划
    3. Send API 实现维度并行分发
    """
    # 核心驱动
    messages: Annotated[List[BaseMessage], add_messages]

    # 业务参数
    session_id: str
    project_name: str
    config: PlanningConfig

    # 执行进度
    phase: str
    current_wave: int
    reports: Dict[str, Dict[str, str]]
    completed_dimensions: Dict[str, List[str]]

    # Send API 自动合并
    dimension_results: Annotated[List[Dict], operator.add]
    sse_events: Annotated[List[Dict], operator.add]

    # 交互控制
    pending_review: bool
    need_revision: bool
    revision_target_dimensions: List[str]
    review_feedback: str

    # 元数据
    metadata: Dict[str, Any]


def create_initial_state(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束"
) -> UnifiedPlanningState:
    """创建初始规划状态"""
    return UnifiedPlanningState(
        session_id=session_id,
        project_name=project_name,
        messages=[],
        phase=PlanningPhase.INIT.value,
        current_wave=1,
        reports={"layer1": {}, "layer2": {}, "layer3": {}},
        config=PlanningConfig(
            village_data=village_data,
            task_description=task_description,
            constraints=constraints,
            knowledge_cache={}
        ),
        completed_dimensions={"layer1": [], "layer2": [], "layer3": []},
        dimension_results=[],
        sse_events=[],
        pending_review=False,
        need_revision=False,
        revision_target_dimensions=[],
        review_feedback="",
        metadata={}
    )


def _phase_to_layer(phase: str) -> int:
    """phase 转 layer 编号（使用 PHASE_ORDER）"""
    try:
        return PHASE_ORDER.index(phase)
    except ValueError:
        return 0


def _layer_to_phase(layer: int) -> str:
    """layer 编号转 phase（使用 PHASE_ORDER）"""
    if 0 <= layer < len(PHASE_ORDER):
        return PHASE_ORDER[layer]
    return PlanningPhase.INIT.value


def get_layer_dimensions(layer: int) -> List[str]:
    """获取指定层级的所有维度"""
    return LAYER_DIMENSIONS.get(layer, [])


def get_wave_dimensions(layer: int, wave: int) -> List[str]:
    """获取指定层级和波次的维度"""
    return WAVE_DIMENSIONS.get(layer, {}).get(wave, [])


def get_total_waves(layer: int) -> int:
    """获取指定层级的总波次数"""
    return TOTAL_WAVES.get(layer, 1)


def get_next_phase(current_phase: str) -> Optional[str]:
    """获取下一阶段"""
    try:
        idx = PHASE_ORDER.index(current_phase)
        if idx < len(PHASE_ORDER) - 1:
            return PHASE_ORDER[idx + 1]
    except ValueError:
        pass
    return None


__all__ = [
    "PlanningPhase",
    "PlanningConfig",
    "UnifiedPlanningState",
    "create_initial_state",
    "_phase_to_layer",
    "_layer_to_phase",
    "get_layer_dimensions",
    "get_wave_dimensions",
    "get_total_waves",
    "get_next_phase",
    "LAYER_NAMES",
    "LAYER_NAMES_BY_NUMBER",
    "get_layer_name",
    "PHASE_DESCRIPTIONS",
]