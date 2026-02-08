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
from langchain_core.messages import BaseMessage, AIMessage, HumanMessage
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
    """维度分析节点（增强版：更好的错误处理和状态验证）"""

    def __init__(self):
        super().__init__("维度分析")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个维度的现状分析"""
        dimension_key = state.get("dimension_key")
        dimension_name = state.get("dimension_name", dimension_key)

        # 1. 状态验证
        if not dimension_key:
            logger.error(f"[{self.node_name}] 缺少维度信息")
            return {"error": "缺少维度信息: dimension_key"}

        raw_data = state.get("raw_data", "")
        if not raw_data:
            logger.warning(f"[{self.node_name}] {dimension_name} 未提供原始数据")
            return {
                "analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "analysis_result": "[分析失败] 未提供原始数据"
                }]
            }

        logger.info(f"[{self.node_name}] 开始执行 {dimension_name} ({dimension_key})")

        try:
            # 2. 创建规划器
            from ..planners.analysis_planners import AnalysisPlannerFactory
            planner = AnalysisPlannerFactory.create_planner(dimension_key)
            logger.debug(f"[{self.node_name}] 创建规划器: {planner}")

            # 3. 调用规划器
            planner_state = {
                "raw_data": raw_data,
                "project_name": state.get("project_name", "村庄")
            }
            planner_result = planner.execute(planner_state)

            # 4. 检查执行结果
            if not planner_result.get("success", True):
                error_msg = planner_result.get("error", "未知错误")
                logger.error(f"[{self.node_name}] {dimension_name} 规划器执行失败: {error_msg}")
                return {
                    "analyses": [{
                        "dimension_key": dimension_key,
                        "dimension_name": dimension_name,
                        "analysis_result": f"[分析失败] {error_msg}"
                    }]
                }

            analysis_text = planner_result["analysis_result"]
            logger.info(f"[{self.node_name}] {dimension_name} 完成，生成 {len(analysis_text)} 字符")

            # 5. 返回结果（包装在列表中以支持 operator.add 累加）
            return {
                "analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "analysis_result": analysis_text
                }]
            }

        except ValueError as e:
            # 规划器创建失败（维度不存在）
            logger.error(f"[{self.node_name}] {dimension_name} 规划器创建失败: {e}")
            return {
                "analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "analysis_result": f"[分析失败] 不支持的维度: {dimension_key}"
                }]
            }

        except Exception as e:
            # 其他未预期的错误
            logger.error(f"[{self.node_name}] {dimension_name} 执行失败: {str(e)}", exc_info=True)
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
        from ..utils.text_formatter import format_dimension_reports

        analyses = state.get("analyses", [])

        logger.info(f"[子图-Reduce] 汇总 {len(analyses)} 个维度的分析结果")

        # Use shared utility to format reports
        dimension_reports_dict, dimension_reports_text = format_dimension_reports(
            analyses,
            result_key="analysis_result"
        )

        logger.info(f"[子图-Reduce] 汇总完成，生成了 {len(dimension_reports_dict)} 个维度报告")
        return {
            "dimension_reports": dimension_reports_dict,
            "dimension_reports_text": dimension_reports_text
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
        """
        初始化规划思路，准备维度分析任务
        
        注意：必须确保返回的 Key 与 ConceptState 定义完全一致
        """
        from ..subgraphs.concept_prompts import list_concept_dimensions

        # 1. 动态获取维度列表，例如：['resource_endowment', 'planning_positioning', ...]
        dimensions = [d["key"] for d in list_concept_dimensions()]
        
        # 调试日志：确保这里拿到了数据
        logger.info(f"[{self.node_name}] 成功初始化维度列表: {dimensions}")

        # 2. 直接返回 Dict，不使用 StateBuilder 以避免嵌套结构导致的更新失效
        # LangGraph 会根据这些 Key 自动合并/覆盖 ConceptState 中的对应字段
        return {
            "dimensions": dimensions,
            "concept_analyses": [],  # 重置累加器
            "messages": [AIMessage(content=f"开始规划思路分析，共 {len(dimensions)} 个维度")]
        }


class AnalyzeConceptDimensionNode(BaseNode):
    """规划思路维度分析节点（增强版：更好的错误处理和状态验证）"""

    def __init__(self):
        super().__init__("规划思路维度分析")

    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """执行单个维度的规划思路分析"""
        dimension_key = state.get("dimension_key")
        dimension_name = state.get("dimension_name", dimension_key)

        # 1. 状态验证
        if not dimension_key:
            logger.error(f"[{self.node_name}] 缺少维度信息")
            return {"error": "缺少维度信息: dimension_key"}

        required_fields = ["analysis_report", "task_description", "constraints"]
        missing_fields = [f for f in required_fields if f not in state or not state[f]]
        if missing_fields:
            logger.warning(f"[{self.node_name}] {dimension_name} 缺少必需字段: {missing_fields}")

        logger.info(f"[{self.node_name}] 开始执行 {dimension_name} ({dimension_key})")

        try:
            # 2. 创建规划器
            from ..planners.concept_planners import ConceptPlannerFactory
            planner = ConceptPlannerFactory.create_planner(dimension_key)
            logger.debug(f"[{self.node_name}] 创建规划器: {planner}")

            # 3. 构建规划器状态
            planner_state = {
                "analysis_report": state.get("analysis_report", ""),
                "dimension_reports": state.get("dimension_reports", {}),
                "project_name": state.get("project_name", "村庄"),
                "task_description": state.get("task_description", "制定规划思路"),
                "constraints": state.get("constraints", "无特殊约束")
            }

            # 4. 调用规划器
            planner_result = planner.execute(planner_state)

            # 5. 检查执行结果
            if not planner_result.get("success", True):
                error_msg = planner_result.get("error", "未知错误")
                logger.error(f"[{self.node_name}] {dimension_name} 规划器执行失败: {error_msg}")
                return {
                    "concept_analyses": [{
                        "dimension_key": dimension_key,
                        "dimension_name": dimension_name,
                        "concept_result": f"[分析失败] {error_msg}"
                    }]
                }

            concept_text = planner_result["concept_result"]
            logger.info(f"[{self.node_name}] {dimension_name} 完成，生成 {len(concept_text)} 字符")

            # 6. 返回结果（包装在列表中以支持 operator.add 累加）
            return {
                "concept_analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "concept_result": concept_text
                }]
            }

        except ValueError as e:
            # 规划器创建失败（维度不存在）
            logger.error(f"[{self.node_name}] {dimension_name} 规划器创建失败: {e}")
            return {
                "concept_analyses": [{
                    "dimension_key": dimension_key,
                    "dimension_name": dimension_name,
                    "concept_result": f"[分析失败] 不支持的维度: {dimension_key}"
                }]
            }

        except Exception as e:
            # 其他未预期的错误
            logger.error(f"[{self.node_name}] {dimension_name} 执行失败: {str(e)}", exc_info=True)
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
        """汇总所有维度的规划思路结果"""
        from ..utils.text_formatter import format_dimension_reports

        concept_analyses = state.get("concept_analyses", [])

        logger.info(f"[子图-规划思路-Reduce] 汇总 {len(concept_analyses)} 个维度的结果")

        # Use shared utility to format reports
        concept_reports_dict, dimension_reports_text = format_dimension_reports(
            concept_analyses,
            result_key="concept_result"
        )

        return {
            "concept_dimension_reports": concept_reports_dict,
            "dimension_reports_text": dimension_reports_text,
            "final_concept": ""  # 清空，等待 generate 节点生成
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
            # 优先使用 reduce 节点生成的拼接文本
            dimension_reports_text = state.get("dimension_reports_text", "")

            # 如果为空（防御性编程），从 concept_analyses 恢复
            if not dimension_reports_text and state.get("concept_analyses"):
                logger.warning("[子图-L2-Generate] dimension_reports_text 为空，从 concept_analyses 恢复")
                summary_parts = []
                for analysis in state["concept_analyses"]:
                    concept_result = analysis.get("concept_result", "")
                    if concept_result:
                        summary_parts.append(f"\n### {analysis['dimension_name']}\n{concept_result}\n")
                dimension_reports_text = "\n".join(summary_parts)

            # 构建汇总 Prompt
            summary_prompt = CONCEPT_SUMMARY_PROMPT.format(
                project_name=state.get("project_name", "村庄"),
                task_description=state.get("task_description", "制定村庄规划思路"),
                dimension_reports=dimension_reports_text  # 修复：使用正确的参数名
            )

            llm = create_llm(model=LLM_MODEL, temperature=0.7, max_tokens=MAX_TOKENS)
            response = llm.invoke([HumanMessage(content=summary_prompt)])

            final_report = f"""# {state.get('project_name', '村庄')}规划思路报告

