"""Run-time state: AgentState TypedDict, reducers, create_initial_state, state_to_ui_status.

Migrated from agent/state.py per docs/architecture/agent-graph.md §5.
"""

import math
import operator
from typing import TypedDict, List, Dict, Any, Optional, Annotated
from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages

from app.agent.bootstrap.phase_machine import (
    PlanningPhase,
    get_layer_name,
    _phase_to_layer,
    _layer_to_phase,
)

# Use plain add_messages reducer.
# DeltaChannel is NOT supported with SqliteSaver (requires per-channel blob table,
# only InMemorySaver / PostgresSaver support delta chains).
# See: langgraph PR #7547
_messages_reducer = add_messages


DEFAULT_RAG_LAYER_CONFIG = {1: True, 2: False, 3: True}


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
        combined = a.get(k, []) + b.get(k, [])
        result[k] = list(dict.fromkeys(combined))  # O(n) dedup, preserves order
    return result


def _merge_revision_completed(
    a: Dict[int, List[str]], b: Dict[int, List[str]]
) -> Dict[int, List[str]]:
    """Revision completed dims reducer.

    - b={} (explicit reset) -> return {} (clear all stale entries)
    - Otherwise -> merge and dedupe (normal fan-in accumulation)
    """
    if b == {}:
        return {}

    return _merge_dict_of_lists(a, b)


def _merge_dict_of_dicts(a: Dict[str, Dict], b: Dict[str, Dict]) -> Dict[str, Dict]:
    """递归合并两个 {key: dict} 字典，同 key 时自动合并嵌套 dict。用于并行 fan-in。"""
    result = {**a}
    for k, v in b.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = {**result[k], **v}
        else:
            result[k] = v
    return result


