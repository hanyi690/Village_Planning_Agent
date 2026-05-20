"""
人口预测内置工具

使用村庄规划标准模型进行人口预测: Pn = P0 × (1 + K)^n + M
"""

import re
from datetime import datetime
from typing import Dict, Any

from ..registry import ToolRegistry
from app.utils.logger import get_logger

logger = get_logger(__name__)


@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str:
    """
    人口预测模型

    使用村庄规划标准模型: Pn = P0 × (1 + K)^n + M

    Args:
        context: 包含人口相关数据的上下文
            - structured_summary: 结构化摘要对象（优先从中提取参数）
            - baseline_population: 基期人口（可选）
            - baseline_year: 基期年份（可选，默认当前年份）
            - target_year: 目标年份（可选，默认2035）
            - natural_growth_rate: 自然增长率‰（可选，默认4‰）
            - mechanical_growth: 机械增长人口（可选，默认0）

    Returns:
        格式化的预测结果字符串
    """
    # Priority: explicit params > structured_summary > dep_metrics > regex extraction
    baseline_population = context.get("baseline_population")

    if baseline_population is None:
        summary = context.get("structured_summary")
        if summary and hasattr(summary, 'registered_population') and summary.registered_population is not None:
            baseline_population = summary.registered_population
            logger.info(f"[population_model_v1] 从结构化摘要获取基期人口: {baseline_population}")

    if baseline_population is None:
        dep_metrics = context.get("dep_metrics") or context.get("_dep_metrics") or {}
        if "registered_population" in dep_metrics:
            baseline_population = dep_metrics["registered_population"]
            logger.info(f"[population_model_v1] 从依赖指标获取基期人口: {baseline_population}")

    if baseline_population is None:
        # Fallback to regex extraction from text
        socio_economic = context.get("socio_economic", "")
        pop_match = re.search(r'(?:户籍)?人口[：:]\s*(\d+)', socio_economic)
        baseline_population = int(pop_match.group(1)) if pop_match else None

    if baseline_population is None:
        logger.error("[population_model_v1] 无法获取基期人口，请确保 socio_economic 维度已分析")
        return "## 人口预测失败\n\n**错误**: 无法获取基期人口数据。请先完成社会经济维度分析，确保户籍人口数据已提取。"

    current_year = datetime.now().year
    baseline_year = context.get("baseline_year", current_year)

    # Try structured summary for growth rate
    natural_growth_rate = context.get("natural_growth_rate")
    if natural_growth_rate is None:
        natural_growth_rate = 4.0  # Default 4‰

    mechanical_growth = context.get("mechanical_growth", 0)
    target_year = context.get("target_year", 2035)

    # Calculate using standard model: Pn = P0 × (1 + K)^n + M
    n = target_year - baseline_year
    K = natural_growth_rate / 1000
    forecast_pop = int(baseline_population * ((1 + K) ** n) + mechanical_growth)

    # Also calculate intermediate year 2030 if applicable
    intermediate_results = {}
    if baseline_year < 2030 < target_year:
        n_2030 = 2030 - baseline_year
        pop_2030 = int(baseline_population * ((1 + K) ** n_2030) + mechanical_growth)
        intermediate_results[2030] = pop_2030

    natural_growth_factor = round((1 + K) ** n, 6)

    result = f"""## 人口预测结果

**预测模型**: Pn = P0 × (1 + K)^n + M（村庄规划标准模型）

**基础参数**:
- 基期年份: {baseline_year}年
- 基期人口: {baseline_population}人
- 自然增长率: {natural_growth_rate}‰
- 机械增长人口: {mechanical_growth}人

**预测结果**:
- 预测年限: {n}年
- 自然增长系数: {natural_growth_factor}
- **{target_year}年预测人口: {forecast_pop}人**"""

    if 2030 in intermediate_results:
        result += f"\n- 2030年预测人口: {intermediate_results[2030]}人"

    result += f"""

**计算过程**:
P{n} = {baseline_population} × (1 + {K})^{n} + {mechanical_growth}
     = {baseline_population} × {natural_growth_factor} + {mechanical_growth}
     = {forecast_pop}人"""

    return result


__all__ = ["calculate_population"]