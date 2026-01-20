"""
详细规划子图 (Detailed Planning Subgraph)

基于现状分析和规划思路，生成详细的村庄规划方案，包含10个专业规划维度：
1. 产业规划 (Industry Planning)
2. 村庄总体规划 (Master Planning)
3. 道路交通规划 (Traffic Planning)
4. 公共服务设施规划 (Public Service Planning)
5. 基础设施规划 (Infrastructure Planning)
6. 生态绿地规划 (Ecological Planning)
7. 防震减灾规划 (Disaster Prevention Planning)
8. 历史文保规划 (Heritage Planning)
9. 村庄风貌指引 (Landscape Planning)
10. 建设项目库 (Project Bank)

使用 LangGraph 的 Send 机制实现 Map-Reduce 模式。
支持人机交互反馈循环。
支持部分状态传递优化，根据维度依赖关系筛选相关信息。
"""

from typing import TypedDict, List, Dict, Any, Literal
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, interrupt
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
import operator
from datetime import datetime

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..utils.logger import get_logger
from ..utils.state_filter import filter_state_for_detailed_dimension
from .detailed_plan_prompts import (
    INDUSTRY_PLANNING_PROMPT,
    MASTER_PLAN_PROMPT,
    TRAFFIC_PLANNING_PROMPT,
    PUBLIC_SERVICE_PROMPT,
    INFRASTRUCTURE_PROMPT,
    ECOLOGICAL_PROMPT,
    DISASTER_PREVENTION_PROMPT,
    HERITAGE_PROMPT,
    LANDSCAPE_PROMPT,
    PROJECT_BANK_PROMPT,
    DETAILED_PLAN_SUMMARY_PROMPT,
    list_detailed_dimensions,
    get_dimension_prompt
)

logger = get_logger(__name__)


# ==========================================
# 子图状态定义
# ==========================================

class DetailedPlanState(TypedDict):
    """详细规划子图的状态"""
    # 输入数据
    project_name: str
    analysis_report: str           # 来自 Layer 1（完整版，降级使用）
    dimension_reports: Dict[str, str]  # 各维度现状分析报告字典（用于部分状态传递）
    planning_concept: str          # 来自 Layer 2（完整版，降级使用）
    concept_dimension_reports: Dict[str, str]  # 各维度规划思路报告字典（用于部分状态传递）
    task_description: str
    constraints: str

    # 规划维度控制
    required_dimensions: List[str] # 需要生成的维度列表
    completed_dimensions: List[str] # 已完成的维度
    current_dimension: str         # 当前处理的维度

    # 各维度规划结果（支持独立更新）
    industry_plan: str             # 产业规划
    master_plan: str               # 总体规划
    traffic_plan: str              # 道路交通规划
    public_service_plan: str       # 公服设施规划
    infrastructure_plan: str       # 基础设施规划
    ecological_plan: str           # 生态绿地规划
    disaster_prevention_plan: str  # 防震减灾规划
    heritage_plan: str             # 历史文保规划
    landscape_plan: str            # 村庄风貌指引
    project_bank: str              # 建设项目库

    # 人机交互状态
    need_review: bool              # 是否需要人工审核
    human_feedback: Dict[str, str] # 各维度的反馈意见
    revision_count: Dict[str, int] # 各维度修改次数

    # 中间结果（用于并行处理）
    dimension_plans: Annotated[List[Dict[str, str]], operator.add]  # 已完成的维度规划

    # 最终输出
    final_detailed_plan: str       # 汇总的详细规划报告
    consolidated_project_bank: str # 整合后的项目库

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


class DetailedDimensionState(TypedDict):
    """单个维度规划的状态（用于并行节点）"""
    dimension_key: str             # 维度标识
    dimension_name: str            # 维度名称
    project_name: str
    analysis_report: str
    planning_concept: str
    task_description: str
    constraints: str
    human_feedback: str            # 针对该维度的反馈意见
    dimension_result: str          # 规划结果


# ==========================================
# 常量定义
# ==========================================

# 所有维度列表
ALL_DIMENSIONS = [
    "industry",
    "master_plan",
    "traffic",
    "public_service",
    "infrastructure",
    "ecological",
    "disaster_prevention",
    "heritage",
    "landscape",
    "project_bank"
]