def _merge_config(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    """Deep-merge config dicts. PATCH updates (b) take precedence over frozen state (a).
    Prevents Send-frozen snapshots from overwriting runtime PATCH updates."""
    if not b:
        return a
    result = {**a}
    for k, v in b.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = {**result[k], **v}
        else:
            result[k] = v
    return result


def _merge_lists(a: List, b: List) -> List:
    """合并两个列表。用于并行 fan-in。"""
    return a + b


def _replace_or_merge_lists(a: List, b: List) -> List:
    """List reducer for pending_reports.

    - b=[] (explicit reset) -> return [] (clear buffer after batch write)
    - Otherwise -> merge (normal fan-in accumulation)
    """
    if b == []:
        return []
    return a + b


def _merge_layer_char_counts(a: Dict[int, int], b: Dict[int, int]) -> Dict[int, int]:
    """合并两个 layer 字符数字典，同 layer 时累加。用于并行 fan-in。"""
    result = dict(a)
    for layer, count in b.items():
        result[layer] = result.get(layer, 0) + count
    return result


def _merge_is_revision(a: bool, b: bool) -> bool:
    """Merge is_revision using logical OR. If any node sets True, keep True.
    Ensures revision flag survives parallel fan-in reducer merge."""
    return a or b


def _preserve_impact_tree(a: Optional[Dict[int, List[str]]], b: Optional[Dict[int, List[str]]]) -> Optional[Dict[int, List[str]]]:
    """fan-in 时保留有值的一方，防止被 None 覆盖。"""
    if b is not None:
        return b
    return a


def _merge_explore_outputs(
    a: Dict[str, Any], b: Dict[str, Any]
) -> Dict[str, Any]:
    """EXPLORE 产出的 state 字段合并（保留有值方，防 Send fan-in 覆盖）。"""
    if not b:
        return a
    result = {**a}
    for k, v in b.items():
        if v is not None and v != [] and v != {}:
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
    messages: Annotated[List[BaseMessage], _messages_reducer]
    session_id: str
    project_name: str
    phase: str
    current_wave: int
    completed_dimensions: Annotated[Dict[str, List[str]], _merge_dict_of_lists]
    config: Annotated[Dict[str, Any], _merge_config]
    feedback: Optional[str]
    dimension_key: Optional[str]
    image_ids: List[str]
    metadata: Dict[str, Any]
    step_mode: bool  # Enable step-by-step execution (pause after each layer)
    previous_layer: int
    # Revision cascade
    need_revision: bool
    revision_target_dimensions: List[str]
    human_feedback: str
    is_revision: Annotated[bool, _merge_is_revision]
    revision_impact_tree: Annotated[Optional[Dict[int, List[str]]], _preserve_impact_tree]
    revision_completed_dims: Annotated[Dict[int, List[str]], _merge_revision_completed]
    revision_feedback: Optional[str]
    last_revised_dimensions: List[str]
    # Performance optimization: batch write and char count cache
    pending_reports: Annotated[List[Dict[str, Any]], _replace_or_merge_lists]  # Buffer for batch DB writes
    layer_char_counts: Annotated[Dict[int, int], _merge_layer_char_counts]  # Cached char counts per layer
    gis_layout_configs: Annotated[List[Dict[str, Any]], _replace_or_merge_lists]  # DEPRECATED Wave M1: use delivery_manifest
    gis_export_result: Dict[str, Any]  # DEPRECATED Wave M1: use delivery_manifest
    gis_render_result: List[Dict[str, Any]]  # DEPRECATED Wave M1: use delivery_manifest
    gis_render_artifact: Dict[str, Any]  # DEPRECATED Wave M1: use delivery_manifest
    gis_validation_result: Dict[str, Any]  # DEPRECATED Wave M1: use validation_report_ref
    gis_execution_errors: List[Dict[str, Any]]  # DEPRECATED Wave M1: use delivery_manifest
    gis_conflict_result: Dict[str, Any]  # DEPRECATED Wave M1: use delivery_manifest
    user_uploaded_data: Annotated[Dict[str, Dict[str, Any]], _merge_dict_of_dicts]  # 用户上传的GIS数据
    # P0: L1/L2/L3 数据流闭环字段（详见 docs/superpowers/specs/2026-07-02-gis-review-exploration.md）
    _landuse_metrics: Annotated[Dict[str, float], _merge_dict_of_dicts]  # L1 注入的现状用地指标
    intent_targets: Annotated[Dict[str, float], _merge_dict_of_dicts]  # L2 持久化的规划目标面积
    # P2: EXPLORE 桥接产出（L3 完成后注入，供 gis_agent 消费）
    explore_instructions: Annotated[Dict[str, Any], _merge_explore_outputs]  # ExplorationInstructionCollection
    report_summary_index: Annotated[Dict[str, Any], _merge_explore_outputs]  # ReportSummaryIndex
    explore_done: Annotated[bool, operator.or_]  # EXPLORE 桥接已执行标记（防重复触发）
    # ── Wave M1: post-L3 链 typed artifact 引用（conservative：新增，不删除遗留 gis_* 字段）──
    delivery_manifest: Optional[Any]  # DeliveryManifest — DELIVER 输出（typed）
    reconciliation_report_ref: Optional[Any]  # ReconciliationReport — RECONCILE 输出（typed）
    validation_report_ref: Optional[Any]  # ValidationReport — VALIDATE 输出（typed）
    pending_requests: Annotated[List[Dict[str, Any]], _replace_or_merge_lists]  # 全链 Gate pending requests 累积
    context_version: str  # PlanningContext 版本戳
    # ── Wave M2: layer aggregate wiring ──
    layer_just_completed: Optional[int]  # set by completion_check, consumed by layer_aggregate_node
    # ── Wave N P5: post-L3 HITL pending/resume fields ──
    post_l3_pending_review: Annotated[List[Dict[str, Any]], _replace_or_merge_lists]  # HUMAN 暂停时的待审 items
    post_l3_thread_id: str  # post-L3 chain 的 LangGraph thread_id（= session_id）
    post_l3_status: str  # "needs_human_review" 等
    post_l3_decisions: Optional[Any]  # resume 后回写的审查决策


# ==========================================
# 辅助函数
# ==========================================

def create_initial_state(
    session_id: str,
    project_name: str,
    village_data: str,
    task_description: str = "制定村庄总体规划方案",
    constraints: str = "无特殊约束",
    image_ids: Optional[List[str]] = None,
    village_name: str = "",
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
            "village_name": village_name or project_name,
            "task_description": task_description,
            "constraints": constraints,
            "knowledge_cache": {},
        },
        "image_ids": image_ids or [],
        "completed_dimensions": {"layer1": [], "layer2": [], "layer3": []},
        "feedback": None,
        "step_mode": False,
        "previous_layer": 0,
        "metadata": {},
        "need_revision": False,
        "revision_target_dimensions": [],
        "human_feedback": "",
        "is_revision": False,
        "revision_impact_tree": None,
        "revision_completed_dims": {},
        "revision_feedback": None,
        "last_revised_dimensions": [],
        "pending_reports": [],  # Buffer for batch DB writes
        "layer_char_counts": {},  # Cached char counts per layer
        "gis_layout_configs": [],  # GIS Agent输出的图层配置
        "gis_export_result": {},
        "gis_render_result": [],
        "gis_render_artifact": {},
        "gis_validation_result": {},
        "gis_execution_errors": [],
        "gis_conflict_result": {},
        "user_uploaded_data": {},  # 用户上传的GIS数据
        "_landuse_metrics": {},  # P0: L1 注入的现状用地指标
        "intent_targets": {},  # P0: L2 持久化的规划目标面积
        "explore_instructions": {},  # P2: EXPLORE 桥接产出
        "report_summary_index": {},  # P2: EXPLORE 概要索引
        # ── Wave M1: post-L3 链 typed artifact 引用 ──
        "delivery_manifest": None,
        "reconciliation_report_ref": None,
        "validation_report_ref": None,
        "pending_requests": [],
        "context_version": "",
        "layer_just_completed": None,
        # ── Wave N P5: post-L3 HITL ──
        "post_l3_pending_review": [],
        "post_l3_thread_id": "",
        "post_l3_status": "",
        "post_l3_decisions": None,
    }