{response.content}
"""

            logger.info(f"[子图-规划思路-汇总] 报告生成完成，共 {len(final_report)} 字符")

            return {
                "final_concept": final_report,  # 修复：使用正确的字段名
                "messages": [AIMessage(content=final_report)]
            }

        except Exception as e:
            logger.error(f"[子图-规划思路-汇总] 报告生成失败: {str(e)}")

            fallback_report = f"# {state.get('project_name', '村庄')}规划思路（简化版）\n\n"
            for analysis in state.get("concept_analyses", []):
                fallback_report += f"## {analysis['dimension_name']}\n\n{analysis['concept_result']}\n\n"

            return {
                "final_concept": fallback_report,  # 修复：使用正确的字段名
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
    # 【已删除】ReduceAnalysesNode - 不再需要汇总节点
    # 【已删除】GenerateAnalysisReportNode - 不再需要生成综合报告

    # Concept Subgraph Nodes
    "InitializeConceptNode",
    "AnalyzeConceptDimensionNode",
    # 【已删除】ReduceConceptsNode - 不再需要汇总节点
    # 【已删除】GenerateConceptReportNode - 不再需要生成综合报告

    # Detailed Plan Subgraph Nodes
    "InitializeDetailedPlanningNode",
    "GenerateDimensionPlanNode",
    "ReduceDimensionReportsNode",
    "CheckAllDimensionsCompleteNode",
    # 【已删除】GenerateFinalDetailedPlanNode - 不再需要生成综合报告
]
