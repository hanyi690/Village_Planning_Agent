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

使用 LangGraph 的 Send 机制实现基于波次的动态并行调度。
支持人机交互反馈循环。
支持部分状态传递优化，根据维度依赖关系筛选相关信息。

关键特性：
- Wave 1: 9个独立维度完全并行执行
- Wave 2: project_bank等待Wave 1完成后执行
- 智能状态筛选：每个维度只接收其依赖的3-4个现状维度
"""

from typing import TypedDict, List, Dict, Any, Literal, Union
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send, interrupt
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
import operator
from datetime import datetime

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..config.dimension_metadata import (
    get_full_dependency_chain,
    get_full_dependency_chain_func,
    get_wave_config,
    get_execution_wave,
    get_dimensions_by_wave,
    check_detailed_dependencies_ready,
    get_detailed_dimension_names,
    get_analysis_dimension_names,
    get_concept_dimension_names,
    list_dimensions
)
from ..utils.logger import get_logger
from .detailed_plan_prompts import (
    INDUSTRY_PLANNING_PROMPT,
    MASTER_PLAN_PROMPT,
    SPATIAL_STRUCTURE_PROMPT,
    LAND_USE_PLANNING_PROMPT,
    SETTLEMENT_PLANNING_PROMPT,
    TRAFFIC_PLANNING_PROMPT,
    PUBLIC_SERVICE_PROMPT,
    INFRASTRUCTURE_PROMPT,
    ECOLOGICAL_PROMPT,
    DISASTER_PREVENTION_PROMPT,
    HERITAGE_PROMPT,
    LANDSCAPE_PROMPT,
    PROJECT_BANK_PROMPT,
    DETAILED_PLAN_SUMMARY_PROMPT,
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
    analysis_reports: Dict[str, str]  # 各维度现状分析报告字典（用于部分状态传递）
    concept_reports: Dict[str, str]   # 各维度规划思路报告字典（用于部分状态传递）
    task_description: str
    constraints: str
    village_data: str              # 村庄原始数据（用于适配器）

    # 规划维度控制
    required_dimensions: List[str] # 需要生成的维度列表
    completed_dimensions: List[str] # 已完成的维度
    current_dimension: str         # 当前处理的维度

    # 动态路由字段
    current_wave: int              # 当前执行波次 (1 或 2)
    total_waves: int               # 总波次数（固定为2）
    completed_dimension_reports: Dict[str, str]  # 已完成维度的报告（project_bank需要）
    token_usage_stats: Dict[str, dict]  # Token使用统计

    # 适配器配置
    enable_adapters: bool          # 是否启用适配器
    adapter_config: Dict[str, List[str]]  # 各维度的适配器配置

    # 输出数据（统一命名，只保留字典形式）
    detail_reports: Dict[str, str]  # 各维度独立报告（唯一输出）

    # 【新增】RAG 知识缓存 - 预加载的知识上下文
    knowledge_cache: Dict[str, str]  # 维度 -> 知识上下文

    # 人机交互状态
    need_review: bool              # 是否需要人工审核
    human_feedback: Dict[str, str] # 各维度的反馈意见
    revision_count: Dict[str, int] # 各维度修改次数

    # 中间结果（用于并行处理）
    dimension_plans: Annotated[List[Dict[str, str]], operator.add]  # 已完成的维度规划

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


class DetailedDimensionState(TypedDict):
    """单个维度规划的状态（用于并行节点）"""
    dimension_key: str             # 维度标识
    dimension_name: str            # 维度名称
    project_name: str
    task_description: str
    constraints: str
    human_feedback: str            # 针对该维度的反馈意见
    dimension_result: str          # 规划结果
    # 支持前序规划（project_bank需要）
    completed_plans: Dict[str, str]  # 已完成的前序详细规划
    dependency_chain: dict         # 完整依赖链信息
    # 适配器支持
    enable_adapters: bool          # 是否启用适配器
    adapter_config: Dict[str, List[str]]  # 适配器配置
    village_data: str              # 村庄原始数据（用于适配器）
    # 筛选后的报告文本（直接用于 Prompt）
    filtered_analysis: str         # 筛选后的现状分析文本
    filtered_concept: str          # 筛选后的规划思路文本
    filtered_detail: str           # 筛选后的前序详细规划文本
    # 【新增】RAG 知识缓存
    knowledge_cache: Dict[str, str]  # 维度 -> 知识上下文


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
DIMENSION_NAMES = get_detailed_dimension_names

# 【新增】波次配置常量
TOTAL_WAVES = 2


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
    初始化详细规划流程，设置待规划的维度列表和波次信息
    """
    logger.info(f"[子图-L3-初始化] 开始详细规划，项目: {state.get('project_name', '未命名')}")

    # 如果没有指定维度，默认生成所有维度
    required = state.get("required_dimensions", ALL_DIMENSIONS)

    # 验证维度有效性
    valid_dimensions = [d for d in required if d in ALL_DIMENSIONS]

    # 初始化波次执行
    current_wave = 1
    total_waves = TOTAL_WAVES

    logger.info(f"[子图-L3-初始化] 设置 {len(valid_dimensions)} 个规划维度")
    logger.info(f"[子图-L3-初始化] 开始 Wave {current_wave}/{total_waves}")

    return {
        "required_dimensions": valid_dimensions,
        "completed_dimensions": [],
        "dimension_plans": [],
        "human_feedback": state.get("human_feedback", {}),
        "revision_count": state.get("revision_count", {}),
        "current_wave": current_wave,
        "total_waves": total_waves,
        "completed_dimension_reports": {},
        "token_usage_stats": {}
    }


