"""
编排层 - Router Agent 架构

单一 State，消灭双写问题。
"""

from .state import (
    PlanningPhase,
    PlanningConfig,
    UnifiedPlanningState,
    create_initial_state,
    get_layer_dimensions,
    get_wave_dimensions,
    get_total_waves,
    get_next_phase,
    _phase_to_layer,
    _layer_to_phase,
)
from .main_graph import (
    create_unified_planning_graph,
    run_unified_planning,
    run_unified_planning_async,
    resume_from_checkpoint,
)
from .routing import (
    intent_router,
    route_by_phase,
    collect_layer_results,
    emit_sse_events,
    check_phase_completion,
)

__all__ = [
    # 状态
    "PlanningPhase",
    "PlanningConfig",
    "UnifiedPlanningState",
    "create_initial_state",
    "get_layer_dimensions",
    "get_wave_dimensions",
    "get_total_waves",
    "get_next_phase",
    "_phase_to_layer",
    "_layer_to_phase",
    # 主图
    "create_unified_planning_graph",
    "run_unified_planning",
    "run_unified_planning_async",
    "resume_from_checkpoint",
    # 路由
    "intent_router",
    "route_by_phase",
    "collect_layer_results",
    "emit_sse_events",
    "check_phase_completion",
]