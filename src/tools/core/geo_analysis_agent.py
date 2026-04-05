"""地理分析 LLM 动态代理

基于 LLM 动态生成 GIS 分析脚本，支持复杂地理问题的智能分析。
"""

from typing import Dict, Any, Optional, List
from ...utils.logger import get_logger

logger = get_logger(__name__)


class GeoAnalysisAgent:
    """地理分析 LLM 代理"""

    def __init__(self, llm_client: Optional[Any] = None):
        """
        Args:
            llm_client: LLM 客户端（如 Anthropic Claude）
        """
        self.llm_client = llm_client

    def generate_analysis_script(
        self,
        analysis_request: str,
        available_data: Dict[str, Any],
        context: Optional[str] = None
    ) -> str:
        """生成分析脚本

        Args:
            analysis_request: 分析需求描述
            available_data: 可用数据类型和范围
            context: 额外上下文信息

        Returns:
            生成的 Python 分析脚本
        """
        if not self.llm_client:
            return self._generate_template_script(analysis_request, available_data)

        prompt = self._build_analysis_prompt(analysis_request, available_data, context)

        try:
            response = self.llm_client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=4096,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"[GeoAnalysisAgent] LLM 调用失败: {e}")
            return self._generate_template_script(analysis_request, available_data)

    def _build_analysis_prompt(
        self,
        request: str,
        data: Dict[str, Any],
        context: Optional[str]
    ) -> str:
        """构建分析提示词"""
        prompt_parts = [
            "请根据以下需求生成一个 Python GIS 分析脚本。",
            f"\n分析需求: {request}",
            f"\n可用数据类型: {self._describe_available_data(data)}"
        ]

        if context:
            prompt_parts.append(f"\n额外上下文: {context}")

        prompt_parts.extend([
            "\n要求:",
            "- 使用 geopandas 进行空间分析",
            "- 代码应包含完整的函数定义和文档字符串",
            "- 输出格式应返回 Dict[str, Any] 包含 success 和 data 字段",
            "- 不要硬编码数值，使用参数化设计"
        ])

        return "\n".join(prompt_parts)

    def _describe_available_data(self, data: Dict[str, Any]) -> str:
        """描述可用数据"""
        descriptions = []

        if "water" in data:
            descriptions.append("水系数据 (HYDA/HYDL/HYDP)")
        if "road" in data:
            descriptions.append("道路数据 (LRRL/LRDL)")
        if "residential" in data:
            descriptions.append("居民地数据 (RESA/RESP)")
        if "boundary" in data:
            descriptions.append("行政边界 GeoJSON")

        return ", ".join(descriptions) if descriptions else "无数据"

    def _generate_template_script(
        self,
        request: str,
        data: Dict[str, Any]
    ) -> str:
        """生成模板脚本（无 LLM 时使用）"""
        return '''
def run_dynamic_analysis(
    geo_data: Dict[str, Any],
    analysis_params: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    动态地理分析
    Request: {request}
    Available data: {data_desc}
    """
    try:
        import geopandas as gpd

        # 参数初始化
        params = analysis_params or {}

        # 分析逻辑待 LLM 生成
        result = {{
            "success": True,
            "data": {{
                "analysis_type": "dynamic_analysis",
                "request": "{request}",
                "status": "pending_llm_generation",
                "note": "此脚本为模板，需通过 LLM 生成具体分析逻辑"
            }}
        }}
        return result
    except Exception as e:
        return {{\"success\": False, \"error\": str(e)}}
'''.format(request=request, data_desc=self._describe_available_data(data))

    def interpret_analysis_result(
        self,
        result: Dict[str, Any],
        question: str
    ) -> str:
        """解释分析结果

        Args:
            result: 分析结果
            question: 用户问题

        Returns:
            自然语言解释
        """
        if not result.get("success"):
            return f"分析失败: {result.get('error', '未知错误')}"

        data = result.get("data", {})

        # 基础解释逻辑
        interpretation_parts = [f"基于 '{question}' 的分析结果："]

        if "water_systems" in data:
            water_count = len(data["water_systems"])
            interpretation_parts.append(f"- 发现 {water_count} 个水系要素")

        if "flood_risk_areas" in data:
            flood_count = len(data["flood_risk_areas"])
            total_area = sum(
                f.get("risk_area_km2", 0)
                for f in data["flood_risk_areas"]
            )
            interpretation_parts.append(
                f"- 计算得 {flood_count} 个潜在洪水风险区，总面积约 {total_area:.2f} km²"
            )

        if "pending_metrics" in data:
            pending = data["pending_metrics"]
            interpretation_parts.append(
                f"- 待进一步计算的指标: {list(pending.keys())}"
            )

        return "\n".join(interpretation_parts)

    def suggest_next_steps(
        self,
        current_result: Dict[str, Any],
        analysis_goal: str
    ) -> List[str]:
        """建议下一步分析

        Args:
            current_result: 当前分析结果
            analysis_goal: 分析目标

        Returns:
            建议的后续分析步骤列表
        """
        suggestions = []

        if "pending_metrics" in current_result.get("data", {}):
            pending = current_result["data"]["pending_metrics"]
            for metric, status in pending.items():
                if status == "pending":
                    suggestions.append(
                        f"需要获取自然资源数据以计算 {metric}"
                    )

        if current_result.get("data", {}).get("flood_risk_areas"):
            suggestions.append(
                "结合地形高程数据评估洪水风险等级"
            )
            suggestions.append(
                "分析降雨数据以完善洪水风险评估"
            )

        if not suggestions:
            suggestions.append("当前分析已完成，可进行结果可视化展示")

        return suggestions


__all__ = ["GeoAnalysisAgent"]