# ==========================================
# 知识预加载节点
# ==========================================

# Layer 3 关键维度（需要 RAG 知识检索）
LAYER3_CRITICAL_DIMENSIONS = [
    "land_use_planning",       # 土地利用规划
    "infrastructure_planning", # 基础设施规划
    "ecological",              # 生态绿地规划
    "disaster_prevention",     # 防震减灾规划
    "heritage"                 # 历史文保规划
]


def knowledge_preload_node(state: DetailedPlanState) -> Dict[str, Any]:
    """
    预加载关键维度的 RAG 知识上下文

    在并行规划开始前，统一检索关键维度所需的知识，缓存到状态中。
    各维度规划节点从缓存读取，避免重复调用 RAG。

    关键维度：land_use_planning, infrastructure, ecological, disaster_prevention, heritage

    Returns:
        {"knowledge_cache": {dimension_key: knowledge_content}}
    """
    logger.info("[子图-L3-知识预加载] 开始预加载关键维度知识")

    # 检查 RAG 是否可用
    try:
        from ..rag.core.tools import knowledge_search_tool
        RAG_AVAILABLE = True
    except ImportError:
        logger.warning("[子图-L3-知识预加载] RAG 工具不可用，跳过知识预加载")
        return {"knowledge_cache": {}}

    knowledge_cache: Dict[str, str] = {}
    required_dimensions = state.get("required_dimensions", [])

    # 只为关键维度预加载知识
    dimensions_to_load = [d for d in LAYER3_CRITICAL_DIMENSIONS if d in required_dimensions]

    for dimension_key in dimensions_to_load:
        try:
            # 获取维度名称用于构建查询
            dimension_names = get_detailed_dimension_names()
            dimension_name = dimension_names.get(dimension_key, dimension_key)

            # 构建维度特定的查询
            query = f"{dimension_name} 技术规范 标准 实施要求 规划导则"

            # 调用 RAG 工具检索知识（Layer 3 使用更详细的上下文）
            result = knowledge_search_tool.invoke({
                "query": query,
                "top_k": 5,
                "context_mode": "expanded"  # Layer 3 使用扩展模式
            })

            if result and result.strip():
                knowledge_cache[dimension_key] = result
                logger.info(f"[子图-L3-知识预加载] {dimension_key}: 检索到 {len(result)} 字符知识")

        except Exception as e:
            logger.warning(f"[子图-L3-知识预加载] {dimension_key} 检索失败: {e}")
            continue

    logger.info(f"[子图-L3-知识预加载] 完成，缓存 {len(knowledge_cache)} 个维度知识")
    return {"knowledge_cache": knowledge_cache}


# ==========================================
# 路由节点 - 基于波次的动态路由
# ==========================================