def _sanitize_json(obj):
    """Recursively replace inf/nan floats with None for JSON serialization."""
    if isinstance(obj, float):
        if math.isinf(obj) or math.isnan(obj):
            return None
        return obj
    if isinstance(obj, dict):
        return {k: _sanitize_json(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize_json(v) for v in obj]
    return obj


def state_to_ui_status(state: Dict[str, Any], db_session: Optional[Dict] = None, *, is_interrupted: bool = False) -> Dict[str, Any]:
    """状态转 UI 格式

    注意：reports 字段已移除，前端应从数据库 API 获取报告内容
    """
    phase = state.get("phase", "init")
    current_layer = _phase_to_layer(phase)
    if current_layer is None:
        current_layer = 3 if phase == "completed" else 0

    metadata = state.get("metadata", {})
    progress = metadata.get("progress", (current_layer / 3) * 100 if current_layer else 0)

    # Determine status based on phase and interrupt state
    if phase == "completed":
        status = "completed"
    elif is_interrupted:
        status = "paused"
    elif phase == "init":
        status = "pending"
    else:
        status = "running"

    # Build interrupt_info from interrupt state
    interrupt_info = None
    if is_interrupted:
        interrupt_info = {
            "layer": current_layer or 0,
            "phase": phase,
            "layer_name": get_layer_name(current_layer or 0) if (current_layer or 0) > 0 else None,
            "reason": "step_mode" if state.get("step_mode", False) else "pause",
        }

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

    result = {
        # Core status fields
        "session_id": db_session.get("session_id") if db_session else state.get("session_id", ""),
        "status": status,
        "created_at": db_session.get("created_at") if db_session else metadata.get("created_at", ""),
        "execution_error": metadata.get("execution_error"),
        "execution_complete": phase == "completed",
        "last_checkpoint_id": metadata.get("last_checkpoint_id", ""),
        # Agent State (Single Source of Truth)
        "phase": phase,
        "current_wave": state.get("current_wave", 1),
        "current_layer": current_layer,
        "progress": progress,
        "completed_dimensions": state.get("completed_dimensions", {}),
        "interrupt_info": interrupt_info,
        "step_mode": state.get("step_mode", False),
        "rag_enabled": state.get("config", {}).get("rag_enabled", True),
        "rag_layer_config": state.get("config", {}).get("rag_layer_config", DEFAULT_RAG_LAYER_CONFIG),
        "previous_layer": state.get("previous_layer", 0),
        "messages": messages_ui,
        # 项目上下文（优先使用 db_session 数据，因为是持久化的）
        "project_name": db_session.get("project_name") if db_session else state.get("project_name", ""),
        "village_name": db_session.get("village_name") if db_session else state.get("config", {}).get("village_name", ""),
        "province": db_session.get("province") if db_session else state.get("config", {}).get("province", ""),
        "city": db_session.get("city") if db_session else state.get("config", {}).get("city", ""),
        "county": db_session.get("county") if db_session else state.get("config", {}).get("county", ""),
        "township": db_session.get("township") if db_session else state.get("config", {}).get("township", ""),
        "planning_period": db_session.get("planning_period") if db_session else state.get("config", {}).get("planning_period", "2022-2035年"),
        "gis_layout_configs": state.get("gis_layout_configs", []),
    }

    return _sanitize_json(result)


__all__ = [
    "AgentState", "ReportVersion", "DimensionSummary",
    "create_initial_state",
    "state_to_ui_status",
    "_merge_lists", "_merge_layer_char_counts",  # Performance optimization reducers
]
