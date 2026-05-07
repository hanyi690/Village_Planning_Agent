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


# ==========================================
# 摘要类型定义 - 仅用于记忆和检索，不参与维度分析
# ==========================================

class DimensionSummary(TypedDict):
    """维度摘要 - 仅用于记忆存储、检索索引和UI预览

    注意：此摘要不替代完整报告。维度依赖分析仍使用 State.reports 的完整内容。
    """
    dimension_key: str          # 维度标识
    dimension_name: str         # 维度名称
    layer: int                  # 所属层级 (1-3)
    summary: str                # 执行摘要（200字以内）
    key_points: List[str]       # 关键要点（5-10条）
    metrics: Dict[str, Any]     # 数据指标（量化数据，如面积、覆盖率等）
    tags: List[str]             # 检索标签（便于关键词匹配）
    created_at: str             # 创建时间（ISO格式）


def merge_dicts(left: Dict[str, Any], right: Dict[str, Any]) -> Dict[str, Any]:
    """Merge two dicts for LangGraph concurrent updates.

    Used with Annotated to allow multiple dimension nodes to update
    gis_analysis_results and planning_layers simultaneously.
    """
    return {**left, **right}


def clearable_add(left: List[Dict], right: List[Dict]) -> List[Dict]:
    """
    可清空的累加 reducer，专为 SSE 事件设计。

    规则：
    - right 非空时：累加到 left（新事件入队）
    - right 为空时：清空 left（发送完成信号）

    这解决了 operator.add 无法清空已累加事件的问题。
    当 emit_sse_events 发送完事件后返回空列表，此 reducer
    会清空累积的旧事件，避免 Layer 2 执行时重发 Layer 1 的事件。
    """
    if not right:
        return []
    return left + right

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
    village_name: str
    task_description: str
    constraints: str
    knowledge_cache: Dict[str, str]
    # images 移至 UnifiedPlanningState 顶层，只在 Layer 1 使用


class UnifiedPlanningState(TypedDict):
    """
    统一规划状态 - Router Agent 架构核心

    特性：
    1. 单一 State 消灭双写问题
    2. Checkpoint 完整记录聊天+规划
    3. Send API 实现维度并行分发

    字段用途区分：
    - reports: 维度依赖传递、完整分析（原始生成）
    - dimension_summaries: 记忆存储、检索索引、UI预览（Flash模型压缩）
    """
    # 核心驱动
    messages: Annotated[List[BaseMessage], add_messages]

    # 业务参数
    session_id: str
    project_name: str
    config: PlanningConfig

    # 图片数据（多模态分析）- 仅 Layer 1 使用
    images: List[Dict[str, Any]]

    # 执行进度
    phase: str
    current_wave: int
    reports: Dict[str, Dict[str, str]]
    completed_dimensions: Dict[str, List[str]]

    # 维度摘要索引（仅用于记忆和检索，不参与分析）
    dimension_summaries: Dict[str, DimensionSummary]

    # Send API 自动合并
    dimension_results: Annotated[List[Dict], operator.add]
    sse_events: Annotated[List[Dict], clearable_add]

    # 交互控制
    pending_review: bool
    need_revision: bool
    revision_target_dimensions: List[str]
    human_feedback: str  # 人工反馈（用户 reject 时提供）


    # Step Mode 控制
    step_mode: bool              # 是否启用分步执行（层级完成后暂停）
    pause_after_step: bool       # 层级完成后暂停标志
    previous_layer: int          # 刚完成的层级编号（用于审查面板）

    # GIS analysis results (vectorization and spatial analysis)
    # Use Annotated with merge_dicts to support concurrent updates from Send API
    gis_analysis_results: Annotated[Dict[str, Any], merge_dicts]  # {dimension_key: result}
    planning_layers: Annotated[Dict[str, Any], merge_dicts]       # {layer_name: GeoJSON}

    # 元数据
    metadata: Dict[str, Any]


def create_initial_state(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    images: Optional[List[Dict[str, Any]]] = None,
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
            village_name=project_name,
            task_description=task_description,
            constraints=constraints,
            knowledge_cache={},
        ),
        images=images or [],  # 图片作为顶层属性，仅 Layer 1 使用
        completed_dimensions={"layer1": [], "layer2": [], "layer3": []},
        dimension_summaries={},  # 维度摘要索引（层级完成后生成）
        dimension_results=[],
        sse_events=[],
        pending_review=False,
        need_revision=False,
        revision_target_dimensions=[],
        human_feedback="",

        step_mode=False,
        pause_after_step=False,
        previous_layer=0,
        gis_analysis_results={},
        planning_layers={},
        metadata={}
    )


