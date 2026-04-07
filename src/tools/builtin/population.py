"""
人口预测内置工具

使用村庄规划标准模型进行人口预测。
"""

import re
from datetime import datetime
from typing import Dict, Any

from ..registry import ToolRegistry
from ...utils.logger import get_logger

logger = get_logger(__name__)


@ToolRegistry.register("population_model_v1")
def calculate_population(context: Dict[str, Any]) -> str:
    """
    人口预测模型

    使用村庄规划标准模型: Pn = P0 × (1 + K)^n + M

    Args:
        context: 包含人口相关数据的上下文
            - socio_economic: 社会经济分析文本（提取基期人口）
            - baseline_population: 基期人口（可选，优先使用）
            - baseline_year: 基期年份（可选，默认2024）
            - target_year: 目标年份（可选，默认2035）
            - natural_growth_rate: 自然增长率‰（可选，默认4‰）
            - mechanical_growth: 机械增长人口（可选，默认0）

    Returns:
        格式化的预测结果字符串
    """
    baseline_population = context.get("baseline_population")
    if baseline_population is None:
        socio_economic = context.get("socio_economic", "")
        pop_match = re.search(r'(?:户籍)?人口[：:]\s*(\d+)', socio_economic)
        baseline_population = int(pop_match.group(1)) if pop_match else 1000

    current_year = datetime.now().year
    baseline_year = context.get("baseline_year", current_year)
    target_year = context.get("target_year", 2035)
    natural_growth_rate = context.get("natural_growth_rate", 4.0)
    mechanical_growth = context.get("mechanical_growth", 0)
    n = target_year - baseline_year

    try:
        from ..core.population_core import run_population_analysis

        result = run_population_analysis(
            analysis_type="village_forecast",
            baseline_population=baseline_population,
            baseline_year=baseline_year,
            target_year=target_year,
            natural_growth_rate=natural_growth_rate,
            mechanical_growth=mechanical_growth,
            intermediate_years=[2030]
        )

        if result.get("success"):
            data = result["data"]
            intermediate = data.get("intermediate_results", {})

            return f"""## 人口预测结果

**预测模型**: Pn = P0 × (1 + K)^n + M（村庄规划标准模型）

**基础参数**:
- 基期年份: {data['baseline_year']}年
- 基期人口: {data['baseline_population']}人
- 自然增长率: {data['natural_growth_rate_permillage']}‰
- 机械增长人口: {data['mechanical_growth']}人

**预测结果**:
- 预测年限: {data['forecast_years']}年
- 自然增长系数: {data['natural_growth_factor']}
- **{data['target_year']}年预测人口: {data['forecast_population']}人**
{f"- 2030年预测人口: {intermediate.get(2030, 'N/A')}人" if 2030 in intermediate else ""}

**计算过程**:
P{n} = {baseline_population} × (1 + {natural_growth_rate/1000})^{data['forecast_years']} + {mechanical_growth}
     = {baseline_population} × {data['natural_growth_factor']} + {mechanical_growth}
     = {data['forecast_population']}人
"""
        else:
            logger.warning(f"[population_model_v1] 预测失败: {result.get('error')}，使用简化模型")
            raise Exception(result.get("error"))

    except Exception as e:
        n = target_year - baseline_year
        K = natural_growth_rate / 1000
        forecast_pop = int(baseline_population * ((1 + K) ** n) + mechanical_growth)

        logger.warning(f"[population_model_v1] 使用简化模型（{e}）")

        return f"""## 人口预测结果

**预测模型**: Pn = P0 × (1 + K)^n + M（简化计算）

**基础参数**:
- 基期人口: {baseline_population}人
- 自然增长率: {natural_growth_rate}‰
- 机械增长人口: {mechanical_growth}人

**预测结果**:
- **{target_year}年预测人口: {forecast_pop}人**

**注意**: 适配器不可用，使用简化计算
"""


__all__ = ["calculate_population"]