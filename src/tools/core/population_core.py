"""
人口预测核心逻辑

从 PopulationPredictionAdapter 提取的核心功能，提供人口预测、人口结构、劳动力分析。
"""

from typing import Dict, Any, List, Optional
import math
from ...utils.logger import get_logger

logger = get_logger(__name__)


def run_population_analysis(
    analysis_type: str,
    baseline_population: Optional[int] = None,
    baseline_year: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    执行人口预测分析

    Args:
        analysis_type: 分析类型
            - population_forecast: 通用人口预测
            - village_forecast: 村庄规划标准模型
            - population_structure: 人口结构分析
            - labor_force_analysis: 劳动力供给分析
        baseline_population: 基期人口
        baseline_year: 基期年份

    Returns:
        Dict[str, Any]: 分析结果
    """
    if analysis_type == "population_forecast":
        return _forecast_population(baseline_population, baseline_year, **kwargs)
    elif analysis_type == "village_forecast":
        return _village_forecast(baseline_population, baseline_year, **kwargs)
    elif analysis_type == "population_structure":
        return _analyze_population_structure(kwargs.get("total_population"), **kwargs)
    elif analysis_type == "labor_force_analysis":
        return _analyze_labor_force(kwargs.get("total_population"), **kwargs)
    else:
        return {"success": False, "error": f"不支持的分析类型: {analysis_type}"}


def _forecast_population(
    baseline_population: Optional[int],
    baseline_year: Optional[int],
    **kwargs
) -> Dict[str, Any]:
    """人口预测"""
    if baseline_population is None:
        return {"success": False, "error": "缺少必需参数: baseline_population"}
    if baseline_year is None:
        return {"success": False, "error": "缺少必需参数: baseline_year"}

    try:
        forecast_years_count = kwargs.get("forecast_years", 10)
        growth_rate = kwargs.get("growth_rate", 0.5)
        model = kwargs.get("model", "exponential")

        forecast_years = [baseline_year + i for i in range(1, forecast_years_count + 1)]
        forecast_population = []

        if model == "exponential":
            for i in range(1, forecast_years_count + 1):
                pop = baseline_population * ((1 + growth_rate / 100) ** i)
                forecast_population.append(int(pop))
        elif model == "linear":
            for i in range(1, forecast_years_count + 1):
                pop = baseline_population * (1 + (growth_rate / 100) * i)
                forecast_population.append(int(pop))
        elif model == "logistic":
            carrying_capacity = kwargs.get("carrying_capacity", baseline_population * 1.5)
            r = growth_rate / 100
            for i in range(1, forecast_years_count + 1):
                pop = carrying_capacity / (1 + ((carrying_capacity - baseline_population) / baseline_population) * math.exp(-r * i))
                forecast_population.append(int(pop))

        result = {
            "baseline_population": baseline_population,
            "baseline_year": baseline_year,
            "forecast_years": forecast_years,
            "forecast_population": forecast_population,
            "growth_rate": growth_rate,
            "model": model
        }

        if model == "logistic":
            peak_idx = forecast_population.index(max(forecast_population))
            result["peak_year"] = forecast_years[peak_idx]
            result["peak_population"] = forecast_population[peak_idx]

        return {"success": True, "data": result}
    except Exception as e:
        return {"success": False, "error": f"人口预测失败: {str(e)}"}


def _village_forecast(
    baseline_population: Optional[int],
    baseline_year: Optional[int],
    **kwargs
) -> Dict[str, Any]:
    """
    村庄规划标准人口预测模型

    公式: Pn = P0 × (1 + K)^n + M
    """
    if baseline_population is None:
        return {"success": False, "error": "缺少必需参数: baseline_population"}
    if baseline_year is None:
        return {"success": False, "error": "缺少必需参数: baseline_year"}

    try:
        target_year = kwargs.get("target_year", 2035)
        n = target_year - baseline_year

        if n <= 0:
            return {"success": False, "error": f"目标年份 {target_year} 必须大于基期年份 {baseline_year}"}

        natural_growth_rate = kwargs.get("natural_growth_rate", 4.0)
        mechanical_growth = kwargs.get("mechanical_growth", 0)

        K = natural_growth_rate / 1000
        natural_growth_factor = (1 + K) ** n
        forecast_population = int(baseline_population * natural_growth_factor + mechanical_growth)

        intermediate_years = kwargs.get("intermediate_years", [2030])
        intermediate_results = {}
        for year in intermediate_years:
            if year > baseline_year and year < target_year:
                mid_n = year - baseline_year
                mid_pop = int(baseline_population * ((1 + K) ** mid_n) + mechanical_growth * (mid_n / n))
                intermediate_results[year] = mid_pop

        return {
            "success": True,
            "data": {
                "model": "village_standard",
                "formula": "Pn = P0 × (1 + K)^n + M",
                "baseline_population": baseline_population,
                "baseline_year": baseline_year,
                "target_year": target_year,
                "forecast_years": n,
                "natural_growth_rate_permillage": natural_growth_rate,
                "mechanical_growth": mechanical_growth,
                "natural_growth_factor": round(natural_growth_factor, 4),
                "forecast_population": forecast_population,
                "intermediate_results": intermediate_results if intermediate_results else None
            }
        }
    except Exception as e:
        return {"success": False, "error": f"村庄人口预测失败: {str(e)}"}


def _analyze_population_structure(total_population: Optional[int], **kwargs) -> Dict[str, Any]:
    """人口结构分析"""
    if total_population is None:
        return {"success": False, "error": "缺少必需参数: total_population"}

    age_distribution = kwargs.get("age_distribution")
    if not age_distribution:
        return {"success": False, "error": "缺少必需参数: age_distribution"}

    gender_ratio = kwargs.get("gender_ratio")
    if not gender_ratio:
        return {"success": False, "error": "缺少必需参数: gender_ratio"}

    labor_force_participation_rate = kwargs.get("labor_force_participation_rate")
    if labor_force_participation_rate is None:
        return {"success": False, "error": "缺少必需参数: labor_force_participation_rate"}

    try:
        for age_group in age_distribution:
            age_group["population"] = int(total_population * age_group["percentage"] / 100)

        working_age_percentage = sum(
            ag["percentage"] for ag in age_distribution
            if ag["age_group"] in ["15-24岁", "25-44岁", "45-64岁"]
        )
        dependent_age_percentage = sum(
            ag["percentage"] for ag in age_distribution
            if ag["age_group"] in ["0-14岁", "65岁以上"]
        )
        dependency_ratio = (dependent_age_percentage / working_age_percentage) * 100 if working_age_percentage > 0 else 0

        return {
            "success": True,
            "data": {
                "age_distribution": age_distribution,
                "gender_ratio": gender_ratio,
                "labor_force_participation_rate": round(labor_force_participation_rate, 2),
                "dependency_ratio": round(dependency_ratio, 2)
            }
        }
    except Exception as e:
        return {"success": False, "error": f"人口结构分析失败: {str(e)}"}


def _analyze_labor_force(total_population: Optional[int], **kwargs) -> Dict[str, Any]:
    """劳动力供给分析"""
    if total_population is None:
        return {"success": False, "error": "缺少必需参数: total_population"}

    population_structure = kwargs.get("population_structure")
    if not population_structure:
        return {"success": False, "error": "缺少必需参数: population_structure"}

    labor_participation_rate = kwargs.get("labor_participation_rate")
    if labor_participation_rate is None:
        return {"success": False, "error": "缺少必需参数: labor_participation_rate"}

    cultivated_land = kwargs.get("cultivated_land")
    if cultivated_land is None:
        return {"success": False, "error": "缺少必需参数: cultivated_land"}

    non_agricultural_jobs = kwargs.get("non_agricultural_jobs")
    if non_agricultural_jobs is None:
        return {"success": False, "error": "缺少必需参数: non_agricultural_jobs"}

    try:
        age_distribution = population_structure.get("age_distribution", [])
        working_age_population = sum(
            ag["population"] for ag in age_distribution
            if ag["age_group"] in ["15-24岁", "25-44岁", "45-64岁"]
        )

        labor_force_size = int(working_age_population * labor_participation_rate / 100)
        labor_demand_agriculture = int(cultivated_land / 100 * 15)
        labor_demand_non_agriculture = non_agricultural_jobs
        total_labor_demand = labor_demand_agriculture + labor_demand_non_agriculture
        labor_surplus = labor_force_size - total_labor_demand

        elderly_percentage = next(
            (ag["percentage"] for ag in age_distribution if ag["age_group"] == "65岁以上"),
            None
        )

        if elderly_percentage is None:
            return {"success": False, "error": "年龄分布数据中缺少65岁以上年龄组"}

        if elderly_percentage < 10:
            aging_trend = "年轻化"
        elif elderly_percentage < 14:
            aging_trend = "成年型"
        elif elderly_percentage < 20:
            aging_trend = "老龄化初期"
        else:
            aging_trend = "中度老龄化"

        return {
            "success": True,
            "data": {
                "working_age_population": working_age_population,
                "labor_force_size": labor_force_size,
                "labor_demand": {
                    "total": total_labor_demand,
                    "agriculture": labor_demand_agriculture,
                    "non_agriculture": labor_demand_non_agriculture
                },
                "labor_surplus": labor_surplus,
                "aging_trend": aging_trend,
                "elderly_percentage": round(elderly_percentage, 2)
            }
        }
    except Exception as e:
        return {"success": False, "error": f"劳动力供给分析失败: {str(e)}"}


def format_population_result(result: Dict[str, Any]) -> str:
    """格式化人口分析结果为字符串"""
    if not result.get("success"):
        return f"人口分析失败: {result.get('error', '未知错误')}"

    data = result.get("data", {})
    lines = ["人口预测分析结果："]

    if "model" in data:
        if data["model"] == "village_standard":
            lines.append(f"- 模型: 村庄规划标准模型 ({data['formula']})")
            lines.append(f"- 基期人口: {data['baseline_population']} 人 ({data['baseline_year']}年)")
            lines.append(f"- 目标年份: {data['target_year']}年")
            lines.append(f"- 预测年限: {data['forecast_years']} 年")
            lines.append(f"- 自然增长率: {data['natural_growth_rate_permillage']}‰")
            lines.append(f"- 机械增长: {data['mechanical_growth']} 人")
            lines.append(f"- 预测人口: {data['forecast_population']} 人")

            if data.get("intermediate_results"):
                lines.append("- 中间年份预测:")
                for year, pop in data["intermediate_results"].items():
                    lines.append(f"  * {year}年: {pop} 人")
        else:
            lines.append(f"- 模型: {data['model']}")
            lines.append(f"- 基期人口: {data['baseline_population']} 人 ({data['baseline_year']}年)")
            lines.append(f"- 增长率: {data['growth_rate']}%")
            lines.append("- 预测序列:")
            for year, pop in zip(data["forecast_years"], data["forecast_population"]):
                lines.append(f"  * {year}年: {pop} 人")

    if "age_distribution" in data:
        lines.append("- 年龄结构分布:")
        for ag in data["age_distribution"]:
            lines.append(f"  * {ag['age_group']}: {ag['percentage']}% ({ag.get('population', 0)} 人)")

    if "labor_force_size" in data:
        lines.append(f"- 劳动力规模: {data['labor_force_size']} 人")
        lines.append(f"- 劳动力剩余: {data['labor_surplus']} 人")
        lines.append(f"- 老龄化趋势: {data['aging_trend']}")

    return "\n".join(lines)