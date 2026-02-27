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
    # 与 dimension_metadata.py 和前端 dimensions.ts 保持一致
    DIMENSION_KEYWORDS = {
        # Layer 1: 现状分析 (12个)
        "location": ["区位", "对外交通", "地理位置", "交通区位", "区域关系"],
        "socio_economic": ["社会经济", "人口", "经济", "收入", "产业", "gdp"],
        "villager_wishes": ["村民意愿", "诉求", "愿望", "需求", "意见", "期望"],
        "superior_planning": ["上位规划", "政策导向", "规划衔接", "政策约束"],
        "natural_environment": ["自然环境", "地形", "地貌", "气候", "水文", "生态"],
        "land_use": ["土地利用", "用地现状", "土地结构", "用地分布"],
        "traffic": ["道路交通", "交通", "道路", "出行", "路网", "停车"],
        "public_services": ["公共服务", "教育", "医疗", "卫生", "养老", "文化", "体育"],
        "infrastructure": ["基础设施", "水电", "给排水", "电力", "通信", "环卫"],
        "ecological_green": ["生态绿地", "绿化", "生态环境", "绿地", "公园"],
        "architecture": ["建筑", "房屋", "建筑质量", "建筑风格", "建筑高度"],
        "historical_culture": ["历史文化", "文物", "古迹", "乡愁", "传统", "民俗", "文化遗产"],

        # Layer 2: 规划思路 (4个)
        "resource_endowment": ["资源禀赋", "资源条件", "优势资源", "资源"],
        "planning_positioning": ["规划定位", "发展定位", "目标定位", "定位"],
        "development_goals": ["发展目标", "规划目标", "建设目标", "目标"],
        "planning_strategies": ["规划策略", "发展策略", "实施策略", "策略"],

        # Layer 3: 详细规划 (12个)
        "industry": ["产业规划", "产业发展", "农业", "工业", "旅游", "产业布局"],
        "spatial_structure": ["空间结构", "空间布局", "功能分区", "空间组织"],
        "land_use_planning": ["土地利用规划", "三区三线", "全域土地治理", "用地规划", "土地整治", "建设用地"],
        "settlement_planning": ["居民点规划", "村庄布局", "聚落", "宅基地"],
        "traffic_planning": ["道路交通规划", "综合交通", "道路规划", "路网规划"],
        "public_service": ["公共服务设施规划", "公服设施", "服务设施"],
        "infrastructure_planning": ["基础设施规划", "市政设施", "市政规划"],
        "ecological": ["生态绿地规划", "生态保护", "绿地系统", "生态空间"],
        "disaster_prevention": ["防灾减灾", "防震", "消防", "防洪", "减灾", "安全"],
        "heritage": ["历史文保", "文物保护", "文化遗产", "历史保护"],
        "landscape": ["村庄风貌", "风貌指引", "建筑风貌", "风貌控制"],
        "project_bank": ["建设项目库", "项目清单", "工程", "投资项目"]
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
            # Layer 1: 现状分析
            "location": "区位与对外交通分析",
            "socio_economic": "社会经济分析",
            "villager_wishes": "村民意愿与诉求分析",
            "superior_planning": "上位规划与政策导向分析",
            "natural_environment": "自然环境分析",
            "land_use": "土地利用分析",
            "traffic": "道路交通分析",
            "public_services": "公共服务设施分析",
            "infrastructure": "基础设施分析",
            "ecological_green": "生态绿地分析",
            "architecture": "建筑分析",
            "historical_culture": "历史文化与乡愁保护分析",

            # Layer 2: 规划思路
            "resource_endowment": "资源禀赋分析",
            "planning_positioning": "规划定位分析",
            "development_goals": "发展目标分析",
            "planning_strategies": "规划策略分析",

            # Layer 3: 详细规划
            "industry": "产业规划",
            "spatial_structure": "空间结构规划",
            "land_use_planning": "土地利用规划",
            "settlement_planning": "居民点规划",
            "traffic_planning": "道路交通规划",
            "public_service": "公共服务设施规划",
            "infrastructure_planning": "基础设施规划",
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

        会自动过滤掉尚未生成的维度。

        Args:
            dimensions: 需要修复的维度列表
            state: 当前状态
            feedback: 人工反馈

        Returns:
            结构化结果字典 {
                "success": bool,
                "revised_results": dict,  # {dimension: revised_result}
                "failed_dimensions": list,
                "skipped_dimensions": list,  # 尚未生成的维度
                "error": str
            }
        """
        try:
            # 1. 验证维度存在性（进度检查）
            validation = self._validate_dimensions(dimensions, state)
            valid_dimensions = validation["valid_dimensions"]
            skipped_dimensions = validation["invalid_dimensions"]

            if validation["skipped_info"]:
                logger.info(f"[RevisionTool] {validation['skipped_info']}")

            if not valid_dimensions:
                return {
                    "success": False,
                    "revised_results": {},
                    "failed_dimensions": [],
                    "skipped_dimensions": skipped_dimensions,
                    "error": "没有可修复的有效维度（所有维度尚未生成）"
                }

            # 2. 对有效维度执行修复
            revised_results = {}
            failed_dimensions = []

            for dimension in valid_dimensions:
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
                "skipped_dimensions": skipped_dimensions,
                "original_results": {dim: self._get_dimension_result(dim, state) 
                                    for dim in revised_results.keys()},
                "error": "" if revised_results else "所有维度修复失败"
            }

        except Exception as e:
            logger.error(f"[RevisionTool] 批量修复时出错: {e}")
            return {
                "success": False,
                "revised_results": {},
                "failed_dimensions": dimensions,
                "skipped_dimensions": [],
                "error": str(e)
            }

    def get_dimension_result(
        self,
        dimension: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        从状态中获取指定维度的原始结果

        根据维度所属层级自动选择正确的数据源：
        - Layer 1: analysis_reports
        - Layer 2: concept_reports
        - Layer 3: detail_reports

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
            # 根据维度所属层级选择数据源（使用 dimension_metadata.py）
            from ..config.dimension_metadata import get_dimension_layer
            
            layer = get_dimension_layer(dimension)
            
            if layer == 1:
                reports = state.get("analysis_reports", {})
                source_name = "analysis_reports"
            elif layer == 2:
                reports = state.get("concept_reports", {})
                source_name = "concept_reports"
            else:  # layer == 3 或 None（默认 Layer 3）
                reports = state.get("detail_reports", {})
                source_name = "detail_reports"
            
            # 调试日志：显示状态中的字段和内容
            logger.info(f"[RevisionTool] get_dimension_result 调用:")
            logger.info(f"  - 目标维度: {dimension}")
            logger.info(f"  - 维度层级: {layer}")
            logger.info(f"  - 数据源: {source_name}")
            logger.info(f"  - {source_name} 键列表: {list(reports.keys())}")
            
            # 直接使用维度名作为键（不需要映射）
            result = reports.get(dimension, "")
            
            if result:
                logger.info(f"  - 找到维度 {dimension}，内容长度: {len(result)}")
                return {
                    "success": True,
                    "result": result,
                    "error": ""
                }

            logger.warning(f"  - 维度 {dimension} 未找到")
            return {
                "success": False,
                "result": "",
                "error": f"维度 {dimension} 尚未生成"
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

    def _validate_dimensions(
        self,
        dimensions: List[str],
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        验证维度是否已生成（进度检查）

        过滤掉尚未生成的维度，避免尝试修复不存在的维度。

        Args:
            dimensions: 待验证的维度列表
            state: 当前状态

        Returns:
            {
                "valid_dimensions": [...],  # 已生成可修复的维度
                "invalid_dimensions": [...],  # 尚未生成的维度
                "skipped_info": str  # 跳过原因说明
            }
        """
        valid_dimensions = []
        invalid_dimensions = []

        for dim in dimensions:
            result = self._get_dimension_result(dim, state)
            if result:
                valid_dimensions.append(dim)
            else:
                invalid_dimensions.append(dim)
                logger.warning(f"[RevisionTool] 维度 {dim} 尚未生成，跳过修复")

        skipped_info = ""
        if invalid_dimensions:
            skipped_info = f"跳过未生成的维度: {', '.join(invalid_dimensions)}"

        return {
            "valid_dimensions": valid_dimensions,
            "invalid_dimensions": invalid_dimensions,
            "skipped_info": skipped_info
        }

    def generate_change_summary(
        self,
        original: str,
        revised: str,
        target_dimension: str
    ) -> str:
        """
        生成精简的变更摘要，用于触发依赖维度更新

        使用 LLM 分析变更，生成简洁的摘要，作为下游维度的修复 feedback。

        Args:
            original: 原始内容
            revised: 修复后的内容
            target_dimension: 目标维度（用于上下文）

        Returns:
            变更摘要文本
        """
        try:
            from ..planners.generic_planner import GenericPlannerFactory
            from ..core.llm_factory import get_llm

            # 获取 LLM 实例
            llm = get_llm()

            # 构建变更摘要 prompt
            prompt = f"""分析以下规划内容的变更，生成一个精简的变更摘要（不超过150字）。

【原内容摘要】
{original[:1000]}

【新内容摘要】
{revised[:1000]}

【变更将影响的维度】
{target_dimension}

【要求】
1. 只描述关键数据变化（如数字、指标、位置等）
2. 突出对下游规划有影响的内容
3. 格式简洁，便于作为修改意见使用
4. 不要重复原文，只总结变化点

变更摘要："""

            response = llm.invoke(prompt)
            summary = response.content.strip() if hasattr(response, 'content') else str(response).strip()

            logger.info(f"[RevisionTool] 生成变更摘要: {summary[:100]}...")
            return summary

        except Exception as e:
            logger.error(f"[RevisionTool] 生成变更摘要失败: {e}")
            # 失败时返回简单摘要
            return f"内容已更新，请根据新的上游数据进行调整。"


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