def route_by_dependency_wave(state: DetailedPlanState) -> Union[List[Send], str]:
    """
    基于依赖波次的动态路由函数

    逻辑：
    1. 检查当前波次（Wave 1 或 Wave 2）
    2. 筛选出当前波次可执行的维度
    3. 对于Wave 1：返回9个维度的Send对象（完全并行）
    4. 对于Wave 2：检查project_bank的9个前序依赖是否完成
    5. 返回路由决策

    Returns:
        List[Send]: Send对象列表（并行执行多个维度）
        str: 节点名称（"advance_wave", "route_next", END）
    """
    current_wave = state.get("current_wave", 1)
    completed = set(state.get("completed_dimensions", []))

    logger.info(f"[子图-L3-波次路由] 当前Wave: {current_wave}/{state.get('total_waves', 2)}")

    if current_wave == 1:
        # Wave 1: Layer 3 的 Wave 1 维度并行执行
        wave1_dims = get_dimensions_by_wave(1, layer=3)  # 关键修复：只获取 Layer 3 的维度
        pending = [d for d in wave1_dims if d not in completed]

        if pending:
            logger.info(f"[子图-L3-波次路由] Wave 1: {len(pending)} 个维度并行执行")
            return create_parallel_tasks_with_state_filtering(state, pending)
        else:
            # Wave 1 完成，推进到 Wave 2
            logger.info("[子图-L3-波次路由] Wave 1 全部完成，推进到 Wave 2")
            return "advance_wave"

    elif current_wave == 2:
        # Wave 2: 只有 project_bank
        if "project_bank" not in completed:
            # 检查依赖是否满足
            if check_detailed_dependencies_ready("project_bank", list(completed)):
                logger.info("[子图-L3-波次路由] Wave 2: project_bank 依赖满足，开始执行")
                return create_parallel_tasks_with_state_filtering(state, ["project_bank"])
            else:
                # 依赖未满足，强制推进（异常情况）
                logger.warning("[子图-L3-波次路由] Wave 2: project_bank 依赖未满足，强制执行")
                return create_parallel_tasks_with_state_filtering(state, ["project_bank"])
        else:
            # 所有维度完成，直接结束
            logger.info("[子图-L3-波次路由] 所有维度完成，流程结束")
            return END

    # 默认结束
    return END


def create_parallel_tasks_with_state_filtering(
    state: DetailedPlanState,
    dimensions: List[str]
) -> List[Send]:
    """
    创建并行任务，每个任务携带经过筛选的状态

    直接从 dimension_metadata 获取依赖链，提取相关报告文本

    Args:
        state: 主状态
        dimensions: 要并行执行的维度列表

    Returns:
        Send对象列表
    """
    sends = []
    completed_detailed = state.get("completed_dimension_reports", {})

    analysis_reports = state.get("analysis_reports", {})
    concept_reports = state.get("concept_reports", {})

    for dim in dimensions:
        # 直接获取依赖链
        chain = get_full_dependency_chain_func(dim)
        
        # 提取 Layer 1 现状分析
        required_analyses = chain.get("layer1_analyses", [])
        filtered_analysis_parts = []
        for k in required_analyses:
            if k in analysis_reports:
                name = get_analysis_dimension_names().get(k, k)
                filtered_analysis_parts.append(f"### {name}\n\n{analysis_reports[k]}\n")
        filtered_analysis = "\n".join(filtered_analysis_parts) if filtered_analysis_parts else ""
        
        # 提取 Layer 2 规划思路
        required_concepts = chain.get("layer2_concepts", [])
        filtered_concept_parts = []
        for k in required_concepts:
            if k in concept_reports:
                name = get_concept_dimension_names().get(k, k)
                filtered_concept_parts.append(f"### {name}\n\n{concept_reports[k]}\n")
        filtered_concept = "\n".join(filtered_concept_parts) if filtered_concept_parts else ""
        
        # 提取 Layer 3 前序详细规划（project_bank 需要）
        required_details = chain.get("layer3_plans", [])
        filtered_detail_parts = []
        for k in required_details:
            if k in completed_detailed:
                name = get_detailed_dimension_names().get(k, k)
                filtered_detail_parts.append(f"### {name}\n\n{completed_detailed[k]}\n")
        filtered_detail = "\n".join(filtered_detail_parts) if filtered_detail_parts else ""

        # 构建维度状态
        dimension_info = {d["key"]: d for d in list_dimensions(layer=3)}.get(dim, {"name": dim})
        dimension_state = DetailedDimensionState({
            "dimension_key": dim,
            "dimension_name": dimension_info.get("name", dim),
            "project_name": state["project_name"],
            "task_description": state.get("task_description", "制定详细规划"),
            "constraints": state.get("constraints", ""),
            "human_feedback": state.get("human_feedback", {}).get(dim, ""),
            "dimension_result": "",
            "completed_plans": {k: completed_detailed[k] for k in required_details if k in completed_detailed},
            "dependency_chain": chain,
            # 适配器配置
            "enable_adapters": state.get("enable_adapters", False),
            "adapter_config": state.get("adapter_config", {}),
            "village_data": state.get("village_data", ""),
            # 传递筛选后的文本
            "filtered_analysis": filtered_analysis,
            "filtered_concept": filtered_concept,
            "filtered_detail": filtered_detail,
            # 【新增】传递知识缓存
            "knowledge_cache": state.get("knowledge_cache", {})
        })

        sends.append(Send("generate_dimension_plan", dimension_state))
        
        logger.info(f"[状态筛选] {dim}: "
                   f"现状 {len(required_analyses)} 个 ({len(filtered_analysis)}字符), "
                   f"思路 {len(required_concepts)} 个 ({len(filtered_concept)}字符), "
                   f"前序 {len(required_details)} 个 ({len(filtered_detail)}字符)")

    return sends


