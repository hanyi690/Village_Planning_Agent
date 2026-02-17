"""
子图节点实现

将子图中的函数节点改造成封装的节点类，继承自 BaseNode。
实现统一的节点架构。

支持的子图节点：
1. Analysis Subgraph 节点
2. Concept Subgraph 节点
3. Detailed Plan Subgraph 节点
"""

from typing import Dict, Any, List
from .base_node import BaseNode
from ..core.state_builder import StateBuilder
from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# Analysis Subgraph 节点
# ==========================================

class InitializeAnalysisNode(BaseNode):
    """现状分析初始化节点"""

    def __init__(self):
        super().__init__("现状分析初始化")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """初始化现状分析，准备维度分析任务"""
        from ..subgraphs.analysis_prompts import list_dimensions

        dimensions = [d["key"] for d in list_dimensions()]

        return StateBuilder()\
            .set("subjects", dimensions)\
            .set("analyses", [])\
            .add_message(f"开始现状分析，共 {len(dimensions)} 个维度")\
            .build()


class AnalyzeDimensionNode(BaseNode):
    """维度分析节点"""

    def __init__(self):
        super().__init__("维度分析")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个维度的现状分析"""
        dimension_key = state.get("dimension_key")
        dimension_name = state.get("dimension_name", dimension_key)
        raw_data = state.get("raw_data", "")

        if not dimension_key:
            return {"error": "缺少维度信息"}

        logger.info(f"[子图-分析] 开始执行 {dimension_name} ({dimension_key})")

        try:
            # 使用 GenericPlannerFactory 创建规划器
            from ..planners.generic_planner import GenericPlannerFactory
            planner = GenericPlannerFactory.create_planner(dimension_key)

            # 调用规划器的 execute 方法
            planner_state = {"raw_data": raw_data, "village_data": raw_data}
            planner_result = planner.execute(planner_state)

            # 使用动态结果键名
            result_key = planner.get_result_key()
            analysis_text = planner_result.get(result_key, "")
            logger.info(f"[子图-分析] 完成 {dimension_name}，生成 {len(analysis_text)} 字符")

            # 返回结果（包装在列表中以支持 operator.add 累加）
            return {
                "analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "analysis_result": analysis_text
                }]
            }

        except Exception as e:
            logger.error(f"[子图-分析] {dimension_name} 执行失败: {str(e)}")
            # 返回错误信息而非崩溃
            return {
                "analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "analysis_result": f"[分析失败] {str(e)}"
                }]
            }


class ReduceAnalysesNode(BaseNode):
    """汇总分析结果节点"""

    def __init__(self):
        super().__init__("汇总分析结果")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """汇总所有维度的分析结果"""
        analyses = state.get("analyses", [])

        logger.info(f"[子图-Reduce] 汇总 {len(analyses)} 个维度的分析结果")

        # 整理分析结果为结构化格式
        dimension_reports_dict = {}
        dimension_reports_text = []

        for analysis in analyses:
            dimension_key = analysis['dimension_key']
            dimension_name = analysis['dimension_name']
            analysis_text = analysis['analysis_result']

            # 保存独立的维度报告（用于部分传输）
            dimension_reports_dict[dimension_key] = analysis_text

            # 同时拼接用于综合报告
            dimension_reports_text.append(f"""
## {dimension_name}