def _phase_to_layer(phase: str) -> Optional[int]:
    """phase 转 layer 编号

    支持简化版和详细版两种 phase 格式：
    - 简化版：init, layer1, layer2, layer3, completed
    - 详细版：layer1_analyzing, layer1_completed, layer2_concepting, etc.

    Args:
        phase: 阶段字符串

    Returns:
        0: 对于 init
        1-3: 对于 layer1/2/3 相关阶段
        None: 对于 completed 或未知阶段
    """
    # 简化版映射
    simple_map = {
        PlanningPhase.INIT.value: 0,
        PlanningPhase.LAYER1.value: 1,
        PlanningPhase.LAYER2.value: 2,
        PlanningPhase.LAYER3.value: 3,
    }

    # 直接匹配简化版
    if phase in simple_map:
        return simple_map[phase]

    # 详细版解析：layer1_analyzing -> 1, layer2_completed -> 2, etc.
    if phase.startswith("layer") and "_" in phase:
        try:
            layer_num = int(phase.split("_")[0].replace("layer", ""))
            if layer_num in [1, 2, 3]:
                return layer_num
        except (ValueError, IndexError):
            pass

    # completed 返回 None（无对应执行层级）
    if phase == PlanningPhase.COMPLETED.value:
        return None

    return None


def _layer_to_phase(layer: int) -> str:
    """layer 编号转 phase

    Args:
        layer: 层级编号 (1-3)

    Returns:
        对应的阶段字符串
    """
    layer_to_phase_map = {
        1: PlanningPhase.LAYER1.value,
        2: PlanningPhase.LAYER2.value,
        3: PlanningPhase.LAYER3.value,
    }
    return layer_to_phase_map.get(layer, PlanningPhase.INIT.value)


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


def state_to_ui_status(state: Dict[str, Any], db_session: Optional[Dict] = None) -> Dict[str, Any]:
    """将 UnifiedPlanningState 转换为前端 UI 状态格式

    Agent 自治：状态自己知道如何呈现给 UI，而非 API 层手动拼接。

    Args:
        state: LangGraph checkpoint state values
        db_session: Optional database session metadata

    Returns:
        UI-ready status dictionary
    """
    phase = state.get("phase", "init")
    reports = state.get("reports", {})

    # 使用 _phase_to_layer 函数计算 current_layer（支持详细版 phase）
    current_layer = _phase_to_layer(phase)
    if current_layer is None:
        # completed 或未知阶段：如果 reports 有数据，显示 3
        if phase == PlanningPhase.COMPLETED.value or phase == "completed":
            current_layer = 3
        else:
            current_layer = 0

    # 从 metadata 获取进度（优先使用预先计算的值）
    metadata = state.get("metadata", {})
    progress = metadata.get("progress")
    if progress is None:
        # 降级计算：复用已计算的 current_layer
        if phase == PlanningPhase.COMPLETED.value or phase == "completed":
            progress = 100
        elif current_layer and current_layer > 0:
            progress = (current_layer / 3) * 100
        else:
            progress = 0

    # 计算 execution_complete
    execution_complete = (
        len(reports.get("layer1", {})) > 0 and
        len(reports.get("layer2", {})) > 0 and
        len(reports.get("layer3", {})) > 0
    )

    return {
        # 核心状态
        "phase": phase,
        "current_wave": state.get("current_wave", 1),
        "reports": reports,
        "pause_after_step": state.get("pause_after_step", False),
        "previous_layer": state.get("previous_layer", 0),
        "step_mode": state.get("step_mode", False),

        # 计算字段
        "current_layer": current_layer,
        "progress": progress,
        "execution_complete": execution_complete,

        # 完成维度
        "completed_dimensions": state.get("completed_dimensions", {}),

        # 元数据
        "version": metadata.get("version", 0),
        "status": db_session.get("status", "running") if db_session else "running",
        "execution_error": db_session.get("execution_error") if db_session else None,
        "created_at": db_session.get("created_at", "") if db_session else "",
    }


__all__ = [
    "PlanningPhase",
    "PlanningConfig",
    "UnifiedPlanningState",
    "DimensionSummary",
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
    "state_to_ui_status",
    "merge_dicts",
    "clearable_add",
]