def advance_wave_node(state: DetailedPlanState) -> Dict[str, Any]:
    """推进到下一个波次"""
    current_wave = state.get("current_wave", 1)
    next_wave = current_wave + 1

    logger.info(f"[子图-L3-波次推进] Wave {current_wave} → Wave {next_wave}")

    return {"current_wave": next_wave}


# ==========================================
# 单维度生成节点 - 处理最后一个维度
# ==========================================

# 注：该函数已废弃，波次路由版本使用纯并行执行，不再需要单维度生成节点


# ==========================================
# 专业Agent节点 - 生成各维度规划
# ==========================================

def generate_dimension_plan(state: DetailedDimensionState) -> Dict[str, Any]:
    """
    生成单个维度的详细规划 - 增强版：支持适配器

    使用 GenericPlanner 统一架构，充分利用现有的基础设施。
    支持使用completed_plans（project_bank需要）。
    新增：支持适配器调用以获取专业分析数据。
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]
    project_name = state["project_name"]

    logger.info(f"[子图-L3-Agent] 开始生成 {dimension_name} ({dimension_key})")
    logger.debug(f"[子图-L3-Agent] {dimension_name} 输入数据: "
               f"filtered_analysis={len(state.get('filtered_analysis', ''))}字符, "
               f"filtered_concept={len(state.get('filtered_concept', ''))}字符, "
               f"completed_plans={len(state.get('completed_plans', {}))}个")

    try:
        # 【使用统一架构】使用 GenericPlannerFactory 创建规划器
        from ..planners.generic_planner import GenericPlannerFactory
        planner = GenericPlannerFactory.create_planner(dimension_key)

        # 【使用统一架构】调用规划器的 execute 方法
        planner_state = {
            "project_name": project_name,
            "filtered_analysis": state.get("filtered_analysis", ""),  # 修复：使用正确的字段名
            "filtered_concept": state.get("filtered_concept", ""),    # 修复：使用正确的字段名
            "completed_plans": state.get("completed_plans", {}),
            "task_description": state["task_description"],
            "constraints": state["constraints"],
            "village_data": state.get("village_data", ""),  # 新增：用于适配器
            "knowledge_cache": state.get("knowledge_cache", {})  # 【新增】传递知识缓存
        }

        # 【新增】检查是否启用适配器
        use_adapters = state.get("enable_adapters", False)
        adapter_config = state.get("adapter_config", {})

        # 获取该维度的适配器配置
        adapter_types = adapter_config.get(dimension_key, [])

        # 只在启用适配器时才输出日志
        if use_adapters and adapter_types:
            logger.info(f"[子图-L3-Agent] 适配器启用: types={adapter_types}")

        # 执行规划（带适配器支持）
        planner_result = planner.execute(
            state=planner_state,
            enable_langsmith=True
        )

        # GenericPlanner 返回的结果键名由 get_result_key() 决定
        result_key = planner.get_result_key()
        plan_content = planner_result.get(result_key, planner_result.get("dimension_result", ""))
        logger.info(f"[子图-L3-Agent] 完成 {dimension_name}，生成 {len(plan_content)} 字符")

        # 检查是否有反馈意见（添加到结果中）
        if state.get("human_feedback"):
            plan_content += f"""

