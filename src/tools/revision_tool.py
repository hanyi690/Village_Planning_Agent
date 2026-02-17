"""
修复工具 - 基于反馈的规划修复工具

管理基于人工反馈的修复流程：
1. 解析人工反馈，识别需要修复的维度
2. 用户确认修复范围（通过interactive_tool）
3. 调用相应skill执行修复

遵循tool pattern：所有方法返回结构化Dict结果。
"""

import re
from typing import Dict, List, Any, Optional

from ..utils.logger import get_logger

logger = get_logger(__name__)


# ==========================================
# 修复工具类
# ==========================================

class RevisionTool:
    """
    修复工具

    处理人工审查驳回后的修复流程，遵循tool pattern。
    UI交互功能已移到interactive_tool。
    """

    # 维度关键词映射（用于从反馈中识别需要修复的维度）
    DIMENSION_KEYWORDS = {
        "industry": ["产业", "经济", "农业", "工业", "旅游", "收入", "gdp"],
        "master_plan": ["总体规划", "空间布局", "用地", "村庄布局", "总规"],
        "traffic": ["交通", "道路", "运输", "出行", "路网", "停车"],
        "public_service": ["公共服务", "教育", "医疗", "卫生", "养老", "文化", "体育"],
        "infrastructure": ["基础设施", "水电", "给排水", "电力", "通信", "管网"],
        "ecological": ["生态", "环境", "绿地", "绿化", "环保", "污染", "景观"],
        "disaster_prevention": ["防灾", "减灾", "安全", "消防", "防洪", "地震"],
        "heritage": ["历史", "文化", "文物", "保护", "古迹", "传统"],
        "landscape": ["风貌", "建筑", "风格", "外观", "色彩", "高度"],
        "project_bank": ["项目", "建设", "工程", "投资", "实施", "计划"]
    }

    def __init__(self):
        """初始化RevisionTool"""
        self.revision_history: List[Dict[str, Any]] = []

    def parse_feedback(self, feedback: str) -> Dict[str, Any]:
        """
        解析人工反馈，智能识别需要修复的维度

        Args:
            feedback: 人工反馈文本

        Returns:
            结构化结果字典 {
                "success": bool,
                "dimensions": list,
                "error": str
            }
        """
        try:
            logger.info(f"[RevisionTool] 解析反馈: {feedback[:100]}...")

            identified_dimensions = []

            # 将反馈转为小写进行匹配
            feedback_lower = feedback.lower()

            # 检查每个维度的关键词
            for dimension, keywords in self.DIMENSION_KEYWORDS.items():
                for keyword in keywords:
                    if keyword in feedback_lower:
                        if dimension not in identified_dimensions:
                            identified_dimensions.append(dimension)
                        break

            logger.info(f"[RevisionTool] 识别到需要修复的维度: {identified_dimensions}")

            return {
                "success": True,
                "dimensions": identified_dimensions,
                "error": ""
            }

        except Exception as e:
            logger.error(f"[RevisionTool] 解析反馈时出错: {e}")
            return {
                "success": False,
                "dimensions": [],
                "error": str(e)
            }

    def get_dimension_names(self) -> Dict[str, str]:
        """
        获取维度名称映射

        Returns:
            维度ID到名称的映射字典
        """
        return {
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

    def revise_dimension(
        self,
        dimension: str,
        state: Dict[str, Any],
        feedback: str,
        original_result: str,
        revision_count: int = 0
    ) -> Dict[str, Any]:
        """
        修复指定维度

        Args:
            dimension: 维度标识
            state: 当前状态
            feedback: 人工反馈
            original_result: 原始结果
            revision_count: 修复次数

        Returns:
            结构化结果字典 {
                "success": bool,
                "revised_result": str,
                "metadata": dict,
                "error": str
            }
        """
        try:
            logger.info(f"[RevisionTool] 开始修复维度: {dimension} (第{revision_count + 1}次)")

            # 使用 GenericPlannerFactory 进行修复（统一架构）
            from ..planners.generic_planner import GenericPlannerFactory
            planner = GenericPlannerFactory.create_planner(dimension)

            revised_result = planner.execute_with_feedback(
                state=state,
                feedback=feedback,
                original_result=original_result,
                revision_count=revision_count
            )

            logger.info(f"[RevisionTool] 维度 {dimension} 修复完成，内容长度: {len(revised_result)}")

            # 记录修复历史
            self.revision_history.append({
                "dimension": dimension,
                "revision_count": revision_count + 1,
                "feedback": feedback,
                "original_length": len(original_result),
                "revised_length": len(revised_result)
            })

            return {
                "success": True,
                "revised_result": revised_result,
                "metadata": {
                    "dimension": dimension,
                    "revision_count": revision_count + 1,
                    "original_length": len(original_result),
                    "revised_length": len(revised_result)
                },
                "error": ""
            }

        except Exception as e:
            logger.error(f"[RevisionTool] 修复维度 {dimension} 失败: {e}")
            return {
                "success": False,
                "revised_result": original_result,  # 失败时返回原始结果
                "metadata": {},
                "error": str(e)
            }

    def revise_multiple(
        self,
        dimensions: List[str],
        state: Dict[str, Any],
        feedback: str
    ) -> Dict[str, Any]:
        """
        修复多个维度

        Args:
            dimensions: 需要修复的维度列表
            state: 当前状态
            feedback: 人工反馈

        Returns:
            结构化结果字典 {
                "success": bool,
                "revised_results": dict,  # {dimension: revised_result}
                "failed_dimensions": list,
                "error": str
            }
        """
        try:
            revised_results = {}
            failed_dimensions = []

            for dimension in dimensions:
                # 获取原始结果
                original_result = self._get_dimension_result(dimension, state)

                if original_result:
                    # 执行修复
                    result = self.revise_dimension(
                        dimension=dimension,
                        state=state,
                        feedback=feedback,
                        original_result=original_result,
                        revision_count=0
                    )

                    if result["success"]:
                        revised_results[dimension] = result["revised_result"]
                    else:
                        failed_dimensions.append(dimension)
                        logger.warning(f"[RevisionTool] 维度 {dimension} 修复失败: {result['error']}")
                else:
                    failed_dimensions.append(dimension)
                    logger.warning(f"[RevisionTool] 维度 {dimension} 没有找到原始结果")

            return {
                "success": len(revised_results) > 0,
                "revised_results": revised_results,
                "failed_dimensions": failed_dimensions,
                "error": "" if revised_results else "所有维度修复失败"
            }

        except Exception as e:
            logger.error(f"[RevisionTool] 批量修复时出错: {e}")
            return {
                "success": False,
                "revised_results": {},
                "failed_dimensions": dimensions,
                "error": str(e)
            }

    def get_dimension_result(
        self,
        dimension: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        从状态中获取指定维度的原始结果

        Args:
            dimension: 维度标识
            state: 当前状态

        Returns:
            结构化结果字典 {
                "success": bool,
                "result": str,
                "error": str
            }
        """
        try:
            detailed_dimension_reports = state.get("detailed_dimension_reports", {})

            # 维度键名映射
            dimension_key_map = {
                "industry": "dimension_industry",
                "master_plan": "dimension_master_plan",
                "traffic": "dimension_traffic",
                "public_service": "dimension_public_service",
                "infrastructure": "dimension_infrastructure",
                "ecological": "dimension_ecological",
                "disaster_prevention": "dimension_disaster_prevention",
                "heritage": "dimension_heritage",
                "landscape": "dimension_landscape",
                "project_bank": "dimension_project_bank"
            }

            key = dimension_key_map.get(dimension)
            if key:
                result = detailed_dimension_reports.get(key, "")
                return {
                    "success": True,
                    "result": result,
                    "error": ""
                }

            return {
                "success": False,
                "result": "",
                "error": f"未知维度: {dimension}"
            }

        except Exception as e:
            logger.error(f"[RevisionTool] 获取维度结果时出错: {e}")
            return {
                "success": False,
                "result": "",
                "error": str(e)
            }

    def get_revision_history(self) -> Dict[str, Any]:
        """
        获取修复历史

        Returns:
            结构化结果字典 {
                "success": bool,
                "history": list,
                "count": int,
                "error": str
            }
        """
        return {
            "success": True,
            "history": self.revision_history.copy(),
            "count": len(self.revision_history),
            "error": ""
        }

    def _get_dimension_result(self, dimension: str, state: Dict[str, Any]) -> Optional[str]:
        """内部方法：从状态中获取指定维度的原始结果（简化版本）"""
        result = self.get_dimension_result(dimension, state)
        return result["result"] if result["success"] else None


# ==========================================
# 便捷函数
# ==========================================

def parse_feedback(feedback: str) -> List[str]:
    """
    便捷函数：解析反馈并识别需要修复的维度

    Args:
        feedback: 人工反馈文本

    Returns:
        需要修复的维度列表
    """
    tool = RevisionTool()
    result = tool.parse_feedback(feedback)
    return result["dimensions"] if result["success"] else []


def revise_dimension(
    dimension: str,
    state: Dict[str, Any],
    feedback: str,
    original_result: str
) -> str:
    """
    便捷函数：修复单个维度

    Args:
        dimension: 维度标识
        state: 当前状态
        feedback: 人工反馈
        original_result: 原始结果

    Returns:
        修复后的结果，失败时返回原始结果
    """
    tool = RevisionTool()
    result = tool.revise_dimension(dimension, state, feedback, original_result)
    return result["revised_result"] if result["success"] else original_result


def revise_dimensions(
    dimensions: List[str],
    state: Dict[str, Any],
    feedback: str
) -> Dict[str, str]:
    """
    便捷函数：修复多个维度

    Args:
        dimensions: 需要修复的维度列表
        state: 当前状态
        feedback: 人工反馈

    Returns:
        修复后的维度结果字典 {dimension: revised_result}
    """
    tool = RevisionTool()
    result = tool.revise_multiple(dimensions, state, feedback)
    return result["revised_results"]


__all__ = [
    "RevisionTool",
    "parse_feedback",
    "revise_dimension",
    "revise_dimensions",
]