# 维度名称映射
DIMENSION_NAMES = {
    "industry": "产业规划",
    "master_plan": "村庄总体规划",
    "traffic": "道路交通规划",
    "public_service": "公服设施规划",
    "infrastructure": "基础设施规划",
    "ecological": "生态绿地规划",
    "disaster_prevention": "防震减灾规划",
    "heritage": "历史文保规划",
    "landscape": "村庄风貌指引",
    "project_bank": "建设项目库"
}

# 维度依赖关系（某些维度依赖其他维度）
DIMENSION_DEPENDENCIES = {
    "project_bank": ["industry", "traffic", "public_service",
                     "infrastructure", "ecological", "disaster_prevention",
                     "heritage", "landscape"]
}


# ==========================================
# LLM 调用辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例，使用统一的 LLM 工厂"""
    from ..core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# 初始化节点
# ==========================================

def initialize_detailed_planning(state: DetailedPlanState) -> Dict[str, Any]:
    """
    初始化详细规划流程，设置待规划的维度列表
    """
    logger.info(f"[子图-L3-初始化] 开始详细规划，项目: {state.get('project_name', '未命名')}")

    # 如果没有指定维度，默认生成所有维度
    required = state.get("required_dimensions", ALL_DIMENSIONS)

    # 验证维度有效性
    valid_dimensions = [d for d in required if d in ALL_DIMENSIONS]

    logger.info(f"[子图-L3-初始化] 设置 {len(valid_dimensions)} 个规划维度")

    return {
        "required_dimensions": valid_dimensions,
        "completed_dimensions": [],
        "dimension_plans": [],
        "human_feedback": state.get("human_feedback", {}),
        "revision_count": state.get("revision_count", {})
    }


# ==========================================
# 路由节点 - 分发到各专业Agent
# ==========================================

def route_to_planning_agents(state: DetailedPlanState):
    """
    路由到专业规划Agent（用于条件边）

    逻辑：
    1. 检查 required_dimensions
    2. 过滤已完成的维度
    3. 处理依赖关系（如项目库在最后）
    4. 返回 Send 对象列表或节点名称

    Returns:
        List[Send]: Send 对象列表（多个维度时）
        str: 节点名称（"generate_single" 或 "generate_final"）
    """
    required = state.get("required_dimensions", ALL_DIMENSIONS)
    completed = state.get("completed_dimensions", [])

    # 过滤已完成的维度
    pending = [d for d in required if d not in completed]

    if not pending:
        logger.info("[子图-L3-路由] 所有维度已完成")
        return "generate_final"

    # 处理依赖关系：项目库需要在其他维度之后生成
    if "project_bank" in pending:
        # 检查依赖是否满足
        dependencies = DIMENSION_DEPENDENCIES["project_bank"]
        completed_dependencies = [d for d in dependencies if d in completed]

        if len(completed_dependencies) < len(dependencies):
            # 依赖未满足，暂时跳过项目库
            pending.remove("project_bank")
            logger.info("[子图-L3-路由] 项目库等待其他维度完成")

            if not pending:
                # 只有项目库待生成，但依赖未满足，强制生成
                logger.info("[子图-L3-路由] 只有项目库待生成，强制生成")
                pending = ["project_bank"]
        else:
            # 依赖满足，确保项目库在最后
            pending.remove("project_bank")
            pending.append("project_bank")

    # 如果只剩一个维度，直接返回节点名称
    if len(pending) == 1:
        logger.info(f"[子图-L3-路由] 仅剩 1 个维度 {pending[0]}，直接生成")
        return "generate_single"

    # 多个维度，创建 Send 对象
    logger.info(f"[子图-L3-路由] 分发 {len(pending)} 个待规划维度")

    # 获取完整的维度报告字典
    full_dimension_reports = state.get("dimension_reports", {})
    full_concept_dimension_reports = state.get("concept_dimension_reports", {})

    sends = []
    for dim in pending:
        dimension_info = {d["key"]: d for d in list_detailed_dimensions()}.get(dim, {"name": dim})

        # 【关键优化】筛选相关的现状分析和规划思路
        filtered_state = filter_state_for_detailed_dimension(
            detailed_dimension=dim,
            full_analysis_reports=full_dimension_reports,
            full_analysis_report=state["analysis_report"],
            full_concept_reports=full_concept_dimension_reports,
            full_concept_report=state["planning_concept"]
        )

        dimension_state = DetailedDimensionState({
            "dimension_key": dim,
            "dimension_name": dimension_info.get("name", dim),
            "project_name": state["project_name"],
            "analysis_report": filtered_state["filtered_analysis"],  # 使用筛选后的报告
            "planning_concept": filtered_state["filtered_concept"],   # 使用筛选后的报告
            "task_description": state.get("task_description", "制定详细规划"),
            "constraints": state.get("constraints", ""),
            "human_feedback": state.get("human_feedback", {}).get(dim, ""),
            "dimension_result": ""
        })

        sends.append(Send("generate_dimension_plan", dimension_state))

    logger.info(f"[子图-L3-路由] 创建了 {len(sends)} 个并行任务（已优化状态传递）")
    return sends