## 修改说明
根据之前的反馈，已对规划进行以下修改：
{state['human_feedback']}

"""

        # 返回结果（包装在列表中以支持累加）
        # 注意：不再添加外部标题包装，与 Layer 1/2 保持一致，避免重复标题
        return {
            "dimension_plans": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "dimension_result": plan_content
            }]
        }

    except Exception as e:
        logger.error(f"[子图-L3-Agent] {dimension_name} 生成失败: {str(e)}")

        error_plan = f"""[规划生成失败]

错误信息: {str(e)}

请检查输入数据或稍后重试。"""

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

    同时更新 completed_dimension_reports，供后续维度（如project_bank）使用
    """
    logger.info(f"[子图-L3-Reduce] 汇总 {len(state['dimension_plans'])} 个维度的规划结果")

    # 汇总所有维度报告到字典
    detail_reports = {}
    completed = []
    completed_reports = state.get("completed_dimension_reports", {})

    for plan in state["dimension_plans"]:
        dim_key = plan["dimension_key"]
        dim_result = plan["dimension_result"]

        detail_reports[dim_key] = dim_result
        completed.append(dim_key)

        # 记录已完成维度的报告（供project_bank使用）
        completed_reports[dim_key] = dim_result

    logger.info(f"[子图-L3-Reduce] 已完成维度: {', '.join(completed)}")

    return {
        "detail_reports": detail_reports,
        "completed_dimensions": completed,
        "completed_dimension_reports": completed_reports
    }


# ==========================================
# 条件路由 - 检查是否所有维度完成
# ==========================================

