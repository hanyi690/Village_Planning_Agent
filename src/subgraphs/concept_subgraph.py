"""
规划思路子图 (Concept Subgraph)

基于现状分析，生成规划思路，包含4个维度的并行分析：
1. 资源禀赋分析
2. 规划定位分析
3. 发展目标分析
4. 规划策略分析

使用 LangGraph 的 Send 机制实现 Map-Reduce 模式。
支持部分状态传递优化，根据维度依赖关系筛选相关的现状分析信息。
"""

from typing import TypedDict, List, Dict, Any
from typing_extensions import Annotated
from langgraph.graph import StateGraph, END, START
from langgraph.types import Send
from langgraph.graph.message import add_messages
from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
import operator

from ..core.config import LLM_MODEL, MAX_TOKENS
from ..config.dimension_metadata import (
    get_analysis_to_concept_mapping, 
    get_analysis_dimension_names,
    get_concept_dimension_names,
    get_dimensions_by_wave,
    get_full_dependency_chain_func,
    list_dimensions
)
from ..utils.logger import get_logger
from .concept_prompts import (
    RESOURCE_ENDOWMENT_PROMPT,
    PLANNING_POSITIONING_PROMPT,
    DEVELOPMENT_GOALS_PROMPT,
    PLANNING_STRATEGIES_PROMPT,
    CONCEPT_SUMMARY_PROMPT
)

logger = get_logger(__name__)


# ==========================================
# 子图状态定义
# ==========================================

class ConceptState(TypedDict):
    """规划思路子图的状态"""
    # 输入数据
    analysis_reports: Dict[str, str]  # 各维度现状分析报告字典（用于部分状态传递）
    project_name: str            # 项目名称
    task_description: str         # 规划任务描述
    constraints: str             # 约束条件

    # 中间状态 - 用于并行分析
    dimensions: List[str]        # 待分析的维度列表
    concept_analyses: Annotated[List[Dict[str, str]], operator.add]  # 已完成的维度分析

    # 输出数据（统一命名）
    concept_reports: Dict[str, str]  # 各维度独立报告（用于部分状态传递）

    # 波次路由状态
    current_wave: int              # 当前波次 (1-4)
    total_waves: int               # 总波次数 (4)
    completed_dimensions: List[str] # 已完成的维度

    # 消息历史
    messages: Annotated[List[BaseMessage], add_messages]


class ConceptDimensionState(TypedDict):
    """单个维度分析的状态（用于并行节点）"""
    dimension_key: str           # 维度标识
    dimension_name: str           # 维度名称
    filtered_analysis: str       # 筛选后的现状分析文本（直接用于 Prompt）
    filtered_concept: str        # 筛选后的规划思路文本（来自前序 Layer 2 维度）
    task_description: str         # 规划任务
    constraints: str             # 约束条件
    concept_result: str          # 分析结果


# ==========================================
# LLM 调用辅助函数
# ==========================================

def _get_llm():
    """获取 LLM 实例，使用统一的 LLM 工厂"""
    from ..core.llm_factory import create_llm
    return create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)


# ==========================================
# 并行分析节点函数
# ==========================================