# ==========================================
# 单维度生成节点 - 处理最后一个维度
# ==========================================

def generate_single_dimension(state: DetailedPlanState) -> Dict[str, Any]:
    """
    生成单个维度的规划（用于最后一个待规划维度）

    当只剩一个维度时，不使用 Send 机制，直接在此节点生成规划，
    避免 LangGraph 状态错误。
    """
    required = state.get("required_dimensions", ALL_DIMENSIONS)
    completed = state.get("completed_dimensions", [])
    pending = [d for d in required if d not in completed]

    if not pending:
        logger.warning("[子图-L3-单维度] 没有找到待生成的维度")
        return {}

    # 处理依赖关系：项目库需要在其他维度之后生成
    dimension_key = pending[0]
    if dimension_key == "project_bank":
        dependencies = DIMENSION_DEPENDENCIES["project_bank"]
        completed_dependencies = [d for d in dependencies if d in completed]
        if len(completed_dependencies) < len(dependencies):
            logger.info("[子图-L3-单维度] 生成项目库（依赖自动满足）")

    # 获取维度信息
    dimension_info = {d["key"]: d for d in list_detailed_dimensions()}.get(dimension_key, {"name": dimension_key})
    dimension_name = dimension_info.get("name", dimension_key)

    logger.info(f"[子图-L3-单维度] 生成最后一个维度: {dimension_name} ({dimension_key})")

    # 获取完整的维度报告字典
    full_dimension_reports = state.get("dimension_reports", {})
    full_concept_dimension_reports = state.get("concept_dimension_reports", {})

    # 【关键优化】筛选相关的现状分析和规划思路
    filtered_state = filter_state_for_detailed_dimension(
        detailed_dimension=dimension_key,
        full_analysis_reports=full_dimension_reports,
        full_analysis_report=state["analysis_report"],
        full_concept_reports=full_concept_dimension_reports,
        full_concept_report=state["planning_concept"]
    )

    # 构建维度状态
    dimension_state = DetailedDimensionState({
        "dimension_key": dimension_key,
        "dimension_name": dimension_name,
        "project_name": state["project_name"],
        "analysis_report": filtered_state["filtered_analysis"],  # 使用筛选后的报告
        "planning_concept": filtered_state["filtered_concept"],   # 使用筛选后的报告
        "task_description": state.get("task_description", "制定详细规划"),
        "constraints": state.get("constraints", ""),
        "human_feedback": state.get("human_feedback", {}).get(dimension_key, ""),
        "dimension_result": ""
    })

    # 调用现有的生成逻辑
    result = generate_dimension_plan(dimension_state)

    logger.info(f"[子图-L3-单维度] 完成 {dimension_name}，生成 {len(result['dimension_plans'][0]['dimension_result'])} 字符")

    return result


# ==========================================
# 专业Agent节点 - 生成各维度规划
# ==========================================

def generate_dimension_plan(state: DetailedDimensionState) -> Dict[str, Any]:
    """
    生成单个维度的详细规划

    通用的专业Agent节点，根据维度调用对应的Prompt。
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]
    project_name = state["project_name"]

    logger.info(f"[子图-L3-Agent] 开始生成 {dimension_name} ({dimension_key})")

    try:
        # 获取专业提示词
        prompt_template = get_dimension_prompt(dimension_key)

        if not prompt_template:
            raise ValueError(f"未找到维度 {dimension_key} 的提示词")

        # 对于项目库，需要传入其他维度的规划摘要
        if dimension_key == "project_bank":
            # 这里需要在主状态中获取其他维度的结果
            # 暂时用占位符
            dimension_plans_summary = "（其他维度规划将在执行时整合）"
        else:
            dimension_plans_summary = ""

        # 构建完整提示词
        prompt = prompt_template.format(
            project_name=project_name,
            analysis_report=state["analysis_report"][:4000],  # 限制长度避免token超限
            planning_concept=state["planning_concept"][:3000],
            task_description=state["task_description"],
            constraints=state["constraints"],
            dimension_plans=dimension_plans_summary
        )

        # 检查是否有反馈意见
        if state.get("human_feedback"):
            prompt += f"""

