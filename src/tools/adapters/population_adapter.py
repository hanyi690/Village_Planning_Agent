"""
人口预测适配器

提供人口预测、人口结构模型、劳动力供给分析等功能。
使用独立的人口预测脚本和统计模型。
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import math

from .base_adapter import BaseAdapter, AdapterResult, AdapterStatus
from ...utils.logger import get_logger

logger = get_logger(__name__)


class PopulationPredictionAdapter(BaseAdapter):
    """
    人口预测适配器

    支持的分析类型：
    1. 人口预测 (population_forecast)
    2. 人口结构模型 (population_structure)
    3. 劳动力供给分析 (labor_force_analysis)
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """
        初始化人口预测适配器

        Args:
            config: 配置参数
        """
        super().__init__(config)

    def validate_dependencies(self) -> bool:
        """
        验证外部依赖是否可用

        Returns:
            True (人口预测适配器使用内置算法，始终可用)
        """
        # 人口预测适配器使用内置算法，不依赖外部库
        logger.info("[PopulationAdapter] 使用内置预测算法")
        return True

    def initialize(self) -> bool:
        """
        初始化适配器

        Returns:
            True if initialization successful
        """
        try:
            # 初始化预测模型参数
            self._status = AdapterStatus.READY
            logger.info("[PopulationAdapter] 人口预测适配器已初始化")
            return True
        except Exception as e:
            self._error_message = f"初始化失败: {str(e)}"
            logger.error(f"[PopulationAdapter] {self._error_message}")
            return False

    def execute(self, analysis_type: str = "population_forecast", **kwargs) -> AdapterResult:
        """
        执行人口预测分析

        Args:
            analysis_type: 分析类型 (population_forecast/population_structure/labor_force_analysis)
            **kwargs: 分析参数，可包含：
                - baseline_population: 基期人口
                - baseline_year: 基期年份
                - forecast_years: 预测年份数
                - growth_rate: 增长率（%）
                - age_structure: 年龄结构数据
                - custom_params: 自定义参数

        Returns:
            AdapterResult: 分析结果
        """
        if analysis_type == "population_forecast":
            return self._forecast_population(**kwargs)
        elif analysis_type == "population_structure":
            return self._analyze_population_structure(**kwargs)
        elif analysis_type == "labor_force_analysis":
            return self._analyze_labor_force(**kwargs)
        else:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"不支持的分析类型: {analysis_type}"
            )

    def get_schema(self) -> Dict[str, Any]:
        """获取输出Schema"""
        return {
            "adapter_name": "PopulationPredictionAdapter",
            "supported_analyses": [
                "population_forecast",
                "population_structure",
                "labor_force_analysis"
            ],
            "output_schemas": {
                "population_forecast": {
                    "baseline_population": "integer",
                    "baseline_year": "integer",
                    "forecast_years": "array",
                    "forecast_population": "array",
                    "growth_rate": "number (optional)",
                    "peak_year": "integer (optional)",
                    "peak_population": "integer (optional)"
                },
                "population_structure": {
                    "age_distribution": "array",
                    "gender_ratio": "object (optional)",
                    "labor_force_participation_rate": "number (optional)",
                    "dependency_ratio": "number (optional)"
                },
                "labor_force_analysis": {
                    "working_age_population": "integer",
                    "labor_force_size": "integer",
                    "labor_surplus": "integer",
                    "aging_trend": "string"
                }
            }
        }

    # ==========================================
    # 具体分析方法
    # ==========================================

    def _forecast_population(self, **kwargs) -> AdapterResult:
        """
        人口预测

        基于历史数据和增长率预测未来人口。
        支持多种预测模型：线性增长、指数增长、Logistic增长。
        """
        logger.info("[PopulationAdapter] 执行人口预测")

        # 检查必需参数
        baseline_population = kwargs.get("baseline_population")
        if baseline_population is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: baseline_population。请提供基期人口数据。"
            )

        baseline_year = kwargs.get("baseline_year")
        if baseline_year is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: baseline_year。请提供基期年份。"
            )

        try:
            forecast_years_count = kwargs.get("forecast_years", 10)
            growth_rate = kwargs.get("growth_rate", 0.5)  # 默认0.5%年增长率
            model = kwargs.get("model", "exponential")  # exponential, logistic, linear

            # 生成预测年份
            forecast_years = [baseline_year + i for i in range(1, forecast_years_count + 1)]
            forecast_population = []

            if model == "exponential":
                # 指数增长模型: P(t) = P0 * (1 + r)^t
                for i, year in enumerate(forecast_years, 1):
                    pop = baseline_population * ((1 + growth_rate / 100) ** i)
                    forecast_population.append(int(pop))

            elif model == "linear":
                # 线性增长模型: P(t) = P0 + P0 * r * t
                for i, year in enumerate(forecast_years, 1):
                    pop = baseline_population * (1 + (growth_rate / 100) * i)
                    forecast_population.append(int(pop))

            elif model == "logistic":
                # Logistic增长模型: P(t) = K / (1 + ((K - P0) / P0) * e^(-rt))
                carrying_capacity = kwargs.get("carrying_capacity", baseline_population * 1.5)
                r = growth_rate / 100

                for i, year in enumerate(forecast_years, 1):
                    pop = carrying_capacity / (1 + ((carrying_capacity - baseline_population) / baseline_population) * math.exp(-r * i))
                    forecast_population.append(int(pop))

            # 找出峰值年份
            if model == "logistic":
                # Logistic模型有峰值
                peak_idx = forecast_population.index(max(forecast_population))
                peak_year = forecast_years[peak_idx]
                peak_population = forecast_population[peak_idx]
            else:
                # 指数和线性模型在预测期内无峰值
                peak_year = None
                peak_population = None

            result = {
                "baseline_population": baseline_population,
                "baseline_year": baseline_year,
                "forecast_years": forecast_years,
                "forecast_population": forecast_population,
                "growth_rate": growth_rate,
                "model": model
            }

            if peak_year:
                result["peak_year"] = peak_year
                result["peak_population"] = peak_population

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result,
                metadata={
                    "analysis_type": "population_forecast",
                    "model": model
                }
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"人口预测失败: {str(e)}"
            )

    def _analyze_population_structure(self, **kwargs) -> AdapterResult:
        """
        人口结构模型

        分析人口的年龄结构、性别比例、劳动参与率等。
        """
        logger.info("[PopulationAdapter] 执行人口结构分析")

        # 检查必需参数
        total_population = kwargs.get("total_population")
        if total_population is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: total_population。请提供总人口数据。"
            )

        # 检查年龄分布
        age_distribution = kwargs.get("age_distribution")
        if not age_distribution:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: age_distribution。请提供年龄分布数据（列表，包含age_group和percentage字段）。"
            )

        try:
            # 计算各年龄组人口数
            for age_group in age_distribution:
                age_group["population"] = int(total_population * age_group["percentage"] / 100)

            # 性别比例（可选参数，如果未提供则报错）
            gender_ratio = kwargs.get("gender_ratio")
            if not gender_ratio:
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error="缺少必需参数: gender_ratio。请提供性别比例数据（包含male和female字段）。"
                )

            # 劳动参与率（可选参数）
            labor_force_participation_rate = kwargs.get("labor_force_participation_rate")
            if labor_force_participation_rate is None:
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error="缺少必需参数: labor_force_participation_rate。请提供劳动参与率数据。"
                )

            # 计算抚养比
            working_age_percentage = sum(
                ag["percentage"] for ag in age_distribution
                if ag["age_group"] in ["15-24岁", "25-44岁", "45-64岁"]
            )
            dependent_age_percentage = sum(
                ag["percentage"] for ag in age_distribution
                if ag["age_group"] in ["0-14岁", "65岁以上"]
            )
            dependency_ratio = (dependent_age_percentage / working_age_percentage) * 100 if working_age_percentage > 0 else 0

            result = {
                "age_distribution": age_distribution,
                "gender_ratio": gender_ratio,
                "labor_force_participation_rate": round(labor_force_participation_rate, 2),
                "dependency_ratio": round(dependency_ratio, 2)
            }

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result,
                metadata={
                    "analysis_type": "population_structure",
                    "total_population": total_population
                }
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"人口结构分析失败: {str(e)}"
            )

    def _analyze_labor_force(self, **kwargs) -> AdapterResult:
        """
        劳动力供给分析

        分析劳动力规模、劳动力剩余、老龄化趋势等。
        """
        logger.info("[PopulationAdapter] 执行劳动力供给分析")

        # 检查必需参数
        total_population = kwargs.get("total_population")
        if total_population is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: total_population。请提供总人口数据。"
            )

        population_structure = kwargs.get("population_structure")
        if not population_structure:
            # 如果没有提供人口结构，要求用户提供
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: population_structure。请先执行人口结构分析，或提供人口结构数据。"
            )

        labor_participation_rate = kwargs.get("labor_participation_rate")
        if labor_participation_rate is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: labor_participation_rate。请提供劳动参与率数据。"
            )

        cultivated_land = kwargs.get("cultivated_land")
        if cultivated_land is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: cultivated_land。请提供耕地面积数据（亩）。"
            )

        non_agricultural_jobs = kwargs.get("non_agricultural_jobs")
        if non_agricultural_jobs is None:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error="缺少必需参数: non_agricultural_jobs。请提供非农产业就业岗位数量。"
            )

        try:
            # 计算劳动年龄人口（15-64岁）
            age_distribution = population_structure.get("age_distribution", [])
            working_age_population = sum(
                ag["population"] for ag in age_distribution
                if ag["age_group"] in ["15-24岁", "25-44岁", "45-64岁"]
            )

            # 劳动力规模
            labor_force_size = int(working_age_population * labor_participation_rate / 100)

            # 劳动力需求
            # 农业劳动力需求：假设每100亩耕地需要15个劳动力
            labor_demand_agriculture = int(cultivated_land / 100 * 15)

            # 非农产业劳动力需求
            labor_demand_non_agriculture = non_agricultural_jobs

            total_labor_demand = labor_demand_agriculture + labor_demand_non_agriculture

            # 劳动力剩余
            labor_surplus = labor_force_size - total_labor_demand

            # 老龄化趋势
            elderly_percentage = next(
                (ag["percentage"] for ag in age_distribution if ag["age_group"] == "65岁以上"),
                None
            )

            if elderly_percentage is None:
                return AdapterResult(
                    success=False,
                    status=AdapterStatus.FAILED,
                    data={},
                    metadata={},
                    error="年龄分布数据中缺少65岁以上年龄组。请提供完整的年龄分布数据。"
                )

            if elderly_percentage < 10:
                aging_trend = "年轻化"
            elif elderly_percentage < 14:
                aging_trend = "成年型"
            elif elderly_percentage < 20:
                aging_trend = "老龄化初期"
            else:
                aging_trend = "中度老龄化"

            result = {
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

            return AdapterResult(
                success=True,
                status=AdapterStatus.SUCCESS,
                data=result,
                metadata={
                    "analysis_type": "labor_force_analysis",
                    "total_population": total_population
                }
            )

        except Exception as e:
            return AdapterResult(
                success=False,
                status=AdapterStatus.FAILED,
                data={},
                metadata={},
                error=f"劳动力供给分析失败: {str(e)}"
            )

    def run_all_analyses(self, **kwargs) -> Dict[str, AdapterResult]:
        """
        运行所有人口分析

        Args:
            **kwargs: 分析参数

        Returns:
            包含所有分析结果的字典
        """
        # 先获取人口结构
        structure_result = self.execute(analysis_type="population_structure", **kwargs)

        # 传递人口结构到劳动力分析
        labor_kwargs = {**kwargs}
        if structure_result.success:
            labor_kwargs["population_structure"] = structure_result.data

        return {
            "forecast": self.execute(analysis_type="population_forecast", **kwargs),
            "structure": structure_result,
            "labor_force": self.execute(analysis_type="labor_force_analysis", **labor_kwargs)
        }