def check_all_dimensions_complete(state: DetailedPlanState) -> Literal["continue", "finalize"]:
    """
    检查当前波次是否完成，决定是继续还是进入汇总

    Returns:
        "continue": 继续执行（路由到下一波次或最终节点）
        "finalize": 所有维度完成，进入汇总
    """
    current_wave = state.get("current_wave", 1)
    total_waves = state.get("total_waves", 2)

    required = set(state.get("required_dimensions", ALL_DIMENSIONS))
    completed = set(state.get("completed_dimensions", []))

    # 检查所有维度是否完成
    all_done = required.issubset(completed)

    if all_done:
        logger.info(f"[子图-L3-检查] Wave {current_wave} 完成，所有维度已生成")
        return "finalize"

    # 如果当前波次还有未完成的维度，继续路由
    logger.info(f"[子图-L3-检查] Wave {current_wave} 还有 {len(required - completed)} 个维度待生成")
    return "continue"


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
    创建详细规划子图（基于波次的动态路由版本）- 使用封装节点

    Returns:
        编译后的 StateGraph 实例
    """
    from ..nodes.subgraph_nodes import (
        InitializeDetailedPlanningNode,
        GenerateDimensionPlanNode,
        ReduceDimensionReportsNode,
        GenerateFinalDetailedPlanNode
    )

    logger.info("[子图构建] 开始构建详细规划子图（波次动态路由版本，使用封装节点）")

    # 创建状态图
    builder = StateGraph(DetailedPlanState)

    # 创建节点实例
    initialize_node = InitializeDetailedPlanningNode()
    generate_node = GenerateDimensionPlanNode()
    reduce_node = ReduceDimensionReportsNode()
    report_node = GenerateFinalDetailedPlanNode()

    # 添加节点
    builder.add_node("initialize", initialize_node)
    builder.add_node("knowledge_preload", knowledge_preload_node)  # 新增：知识预加载节点
    builder.add_node("generate_dimension_plan", generate_node)
    builder.add_node("advance_wave", advance_wave_node)  # 波次推进节点（保留函数形式）
    builder.add_node("reduce_plans", reduce_node)
    builder.add_node("check_complete", check_all_dimensions_complete)
    builder.add_node("human_review", human_review_dimension)
    # 注释掉综合报告生成节点，直接使用维度报告
    # builder.add_node("generate_final", report_node)

    # 构建执行流程
    builder.add_edge(START, "initialize")
    builder.add_edge("initialize", "knowledge_preload")  # 新增：initialize -> knowledge_preload

    # 知识预加载 -> 波次路由决策
    builder.add_conditional_edges(
        "knowledge_preload",
        route_by_dependency_wave,
        ["generate_dimension_plan", "advance_wave", END]  # 使用 END 常量
    )

    # Agent节点 -> Reduce
    builder.add_edge("generate_dimension_plan", "reduce_plans")

    # Reduce -> 检查是否完成
    builder.add_conditional_edges(
        "reduce_plans",
        check_all_dimensions_complete,
        {
            "continue": "route_next",  # 继续波次路由
            "finalize": END  # 所有维度完成，直接结束
        }
    )

    # 添加路由节点（用于再次触发波次路由）
    builder.add_node("route_next", lambda state: {})

    # 路由决策（再次使用波次路由函数）
    builder.add_conditional_edges(
        "route_next",
        route_by_dependency_wave,
        ["generate_dimension_plan", "advance_wave", END]  # 使用 END 常量
    )

    # 波次推进 -> 再次路由
    builder.add_edge("advance_wave", "route_next")

    # 编译子图
    detailed_plan_subgraph = builder.compile()

    logger.info("[子图构建] 详细规划子图构建完成（支持2波次动态路由，使用封装节点）")

    return detailed_plan_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_detailed_plan_subgraph(
    project_name: str,
    analysis_reports: Dict[str, str] = None,
    concept_reports: Dict[str, str] = None,
    task_description: str = "制定村庄详细规划",
    constraints: str = "无特殊约束",
    required_dimensions: List[str] = None,
    enable_human_review: bool = False,
    # 新增：适配器配置参数
    enable_adapters: bool = False,
    adapter_config: Dict[str, List[str]] = None,
    village_data: str = ""
) -> Dict[str, Any]:
    """
    调用详细规划子图的包装函数

    Args:
        project_name: 项目/村庄名称
        analysis_reports: 各维度现状分析报告字典（用于部分状态传递）
        concept_reports: 各维度规划思路报告字典（用于部分状态传递）
        task_description: 规划任务描述
        constraints: 约束条件
        required_dimensions: 指定生成的维度列表（None = 全部）
        enable_human_review: 是否启用人工审核
        enable_adapters: 是否启用适配器
        adapter_config: 适配器配置字典
        village_data: 村庄原始数据

    Returns:
        包含最终详细规划报告的字典
    """
    logger.info(f"[子图调用] 开始调用详细规划子图: {project_name}")

    # 创建子图实例
    subgraph = create_detailed_plan_subgraph()

    # 如果没有指定维度，默认生成所有维度
    if required_dimensions is None:
        required_dimensions = ALL_DIMENSIONS

    # 默认适配器配置
    if adapter_config is None:
        adapter_config = {
            "industry": ["gis"],
            "ecological": ["gis"],
            "traffic": ["network"],
            "infrastructure": ["gis", "network"],
            "public_service": ["network"],
            "master_plan": ["gis"],
            "landscape": ["gis"],
            "disaster_prevention": ["gis"]
        }

    # 构建初始状态
    initial_state: DetailedPlanState = {
        "project_name": project_name,
        "analysis_reports": analysis_reports or {},
        "concept_reports": concept_reports or {},
        "task_description": task_description,
        "constraints": constraints,
        "village_data": village_data,
        "required_dimensions": required_dimensions,
        "completed_dimensions": [],
        "current_dimension": "",
        # 波次路由相关字段
        "current_wave": 1,
        "total_waves": TOTAL_WAVES,
        "completed_dimension_reports": {},
        "token_usage_stats": {},
        # 适配器配置
        "enable_adapters": enable_adapters,
        "adapter_config": adapter_config,
        # 输出数据
        "detail_reports": {},
        "knowledge_cache": {},  # 【新增】知识缓存
        "need_review": enable_human_review,
        "human_feedback": {},
        "revision_count": {},
        "dimension_plans": [],
        "messages": []
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        detail_reports = result.get("detail_reports", {})
        logger.info(f"[子图调用] 子图执行成功，维度报告数量: {len(detail_reports)}")

        return {
            "detail_reports": detail_reports,
            "completed_dimensions": result.get("completed_dimensions", []),
            "success": True
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "detail_reports": {},
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