{analysis_text}
---
""")

        logger.info(f"[子图-Reduce] 汇总完成，生成了 {len(dimension_reports_dict)} 个维度报告")
        return {
            "analysis_reports": dimension_reports_dict,  # 统一命名
            "dimension_reports_text": "\n".join(dimension_reports_text)
        }


class GenerateAnalysisReportNode(BaseNode):
    """生成现状分析报告节点"""

    def __init__(self):
        super().__init__("生成现状分析报告")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成综合现状分析报告"""
        from ..core.llm_factory import create_llm
        from ..core.config import LLM_MODEL, MAX_TOKENS
        from ..subgraphs.analysis_prompts import ANALYSIS_SUMMARY_PROMPT
        from langchain_core.messages import HumanMessage, AIMessage
        from datetime import datetime

        logger.info("[子图-汇总] 开始生成最终综合报告")

        try:
            # 使用 reduce 阶段生成的 dimension_reports_text
            dimension_reports_text = state.get("dimension_reports_text", "")

            # 如果 dimension_reports_text 为空，从 analyses 重新构建
            if not dimension_reports_text:
                for analysis in state.get("analyses", []):
                    dimension_reports_text += f"\n### {analysis['dimension_name']}\n{analysis['analysis_result']}\n"

            # 构建汇总 Prompt
            summary_prompt = ANALYSIS_SUMMARY_PROMPT.format(
                dimension_reports=dimension_reports_text
            )

            # 调用 LLM 生成最终报告
            llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
            response = llm.invoke([HumanMessage(content=summary_prompt)])

            final_report = f"""# {state.get('project_name', '村庄')}现状综合分析报告

{response.content}
"""

            logger.info(f"[子图-汇总] 最终报告生成完成，共 {len(final_report)} 字符")

            return {
                "final_report": final_report,
                "messages": [AIMessage(content=final_report)]
            }

        except Exception as e:
            logger.error(f"[子图-汇总] 报告生成失败: {str(e)}")

            # 降级方案：直接拼接各维度结果
            fallback_report = f"""# {state.get('project_name', '村庄')}现状分析报告（简化版）

## 各维度分析

"""
            for analysis in state.get("analyses", []):
                fallback_report += f"### {analysis['dimension_name']}\n\n{analysis['analysis_result']}\n\n"

            return {
                "final_report": fallback_report,
                "messages": [AIMessage(content=fallback_report)]
            }


# ==========================================
# Concept Subgraph 节点
# ==========================================

class InitializeConceptNode(BaseNode):
    """规划思路初始化节点"""

    def __init__(self):
        super().__init__("规划思路初始化")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """初始化规划思路，准备维度分析任务和波次路由状态"""
        from ..config.dimension_metadata import list_dimensions

        dimensions = [d["key"] for d in list_dimensions(layer=2)]

        # 波次路由状态初始化
        return StateBuilder()\
            .set("dimensions", dimensions)\
            .set("concept_analyses", [])\
            .set("current_wave", 1)\
            .set("total_waves", 4)\
            .set("completed_dimensions", [])\
            .set("concept_reports", {})\
            .add_message(f"开始规划思路分析，共 {len(dimensions)} 个维度，4 个波次")\
            .build()