def analyze_concept_dimension(state: ConceptDimensionState) -> Dict[str, Any]:
    """
    执行单个规划思路维度的分析

    使用 GenericPlanner 统一架构，充分利用现有的基础设施。

    Args:
        state: 包含维度信息和输入数据的状态

    Returns:
        该维度的分析结果（包装在列表中以支持 operator.add 累加）
    """
    dimension_key = state["dimension_key"]
    dimension_name = state["dimension_name"]

    logger.info(f"[子图-规划] 开始执行 {dimension_name} ({dimension_key})")
    logger.info(f"[子图-规划] {dimension_name} 输入数据: "
               f"filtered_analysis={len(state.get('filtered_analysis', ''))}字符, "
               f"filtered_concept={len(state.get('filtered_concept', ''))}字符")

    try:
        # 【使用统一架构】使用 GenericPlannerFactory 创建规划器
        from ..planners.generic_planner import GenericPlannerFactory
        planner = GenericPlannerFactory.create_planner(dimension_key)

        # 【使用统一架构】调用规划器的 execute 方法
        # 直接传递已筛选的 filtered_analysis 和 filtered_concept 字段
        planner_state = {
            "filtered_analysis": state.get("filtered_analysis", ""),  # 预筛选的分析文本
            "filtered_concept": state.get("filtered_concept", ""),    # 前序 Layer 2 报告
            "project_name": state.get("project_name", "村庄"),
            "task_description": state["task_description"],
            "constraints": state["constraints"]
        }
        planner_result = planner.execute(planner_state)

        # GenericPlanner 返回的结果键名由 get_result_key() 决定
        result_key = planner.get_result_key()
        concept_text = planner_result.get(result_key, planner_result.get("concept_result", ""))
        logger.info(f"[子图-规划] 完成 {dimension_name}，生成 {len(concept_text)} 字符")

        # 在 LangGraph 1.0.x 中，使用 operator.add 时需要返回列表
        return {
            "concept_analyses": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "concept_result": concept_text
            }]
        }

    except Exception as e:
        logger.error(f"[子图-规划] {dimension_name} 执行失败: {str(e)}")
        # 返回错误信息而非崩溃
        return {
            "concept_analyses": [{
                "dimension_key": dimension_key,
                "dimension_name": dimension_name,
                "concept_result": f"[分析失败] {str(e)}"
            }]
        }


def _get_dimension_prompt(
    dimension_key: str,
    analysis_report: str,
    task_description: str,
    constraints: str
) -> str:
    """获取指定维度的 Prompt 模板"""
    prompts_map = {
        "resource_endowment": RESOURCE_ENDOWMENT_PROMPT,
        "planning_positioning": PLANNING_POSITIONING_PROMPT,
        "development_goals": DEVELOPMENT_GOALS_PROMPT,
        "planning_strategies": PLANNING_STRATEGIES_PROMPT,
    }

    if dimension_key not in prompts_map:
        raise ValueError(f"未知的规划维度: {dimension_key}")

    prompt_template = prompts_map[dimension_key]
    return prompt_template.format(
        project_name="",  # 可以从 state 中获取
        analysis_report=analysis_report[:3000],  # 限制长度
        task_description=task_description,
        constraints=constraints
    )


# ==========================================
# 波次路由与分发节点
# ==========================================

def route_by_dependency_wave(state: ConceptState):
    """
    基于依赖波次的动态路由函数

    Layer 2 有 4 个波次：
    - Wave 1: resource_endowment（无同层依赖）
    - Wave 2: planning_positioning（依赖 resource_endowment）
    - Wave 3: development_goals（依赖 resource_endowment + planning_positioning）
    - Wave 4: planning_strategies（依赖前三个）

    Returns:
        List[Send]: Send对象列表（并行执行多个维度）
        str: 节点名称（"advance_wave", END）
    """
    current_wave = state.get("current_wave", 1)
    completed = set(state.get("completed_dimensions", []))
    total_waves = state.get("total_waves", 4)

    logger.info(f"[子图-L2-波次路由] 当前Wave: {current_wave}/{total_waves}")

    # 获取当前波次的维度
    wave_dims = get_dimensions_by_wave(current_wave, layer=2)
    pending = [d for d in wave_dims if d not in completed]

    if pending:
        logger.info(f"[子图-L2-波次路由] Wave {current_wave}: {len(pending)} 个维度并行执行: {pending}")
        return create_parallel_tasks_with_state_filtering(state, pending)
    else:
        # 当前波次完成
        if current_wave < total_waves:
            logger.info(f"[子图-L2-波次路由] Wave {current_wave} 完成，推进到 Wave {current_wave + 1}")
            return "advance_wave"
        else:
            logger.info("[子图-L2-波次路由] 所有维度完成，流程结束")
            return END

    # 默认结束
    return END