## 修改意见
根据之前的反馈，请对规划进行以下修改：
{state['human_feedback']}

请基于以上修改意见重新生成/优化该维度的规划。
"""

        # 调用 LLM
        llm = _get_llm()
        response = llm.invoke([HumanMessage(content=prompt)])

        plan_content = response.content
        logger.info(f"[子图-L3-Agent] 完成 {dimension_name}，生成 {len(plan_content)} 字符")

        # 添加元数据
        plan_with_metadata = f"""# {project_name} - {dimension_name}

{plan_content}

---
**编制**: {dimension_name}专业Agent
**编制时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

        # 返回结果（包装在列表中以支持累加）
        return {
            "dimension_plans": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "dimension_result": plan_with_metadata
            }]
        }

    except Exception as e:
        logger.error(f"[子图-L3-Agent] {dimension_name} 生成失败: {str(e)}")

        error_plan = f"""# {project_name} - {dimension_name}

[规划生成失败]

错误信息: {str(e)}

请检查输入数据或稍后重试。

---
**编制时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

        return {
            "dimension_plans": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "dimension_result": error_plan
            }]
        }


# ==========================================
# Reduce 节点 - 汇总维度规划结果
# ==========================================

def reduce_dimension_plans(state: DetailedPlanState) -> Dict[str, Any]:
    """
    汇总所有维度的规划结果，更新主状态
    """
    logger.info(f"[子图-L3-Reduce] 汇总 {len(state['dimension_plans'])} 个维度的规划结果")

    # 更新各维度的规划到对应字段
    updates = {}
    completed = []

    for plan in state["dimension_plans"]:
        dim_key = plan["dimension_key"]
        dim_result = plan["dimension_result"]

        # 更新对应字段
        field_name = f"{dim_key}_plan"
        updates[field_name] = dim_result
        completed.append(dim_key)

    # 更新已完成列表
    updates["completed_dimensions"] = completed

    logger.info(f"[子图-L3-Reduce] 已完成维度: {', '.join(completed)}")

    return updates


# ==========================================
# 条件路由 - 检查是否所有维度完成
# ==========================================

def check_all_dimensions_complete(state: DetailedPlanState) -> Literal["continue", "finalize"]:
    """
    检查是否所有必需的维度都已完成

    Returns:
        "continue": 继续生成剩余维度
        "finalize": 所有维度完成，进入汇总
    """
    required = set(state.get("required_dimensions", ALL_DIMENSIONS))
    completed = set(state.get("completed_dimensions", []))

    # 考虑依赖关系
    pending = required - completed

    # 处理项目库的特殊情况
    if "project_bank" in pending:
        dependencies = set(DIMENSION_DEPENDENCIES["project_bank"])
        if dependencies.issubset(completed):
            # 项目库依赖已满足，可以生成
            pass
        else:
            # 项目库依赖未满足，暂时移除
            pending.remove("project_bank")

    if pending:
        logger.info(f"[子图-L3-检查] 还有 {len(pending)} 个维度待生成")
        return "continue"
    else:
        logger.info("[子图-L3-检查] 所有维度已完成，进入汇总")
        return "finalize"


# ==========================================
# 人工审核节点（可选）
# ==========================================

def human_review_dimension(state: DetailedPlanState) -> Dict[str, Any]:
    """
    人工审核当前维度的规划（简化版本）

    注意：完整的人机交互需要使用 LangGraph 的 interrupt 机制
    当前版本提供简化实现，自动通过所有维度
    """
    logger.info(f"[子图-L3-审核] 等待人工审核（当前版本自动通过）")

    # 当前版本：自动通过所有维度
    # 完整版本可以使用 interrupt() 暂停执行

    return {
        "messages": [AIMessage(content="人工审核完成（自动通过）")]
    }


# ==========================================
# 最终汇总节点
# ==========================================

def generate_final_detailed_plan(state: DetailedPlanState) -> Dict[str, Any]:
    """
    生成最终详细规划报告

    整合所有维度的规划结果，生成连贯的详细规划文档。
    """
    logger.info("[子图-L3-汇总] 开始生成最终详细规划报告")

    try:
        # 整理各维度规划为文本
        dimension_reports_text = ""
        for dim_key in state["completed_dimensions"]:
            field_name = f"{dim_key}_plan"
            plan = state.get(field_name, "")
            dimension_reports_text += f"\n\n{plan}\n\n"

        # 构建汇总 Prompt
        summary_prompt = DETAILED_PLAN_SUMMARY_PROMPT.format(
            project_name=state["project_name"],
            dimension_reports=dimension_reports_text[:10000]  # 限制长度
        )

        # 调用 LLM 生成最终报告
        llm = _get_llm()
        response = llm.invoke([HumanMessage(content=summary_prompt)])

        final_detailed_plan = f"""# {state['project_name']} 详细规划报告