class AnalyzeConceptDimensionNode(BaseNode):
    """规划思路维度分析节点"""

    def __init__(self):
        super().__init__("规划思路维度分析")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个维度的规划思路分析，使用预筛选的数据"""
        dimension_key = state.get("dimension_key")
        dimension_name = state.get("dimension_name", dimension_key)

        if not dimension_key:
            return {"error": "缺少维度信息"}

        logger.info(f"[子图-规划思路] 开始执行 {dimension_name} ({dimension_key})")
        logger.info(f"[子图-规划思路] {dimension_name} 输入数据: "
                   f"filtered_analysis={len(state.get('filtered_analysis', ''))}字符, "
                   f"filtered_concept={len(state.get('filtered_concept', ''))}字符")

        try:
            # 使用 GenericPlannerFactory 创建规划器
            from ..planners.generic_planner import GenericPlannerFactory
            planner = GenericPlannerFactory.create_planner(dimension_key)

            # 调用规划器的 execute 方法
            # 使用预筛选的 filtered_analysis 和 filtered_concept 字段
            planner_state = {
                "filtered_analysis": state.get("filtered_analysis", ""),  # 预筛选的现状分析
                "filtered_concept": state.get("filtered_concept", ""),    # 前序 Layer 2 报告
                "project_name": state.get("project_name", "村庄"),
                "task_description": state.get("task_description", "制定规划思路"),
                "constraints": state.get("constraints", "无特殊约束")
            }
            planner_result = planner.execute(planner_state)

            # 使用动态结果键名
            result_key = planner.get_result_key()
            concept_text = planner_result.get(result_key, "")
            logger.info(f"[子图-规划思路] 完成 {dimension_name}，生成 {len(concept_text)} 字符")

            # 返回结果（包装在列表中以支持 operator.add 累加）
            return {
                "concept_analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "concept_result": concept_text
                }]
            }

        except Exception as e:
            logger.error(f"[子图-规划思路] {dimension_name} 执行失败: {str(e)}")
            return {
                "concept_analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "concept_result": f"[分析失败] {str(e)}"
                }]
            }


class ReduceConceptsNode(BaseNode):
    """汇总规划思路结果节点"""

    def __init__(self):
        super().__init__("汇总规划思路结果")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """汇总所有维度的规划思路结果，更新 completed_dimensions 用于波次路由"""
        concept_analyses = state.get("concept_analyses", [])
        completed_dims = list(state.get("completed_dimensions", []))  # 获取已完成维度

        logger.info(f"[子图-规划思路-Reduce] 汇总 {len(concept_analyses)} 个维度的结果")

        # 整理结果为结构化格式
        concept_reports_dict = dict(state.get("concept_reports", {}))  # 保留已有报告
        concept_reports_text = []

        for analysis in concept_analyses:
            dimension_key = analysis['dimension_key']
            dimension_name = analysis['dimension_name']
            concept_text = analysis['concept_result']

            concept_reports_dict[dimension_key] = concept_text
            concept_reports_text.append(f"""
## {dimension_name}

{concept_text}
---
""")
            # 记录已完成维度
            if dimension_key not in completed_dims:
                completed_dims.append(dimension_key)

        logger.info(f"[子图-规划思路-Reduce] 已完成维度: {completed_dims}")

        return {
            "concept_reports": concept_reports_dict,  # 统一命名
            "concept_reports_text": "\n".join(concept_reports_text),
            "completed_dimensions": completed_dims  # 更新已完成维度列表
        }


class GenerateConceptReportNode(BaseNode):
    """生成规划思路报告节点"""

    def __init__(self):
        super().__init__("生成规划思路报告")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成综合规划思路报告"""
        from ..core.llm_factory import create_llm
        from ..core.config import LLM_MODEL, MAX_TOKENS
        from ..subgraphs.concept_prompts import CONCEPT_SUMMARY_PROMPT
        from langchain_core.messages import HumanMessage, AIMessage

        logger.info("[子图-规划思路-汇总] 开始生成最终报告")

        try:
            concept_reports_text = state.get("concept_reports_text", "")

            # 构建汇总 Prompt
            summary_prompt = CONCEPT_SUMMARY_PROMPT.format(
                project_name=state.get("project_name", "村庄"),
                concept_reports=concept_reports_text
            )

            llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
            response = llm.invoke([HumanMessage(content=summary_prompt)])

            final_report = f"""# {state.get('project_name', '村庄')}规划思路报告

{response.content}
"""

            logger.info(f"[子图-规划思路-汇总] 报告生成完成，共 {len(final_report)} 字符")

            return {
                "final_concept_report": final_report,
                "messages": [AIMessage(content=final_report)]
            }

        except Exception as e:
            logger.error(f"[子图-规划思路-汇总] 报告生成失败: {str(e)}")

            fallback_report = f"# {state.get('project_name', '村庄')}规划思路（简化版）\n\n"
            for analysis in state.get("concept_analyses", []):
                fallback_report += f"## {analysis['dimension_name']}\n\n{analysis['concept_result']}\n\n"

            return {
                "final_concept_report": fallback_report,
                "messages": [AIMessage(content=fallback_report)]
            }