def create_parallel_tasks_with_state_filtering(
    state: ConceptState,
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
    analysis_reports = state.get("analysis_reports", {})
    concept_reports = state.get("concept_reports", {})  # 已完成的 Layer 2 报告

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
        
        # 提取已完成的 Layer 2 规划思路（同层依赖）
        required_concepts = chain.get("depends_on_same_layer", [])
        filtered_concept_parts = []
        for k in required_concepts:
            if k in concept_reports:
                name = get_concept_dimension_names().get(k, k)
                filtered_concept_parts.append(f"### {name}\n\n{concept_reports[k]}\n")
        filtered_concept = "\n".join(filtered_concept_parts) if filtered_concept_parts else ""

        # 构建维度状态
        dimension_info = {d["key"]: d for d in list_dimensions(layer=2)}.get(dim, {"name": dim})
        dimension_state = ConceptDimensionState({
            "dimension_key": dim,
            "dimension_name": dimension_info.get("name", dim),
            "filtered_analysis": filtered_analysis,
            "filtered_concept": filtered_concept,
            "task_description": state["task_description"],
            "constraints": state["constraints"],
            "concept_result": ""
        })

        sends.append(Send("analyze_concept_dimension", dimension_state))
        
        logger.info(f"[状态筛选-L2] {dim}: "
                   f"现状 {len(required_analyses)} 个 ({len(filtered_analysis)}字符), "
                   f"思路 {len(required_concepts)} 个 ({len(filtered_concept)}字符)")

    logger.info(f"[子图-L2-Map] 创建了 {len(sends)} 个并行任务")
    return sends


def advance_wave_node(state: ConceptState) -> Dict[str, Any]:
    """
    推进波次节点：将当前波次加1
    """
    current_wave = state.get("current_wave", 1)
    logger.info(f"[子图-L2-推进波次] Wave {current_wave} → Wave {current_wave + 1}")
    return {"current_wave": current_wave + 1}


def reduce_concept_analyses(state: ConceptState) -> Dict[str, Any]:
    """
    Reduce 阶段：汇总当前波次维度的分析结果

    更新 completed_dimensions 和 concept_reports，用于波次路由
    """
    logger.info(f"[子图-Reduce] 开始汇总 {len(state['concept_analyses'])} 个维度的分析结果")

    # 整理分析结果为结构化格式
    concept_reports_dict = dict(state.get("concept_reports", {}))  # 保留已有报告
    completed_dims = list(state.get("completed_dimensions", []))   # 保留已完成维度

    for analysis in state["concept_analyses"]:
        dimension_key = analysis['dimension_key']
        concept_text = analysis['concept_result']

        # 保存独立的维度报告（用于部分传输）
        concept_reports_dict[dimension_key] = concept_text
        
        # 记录已完成维度
        if dimension_key not in completed_dims:
            completed_dims.append(dimension_key)

    logger.info(f"[子图-Reduce] 汇总完成，已累计 {len(concept_reports_dict)} 个维度报告，"
               f"已完成维度: {completed_dims}")
    return {
        "concept_reports": concept_reports_dict,
        "completed_dimensions": completed_dims
    }


# ==========================================
# 最终规划思路生成节点
# ==========================================

def generate_final_concept(state: ConceptState) -> Dict[str, Any]:
    """
    生成最终规划思路报告

    整合4个维度的分析结果，使用汇总 Prompt 生成连贯的报告。
    支持LangSmith tracing。
    """
    logger.info("[子图-汇总] 开始生成最终规划思路报告")

    try:
        # 使用 reduce 阶段生成的 dimension_reports_text
        dimension_reports_text = state.get("dimension_reports_text", "")

        # 如果 dimension_reports_text 为空，从 concept_analyses 重新构建
        if not dimension_reports_text:
            for analysis in state["concept_analyses"]:
                dimension_reports_text += f"\n### {analysis['dimension_name']}\n{analysis['concept_result']}\n"

        # 构建汇总 Prompt
        summary_prompt = CONCEPT_SUMMARY_PROMPT.format(
            project_name=state["project_name"],
            task_description=state["task_description"],
            dimension_reports=dimension_reports_text
        )

        # 调用 LLM 生成最终报告（支持LangSmith）
        from ..core.llm_factory import create_llm
        from ..core.langsmith_integration import get_langsmith_manager

        # 创建LangSmith metadata
        langsmith = get_langsmith_manager()
        metadata = None
        if langsmith.is_enabled():
            metadata = langsmith.create_run_metadata(
                project_name=state.get('project_name', '村庄'),
                dimension="concept_summary",
                layer=2
            )

        llm = create_llm(
            model=LLM_MODEL,
            temperature=0.7,
            max_tokens=MAX_TOKENS,
            metadata=metadata
        )
        response = llm.invoke([HumanMessage(content=summary_prompt)])

        final_concept = f"""# {state['project_name']} 规划思路报告

{response.content}
---

**生成时间**: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

        logger.info(f"[子图-汇总] 规划思路报告生成完成，共 {len(final_concept)} 字符")

        return {
            "final_concept": final_concept,
            "messages": [AIMessage(content=final_concept)]
        }

    except Exception as e:
        logger.error(f"[子图-汇总] 报告生成失败: {str(e)}")

        # 降级方案：直接拼接各维度结果
        fallback_concept = f"""# {state['project_name']} 规划思路报告（简化版）

## 各维度分析

"""
        for analysis in state["concept_analyses"]:
            fallback_concept += f"### {analysis['dimension_name']}\n\n{analysis['concept_result']}\n\n"

        return {
            "final_concept": fallback_concept,
            "messages": [AIMessage(content=fallback_concept)]
        }


# ==========================================
# 初始化节点
# ==========================================

def initialize_concept_analysis(state: ConceptState) -> Dict[str, Any]:
    """
    初始化规划思路分析流程，设置待分析的维度列表和波次状态
    """
    logger.info(f"[子图-初始化] 开始规划思路分析，项目: {state.get('project_name', '未命名')}")

    # 定义4个规划维度
    all_dimensions = [
        "resource_endowment",   # 资源禀赋
        "planning_positioning",  # 规划定位
        "development_goals",     # 发展目标
        "planning_strategies"    # 规划策略
    ]

    logger.info(f"[子图-初始化] 设置 {len(all_dimensions)} 个规划维度，共4个波次")

    return {
        "dimensions": all_dimensions,
        "concept_analyses": [],
        "current_wave": 1,  # 初始化波次
        "total_waves": 4,   # 总波次数
        "completed_dimensions": [],  # 已完成维度
        "concept_reports": state.get("concept_reports", {})  # 保留已有报告
    }


# ==========================================
# 构建子图
# ==========================================

def create_concept_subgraph() -> StateGraph:
    """
    创建规划思路子图 - 使用波次路由模式

    执行流程：
    START → initialize → route_by_wave → [analyze_concept_dimension]* → reduce_analyses → advance_wave/END
    
    波次依赖：
    - Wave 1: resource_endowment（无同层依赖）
    - Wave 2: planning_positioning（依赖 resource_endowment）
    - Wave 3: development_goals（依赖 resource_endowment + planning_positioning）
    - Wave 4: planning_strategies（依赖前三个）

    Returns:
        编译后的 StateGraph 实例
    """
    from ..nodes.subgraph_nodes import (
        InitializeConceptNode,
        AnalyzeConceptDimensionNode,
        ReduceConceptsNode,
        GenerateConceptReportNode
    )

    logger.info("[子图构建] 开始构建规划思路子图（波次路由模式）")

    # 创建状态图
    builder = StateGraph(ConceptState)

    # 创建节点实例
    initialize_node = InitializeConceptNode()
    analyze_node = AnalyzeConceptDimensionNode()
    reduce_node = ReduceConceptsNode()
    report_node = GenerateConceptReportNode()

    # 添加节点
    builder.add_node("initialize", initialize_node)
    builder.add_node("analyze_concept_dimension", analyze_node)
    builder.add_node("reduce_analyses", reduce_node)
    builder.add_node("advance_wave", advance_wave_node)  # 波次推进节点

    # 构建执行流程
    builder.add_edge(START, "initialize")

    # 波次路由：从 initialize 路由到各维度或结束
    builder.add_conditional_edges(
        "initialize",
        route_by_dependency_wave,
        {
            "advance_wave": "advance_wave",
            END: END
        }
    )

    # 分析节点完成后进入 reduce
    builder.add_edge("analyze_concept_dimension", "reduce_analyses")

    # reduce 完成后路由：检查是否还有下一波次
    builder.add_conditional_edges(
        "reduce_analyses",
        route_by_dependency_wave,
        {
            "advance_wave": "advance_wave",
            END: END
        }
    )

    # advance_wave 后重新路由
    builder.add_conditional_edges(
        "advance_wave",
        route_by_dependency_wave,
        {
            "advance_wave": "advance_wave",
            END: END
        }
    )

    # 编译子图
    concept_subgraph = builder.compile()

    logger.info("[子图构建] 规划思路子图构建完成（波次路由模式）")

    return concept_subgraph


# ==========================================
# 子图包装函数（用于父图调用）
# ==========================================

def call_concept_subgraph(
    project_name: str,
    analysis_reports: Dict[str, str] = None,
    task_description: str = "制定村庄总体规划思路",
    constraints: str = "无特殊约束"
) -> Dict[str, Any]:
    """
    调用规划思路子图的包装函数

    Args:
        project_name: 项目/村庄名称
        analysis_reports: 各维度现状分析报告字典（用于部分状态传递）
        task_description: 规划任务描述
        constraints: 约束条件

    Returns:
        包含最终规划思路报告的字典
    """
    logger.info(f"[子图调用] 开始调用规划思路子图: {project_name}")

    # 创建子图实例
    subgraph = create_concept_subgraph()

    # 构建初始状态
    initial_state: ConceptState = {
        "analysis_reports": analysis_reports or {},
        "project_name": project_name,
        "task_description": task_description,
        "constraints": constraints,
        "dimensions": [],
        "concept_analyses": [],
        "concept_reports": {},
        "current_wave": 1,  # 初始化波次
        "total_waves": 4,   # 总波次数
        "completed_dimensions": [],  # 已完成维度
        "messages": []
    }

    try:
        # 调用子图
        result = subgraph.invoke(initial_state)

        logger.info(f"[子图调用] 子图执行成功，维度报告数量: {len(result.get('concept_reports', {}))}")

        return {
            "concept_report": "",  # 已删除综合报告，保留此字段用于兼容
            "concept_reports": result.get("concept_reports", {}),
            "success": True
        }

    except Exception as e:
        logger.error(f"[子图调用] 子图执行失败: {str(e)}")
        return {
            "concept_report": f"规划思路分析失败: {str(e)}",
            "concept_reports": {},
            "success": False
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
    """

    # 创建并运行子图
    subgraph = create_concept_subgraph()

    initial_state = {
        "analysis_reports": {},
        "project_name": "测试村",
        "task_description": "制定乡村振兴规划思路",
        "constraints": "生态优先，绿色发展",
        "dimensions": [],
        "concept_analyses": [],
        "concept_reports": {},
        "messages": []
    }

    print("=== 开始执行规划思路子图 ===\n")

    result = subgraph.invoke(initial_state)

    print("\n=== 执行完成 ===")
    print(f"报告数: {len(result.get('concept_reports', {}))} 个维度")
    print("\n=== 维度报告 ===")
    for key, value in result.get("concept_reports", {}).items():
        print(f"- {key}: {len(value)} 字符")
