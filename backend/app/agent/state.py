"""
统一规划状态定义 - 简化版

AgentState: 核心状态定义
辅助函数: phase/layer转换、维度查询
"""

import operator
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from enum import Enum
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from ..config import get_layer_dimensions as _get_layer_dimensions, get_wave_config


# ==========================================
# 状态定义
# ==========================================

class ReportVersion(TypedDict):
    """报告版本元数据"""
    version: int
    report_id: str
    summary: str
    generated_at: str
    revision_trigger: Optional[str]


class DimensionSummary(TypedDict):
    """维度摘要"""
    dimension_key: str
    dimension_name: str
    layer: int
    summary: str
    key_points: List[str]
    metrics: Dict[str, Any]
    tags: List[str]
    created_at: str


def _merge_dict_of_lists(a: Dict[str, List], b: Dict[str, List]) -> Dict[str, List]:
    """合并两个 {key: list} 字典，对同 key 的 list 去重拼接。用于并行 fan-in。"""
    result = {}
    all_keys = set(a.keys()) | set(b.keys())
    for k in all_keys:
        a_list = a.get(k, [])
        b_list = b.get(k, [])
        combined = a_list + b_list
        deduped = []
        for item in combined:
            if item not in deduped:
                deduped.append(item)
        result[k] = deduped
    return result


def _merge_dict_of_dicts(a: Dict[str, Dict], b: Dict[str, Dict]) -> Dict[str, Dict]:
    """递归合并两个 {key: dict} 字典，同 key 时自动合并嵌套 dict。用于并行 fan-in。"""
    result = {**a}
    for k, v in b.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = {**result[k], **v}
        else:
            result[k] = v
    return result


class AgentState(TypedDict, total=False):
    """
    核心状态 - 精简版

    字段：
    - messages: 消息流
    - session_id, project_name: 标识
    - phase, current_wave: 进度
    - completed_dimensions: 完成追踪 (Annotated: 并行合并)
    - config: 配置信息
    - feedback: 交互
    - dimension_key: Send API 注入
    - image_ids: 图片引用

    已移除冗余字段（数据存储在数据库 DimensionReport 表）：
    - reports: 完整报告内容（已移除，使用 ReportStore）
    - report_versions: 版本追踪（已移除，使用 ReportStore）
    - summaries: 摘要（已移除，使用 ReportStore）
    """
    messages: Annotated[List[BaseMessage], add_messages]
    session_id: str
    project_name: str
    phase: str
    current_wave: int
    completed_dimensions: Annotated[Dict[str, List[str]], _merge_dict_of_lists]
    config: Dict[str, Any]
    feedback: Optional[str]
    dimension_key: Optional[str]
    image_ids: List[str]
    metadata: Dict[str, Any]
    execution_paused: bool
    pause_after_step: bool
    previous_layer: int


# ==========================================
# 阶段枚举
# ==========================================

class PlanningPhase(Enum):
    """规划阶段"""
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
    PlanningPhase.COMPLETED.value
]

LAYER_NAMES: Dict[str, str] = {
    "layer1": "现状分析", "layer2": "规划思路", "layer3": "详细规划",
}

LAYER_NAMES_BY_NUMBER: Dict[int, str] = {
    1: "现状分析", 2: "规划思路", 3: "详细规划",
}

PHASE_DESCRIPTIONS: Dict[str, str] = {
    PlanningPhase.INIT.value: "初始化阶段",
    PlanningPhase.LAYER1.value: "现状分析阶段",
    PlanningPhase.LAYER2.value: "规划思路阶段",
    PlanningPhase.LAYER3.value: "详细规划阶段",
    PlanningPhase.COMPLETED.value: "规划完成",
}


# ==========================================
# 辅助函数
# ==========================================

def get_layer_name(layer: int) -> str:
    return LAYER_NAMES_BY_NUMBER.get(layer, f"Layer {layer}")


def create_initial_state(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    image_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """创建初始状态"""
    return {
        "session_id": session_id,
        "project_name": project_name,
        "messages": [],
        "phase": PlanningPhase.INIT.value,
        "current_wave": 1,
        "config": {
            "village_data": village_data,
            "village_name": project_name,
            "task_description": task_description,
            "constraints": constraints,
            "knowledge_cache": {},
        },
        "image_ids": image_ids or [],
        "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
        "feedback": None,
        "step_mode": False,
        "execution_paused": False,
        "pause_after_step": False,
        "previous_layer": 0,
        "metadata": {},
    }


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
    if phase == PlanningPhase.COMPLETED.value:
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


def state_to_ui_status(state: Dict[str, Any], db_session: Optional[Dict] = None) -> Dict[str, Any]:
    """状态转 UI 格式

    注意：reports 字段已移除，前端应从数据库 API 获取报告内容
    """
    phase = state.get("phase", "init")
    current_layer = _phase_to_layer(phase)
    if current_layer is None:
        current_layer = 3 if phase == "completed" else 0

    metadata = state.get("metadata", {})
    progress = metadata.get("progress", (current_layer / 3) * 100 if current_layer else 0)

    # Convert messages to UI format
    messages_raw = state.get("messages", [])
    messages_ui = []
    for msg in messages_raw:
        if hasattr(msg, "content") and hasattr(msg, "type"):
            messages_ui.append({
                "type": msg.type,
                "content": msg.content,
                "role": getattr(msg, "role", msg.type),
            })
        elif isinstance(msg, dict):
            messages_ui.append({
                "type": msg.get("type", "unknown"),
                "content": msg.get("content", ""),
                "role": msg.get("role", msg.get("type", "unknown")),
            })

    return {
        "phase": phase,
        "current_wave": state.get("current_wave", 1),
        "current_layer": current_layer,
        "progress": progress,
        "completed_dimensions": state.get("completed_dimensions", {}),
        "pause_after_step": state.get("pause_after_step", False),
        "step_mode": state.get("step_mode", False),
        "execution_paused": state.get("execution_paused", False),
        "previous_layer": state.get("previous_layer", 0),
        "messages": messages_ui,
    }


__all__ = [
    "AgentState", "ReportVersion", "DimensionSummary",
    "PlanningPhase",
    "create_initial_state",
    "_phase_to_layer", "_layer_to_phase",
    "get_layer_dimensions", "get_wave_dimensions", "get_total_waves",
    "get_next_phase", "get_layer_name",
    "LAYER_DIMENSIONS", "WAVE_DIMENSIONS", "TOTAL_WAVES",
    "LAYER_NAMES", "LAYER_NAMES_BY_NUMBER", "PHASE_DESCRIPTIONS",
    "state_to_ui_status",
]