{response.content}

---

## 各专项规划

{dimension_reports_text}

---

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**规划系统**: 村庄规划 AI 系统 - 详细规划层
"""

        logger.info(f"[子图-L3-汇总] 详细规划报告生成完成，共 {len(final_detailed_plan)} 字符")

        return {
            "final_detailed_plan": final_detailed_plan,
            "messages": [AIMessage(content=f"详细规划报告已生成，总长度 {len(final_detailed_plan)} 字符。")]
        }

    except Exception as e:
        logger.error(f"[子图-L3-汇总] 报告生成失败: {str(e)}")

        # 降级方案：直接拼接各维度结果
        fallback_plan = f"""# {state['project_name']} 详细规划报告

## 各专项规划

"""
        for dim_key in state["completed_dimensions"]:
            field_name = f"{dim_key}_plan"
            plan = state.get(field_name, "")
            fallback_plan += f"\n{plan}\n"

        fallback_plan += f"""

---

**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
**说明**: 自动汇总版本
"""

        return {
            "final_detailed_plan": fallback_plan,
            "messages": [AIMessage(content="详细规划报告已生成（简化汇总版本）")]
        }


# ==========================================
# 构建子图
# ==========================================

def create_detailed_plan_subgraph() -> StateGraph:
    """
    创建详细规划子图

    Returns:
        编译后的 StateGraph 实例
    """
    logger.info("[子图构建] 开始构建详细规划子图")

    # 创建状态图
    builder = StateGraph(DetailedPlanState)

    # 添加节点
    builder.add_node("initialize", initialize_detailed_planning)
    builder.add_node("generate_dimension_plan", generate_dimension_plan)
    builder.add_node("generate_single", generate_single_dimension)  # 单维度生成节点
    builder.add_node("reduce_plans", reduce_dimension_plans)
    builder.add_node("check_complete", check_all_dimensions_complete)  # 条件路由函数
    builder.add_node("human_review", human_review_dimension)
    builder.add_node("generate_final", generate_final_detailed_plan)

    # 构建执行流程
    builder.add_edge(START, "initialize")

    # 初始化 -> 路由决策（直接使用路由函数）
    builder.add_conditional_edges(
        "initialize",
        route_to_planning_agents,
        ["generate_dimension_plan", "generate_single", "generate_final"]
    )

    # Agent节点 -> Reduce
    builder.add_edge("generate_dimension_plan", "reduce_plans")

    # 单维度节点 -> Reduce
    builder.add_edge("generate_single", "reduce_plans")

    # Reduce -> 检查是否完成
    builder.add_conditional_edges(
        "reduce_plans",
        check_all_dimensions_complete,
        {
            "continue": "route_next",  # 继续生成剩余维度
            "finalize": "generate_final"  # 所有维度完成
        }
    )

    # 添加路由节点（空节点，仅用于路由）
    def route_next_node(state: DetailedPlanState) -> Dict[str, Any]:
        """路由节点，不修改状态，仅用于触发条件边"""
        return {}

    builder.add_node("route_next", route_next_node)

    # 路由决策（再次使用路由函数）
    builder.add_conditional_edges(
        "route_next",
        route_to_planning_agents,
        ["generate_dimension_plan", "generate_single", "generate_final"]
    )

    # 最终节点 -> END
    builder.add_edge("generate_final", END)

    # 编译子图
    detailed_plan_subgraph = builder.compile()

    logger.info("[子图构建] 详细规划子图构建完成")

    return detailed_plan_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_detailed_plan_subgraph(
    project_name: str,
    analysis_report: str,
    planning_concept: str,
    dimension_reports: Dict[str, str] = None,  # 新增：维度报告字典
    concept_dimension_reports: Dict[str, str] = None,  # 新增：规划思路维度字典
    task_description: str = "制定村庄详细规划",
    constraints: str = "无特殊约束",
    required_dimensions: List[str] = None,
    enable_human_review: bool = False
) -> Dict[str, Any]:
    """
    调用详细规划子图的包装函数

    Args:
        project_name: 项目/村庄名称
        analysis_report: 现状分析报告（来自 Layer 1）
        planning_concept: 规划思路（来自 Layer 2）
        dimension_reports: 各维度现状分析报告字典（用于部分状态传递）
        concept_dimension_reports: 各维度规划思路报告字典（用于部分状态传递）
        task_description: 规划任务描述
        constraints: 约束条件
        required_dimensions: 指定生成的维度列表（None = 全部）
        enable_human_review: 是否启用人工审核

    Returns:
        包含最终详细规划报告的字典
    """
    logger.info(f"[子图调用] 开始调用详细规划子图: {project_name}")

    # 创建子图实例
    subgraph = create_detailed_plan_subgraph()

    # 如果没有指定维度，默认生成所有维度
    if required_dimensions is None:
        required_dimensions = ALL_DIMENSIONS

    # 构建初始状态
    initial_state: DetailedPlanState = {
        "project_name": project_name,
        "analysis_report": analysis_report,
        "dimension_reports": dimension_reports or {},  # 新增
        "planning_concept": planning_concept,
        "concept_dimension_reports": concept_dimension_reports or {},  # 新增
        "task_description": task_description,
        "constraints": constraints,
        "required_dimensions": required_dimensions,
        "completed_dimensions": [],
        "current_dimension": "",
        "industry_plan": "",
        "master_plan": "",
        "traffic_plan": "",
        "public_service_plan": "",
        "infrastructure_plan": "",
        "ecological_plan": "",
        "disaster_prevention_plan": "",
        "heritage_plan": "",
        "landscape_plan": "",
        "project_bank": "",
        "need_review": enable_human_review,
        "human_feedback": {},
        "revision_count": {},
        "dimension_plans": [],
        "final_detailed_plan": "",
        "consolidated_project_bank": "",
        "messages": []
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        logger.info(f"[子图调用] 子图执行成功，报告长度: {len(result.get('final_detailed_plan', ''))} 字符")

        return {
            "detailed_plan_report": result["final_detailed_plan"],
            "industry_plan": result.get("industry_plan", ""),
            "master_plan": result.get("master_plan", ""),
            "traffic_plan": result.get("traffic_plan", ""),
            "public_service_plan": result.get("public_service_plan", ""),
            "infrastructure_plan": result.get("infrastructure_plan", ""),
            "ecological_plan": result.get("ecological_plan", ""),
            "disaster_prevention_plan": result.get("disaster_prevention_plan", ""),
            "heritage_plan": result.get("heritage_plan", ""),
            "landscape_plan": result.get("landscape_plan", ""),
            "project_bank": result.get("project_bank", ""),
            "completed_dimensions": result.get("completed_dimensions", []),
            "success": True
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "detailed_plan_report": f"详细规划失败: {str(e)}",
            "success": False,
            "error": str(e)
        }


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试数据
    test_analysis = """
    # 某某村现状分析报告

    区位分析：位于XX市XX区，距离市中心25公里，交通便利。
    社会经济：人口1200人，主要产业为农业和旅游业。
    自然环境：丘陵地貌，森林覆盖率68%。
    基础设施：道路基本硬化，供水设施完善，污水处理不足。
    公共服务：有小学、卫生室、文化广场，设施较完善。
    """

    test_concept = """
    # 某某村规划思路

    规划定位：生态旅游示范村
    发展目标：3年内创建3A级景区，年接待游客10万人次
    规划策略：生态优先、产业融合、文化传承
    """

    # 测试单个维度
    print("=== 测试单个维度生成 ===\n")
    result = call_detailed_plan_subgraph(
        project_name="测试村",
        analysis_report=test_analysis,
        planning_concept=test_concept,
        required_dimensions=["industry", "traffic"]  # 只生成2个维度
    )

    print("\n=== 执行完成 ===")
    print(f"成功: {result['success']}")
    print(f"完成的维度: {result['completed_dimensions']}")
    print(f"报告长度: {len(result['detailed_plan_report'])} 字符")

    if result['success']:
        print("\n=== 产业规划预览 ===")
        print(result['industry_plan'][:800])