# ==========================================
# Detailed Plan Subgraph 节点
# ==========================================

class InitializeDetailedPlanningNode(BaseNode):
    """详细规划初始化节点"""

    def __init__(self):
        super().__init__("详细规划初始化")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """初始化详细规划流程，设置待规划的维度列表和波次信息"""
        from ..subgraphs.detailed_plan_subgraph import ALL_DIMENSIONS, TOTAL_WAVES

        required = state.get("required_dimensions", ALL_DIMENSIONS)

        return StateBuilder()\
            .set("required_dimensions", required)\
            .set("completed_dimensions", [])\
            .set("dimension_plans", [])\
            .set("current_wave", 1)\
            .set("total_waves", TOTAL_WAVES)\
            .set("completed_dimension_reports", {})\
            .set("token_usage_stats", {})\
            .add_message(f"开始详细规划，共 {len(required)} 个维度")\
            .build()


class GenerateDimensionPlanNode(BaseNode):
    """生成维度详细规划节点"""

    def __init__(self):
        super().__init__("生成维度详细规划")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成单个维度的详细规划"""
        from ..subgraphs.detailed_plan_subgraph import generate_dimension_plan as _generate
        from datetime import datetime

        dimension_key = state["dimension_key"]
        dimension_name = state["dimension_name"]
        project_name = state["project_name"]

        logger.info(f"[子图-L3-Agent] 开始生成 {dimension_name} ({dimension_key})")

        try:
            # 使用子图中的原始函数来执行（保持一致性）
            result = _generate(state)

            # 如果结果包含 dimension_plans，添加元数据
            if "dimension_plans" in result and result["dimension_plans"]:
                plan = result["dimension_plans"][0]
                plan_content = plan["dimension_result"]

                # 添加元数据
                plan_with_metadata = f"""# {project_name} - {dimension_name}

{plan_content}

---
**编制**: {dimension_name}专业Agent
**编制时间**: {datetime.now().strftime('%Y-%m-%d %H:%M')}
"""

                result["dimension_plans"][0]["dimension_result"] = plan_with_metadata

            return result

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


class ReduceDimensionReportsNode(BaseNode):
    """汇总详细规划报告节点"""

    def __init__(self):
        super().__init__("汇总详细规划报告")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """汇总所有维度的详细规划报告"""
        from ..subgraphs.detailed_plan_subgraph import reduce_dimension_plans as _reduce

        return _reduce(state)


class CheckAllDimensionsCompleteNode(BaseNode):
    """检查所有维度完成节点"""

    def __init__(self):
        super().__init__("检查维度完成状态")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """检查当前波次是否完成"""
        from ..subgraphs.detailed_plan_subgraph import (
            ALL_DIMENSIONS, check_all_dimensions_complete as _check
        )

        return {}  # 此节点仅用于路由，不修改状态


class GenerateFinalDetailedPlanNode(BaseNode):
    """生成最终详细规划报告节点"""

    def __init__(self):
        super().__init__("生成最终详细规划报告")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """生成最终详细规划报告"""
        from ..subgraphs.detailed_plan_subgraph import generate_final_detailed_plan as _generate

        return _generate(state)


# ==========================================
# 导出所有节点类
# ==========================================

__all__ = [
    # Analysis Subgraph Nodes
    "InitializeAnalysisNode",
    "AnalyzeDimensionNode",
    "ReduceAnalysesNode",
    "GenerateAnalysisReportNode",

    # Concept Subgraph Nodes
    "InitializeConceptNode",
    "AnalyzeConceptDimensionNode",
    "ReduceConceptsNode",
    "GenerateConceptReportNode",

    # Detailed Plan Subgraph Nodes
    "InitializeDetailedPlanningNode",
    "GenerateDimensionPlanNode",
    "ReduceDimensionReportsNode",
    "CheckAllDimensionsCompleteNode",
    "GenerateFinalDetailedPlanNode",
]
