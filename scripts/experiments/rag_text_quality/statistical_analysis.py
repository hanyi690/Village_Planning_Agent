"""
Statistical Analysis Module
统计分析模块

实现实验数据的统计分析：
- 配对 t 检验：G1 vs G2 的指标差异
- 效应量计算：Cohen's d
- 可视化：雷达图、森林图

使用方法:
    analyzer = StatisticalAnalyzer()
    result = analyzer.compare_groups(g1_data, g2_data)
"""

import json
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime

# 添加项目路径
script_dir = Path(__file__).parent.resolve()
project_root = script_dir.parent.parent.parent.resolve()
backend_root = (project_root / "backend").resolve()

if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))
if str(backend_root) not in sys.path:
    sys.path.insert(0, str(backend_root))

logger = logging.getLogger(__name__)

# 尝试导入统计库
try:
    import numpy as np
    from scipy import stats
    HAS_SCIPY = True
except ImportError:
    HAS_SCIPY = False
    logger.warning("[Stats] scipy not available, using basic calculations")


# ============================================
# 数据类定义
# ============================================

@dataclass
class ComparisonResult:
    """两组对比结果"""
    metric_name: str
    group1_mean: float
    group1_std: float
    group2_mean: float
    group2_std: float
    difference: float
    percent_change: float
    cohens_d: float
    t_statistic: float
    p_value: float
    is_significant: bool
    significance_level: str


@dataclass
class GroupStatistics:
    """组统计信息"""
    group_name: str
    sample_size: int
    metrics: Dict[str, Dict[str, float]]  # {metric: {mean, std, min, max}}


@dataclass
class AnalysisResult:
    """分析结果"""
    experiment_id: str
    groups: Dict[str, GroupStatistics]
    comparisons: Dict[str, ComparisonResult]
    generated_at: str


# ============================================
# 统计分析器
# ============================================

class StatisticalAnalyzer:
    """
    统计分析器
    
    提供配对 t 检验、效应量计算等功能。
    """

    def __init__(self, alpha: float = 0.05):
        """
        初始化分析器
        
        Args:
            alpha: 显著性水平
        """
        self.alpha = alpha

    def calculate_mean(self, values: List[float]) -> float:
        """计算均值"""
        if not values:
            return 0.0
        return sum(values) / len(values)

    def calculate_std(self, values: List[float], mean: float = None) -> float:
        """计算标准差"""
        if not values or len(values) < 2:
            return 0.0
        if mean is None:
            mean = self.calculate_mean(values)
        variance = sum((x - mean) ** 2 for x in values) / (len(values) - 1)
        return variance ** 0.5

    def calculate_cohens_d(
        self,
        group1: List[float],
        group2: List[float]
    ) -> float:
        """
        计算 Cohen's d 效应量
        
        Cohen's d 解释：
        - |d| < 0.2: 小效应
        - 0.2 <= |d| < 0.8: 中等效应
        - |d| >= 0.8: 大效应
        
        Args:
            group1: 第一组数据
            group2: 第二组数据
            
        Returns:
            Cohen's d
        """
        if not group1 or not group2:
            return 0.0
        
        n1, n2 = len(group1), len(group2)
        mean1, mean2 = self.calculate_mean(group1), self.calculate_mean(group2)
        var1 = sum((x - mean1) ** 2 for x in group1) / (n1 - 1) if n1 > 1 else 0
        var2 = sum((x - mean2) ** 2 for x in group2) / (n2 - 1) if n2 > 1 else 0
        
        # 合并标准差
        pooled_std = ((n1 - 1) * var1 + (n2 - 1) * var2) / (n1 + n2 - 2)
        pooled_std = pooled_std ** 0.5 if pooled_std > 0 else 0.001
        
        return (mean1 - mean2) / pooled_std

    def paired_t_test(
        self,
        group1: List[float],
        group2: List[float]
    ) -> Tuple[float, float]:
        """
        配对 t 检验
        
        Args:
            group1: 第一组数据
            group2: 第二组数据
            
        Returns:
            (t 统计量, p 值)
        """
        if HAS_SCIPY:
            t_stat, p_value = stats.ttest_rel(group1, group2)
            return float(t_stat), float(p_value)
        
        # 简单实现（无 scipy）
        if not group1 or not group2 or len(group1) != len(group2):
            return 0.0, 1.0
        
        n = len(group1)
        differences = [g1 - g2 for g1, g2 in zip(group1, group2)]
        mean_diff = self.calculate_mean(differences)
        std_diff = self.calculate_std(differences, mean_diff)
        
        if std_diff == 0:
            return 0.0, 1.0
        
        t_stat = mean_diff / (std_diff / (n ** 0.5))
        
        # 近似 p 值（简化计算）
        # 自由度 = n - 1
        df = n - 1
        p_value = self._approximate_p_value(t_stat, df)
        
        return t_stat, p_value

    def _approximate_p_value(self, t_stat: float, df: int) -> float:
        """
        近似计算 p 值（无 scipy 时的简化方法）
        
        Args:
            t_stat: t 统计量
            df: 自由度
            
        Returns:
            近似 p 值
        """
        # 使用正态近似（大样本时）
        if df >= 30:
            # |t| > 1.96 对应 p < 0.05
            # |t| > 2.58 对应 p < 0.01
            # |t| > 3.29 对应 p < 0.001
            abs_t = abs(t_stat)
            if abs_t > 3.29:
                return 0.001
            elif abs_t > 2.58:
                return 0.01
            elif abs_t > 1.96:
                return 0.05
            else:
                return 0.10
        
        # 小样本时保守估计
        abs_t = abs(t_stat)
        if abs_t > 4.0:
            return 0.001
        elif abs_t > 3.0:
            return 0.01
        elif abs_t > 2.0:
            return 0.05
        else:
            return 0.10

    def compare_groups(
        self,
        group1_data: Dict[str, List[float]],
        group2_data: Dict[str, List[float]],
        group1_name: str = "G1",
        group2_name: str = "G2"
    ) -> Dict[str, ComparisonResult]:
        """
        对比两组数据
        
        Args:
            group1_data: 第一组数据 {metric: [values]}
            group2_data: 第二组数据 {metric: [values]}
            group1_name: 第一组名称
            group2_name: 第二组名称
            
        Returns:
            {metric: ComparisonResult}
        """
        results = {}
        
        for metric in group1_data:
            if metric not in group2_data:
                continue
            
            g1_values = group1_data[metric]
            g2_values = group2_data[metric]
            
            if not g1_values or not g2_values:
                continue
            
            # 计算统计量
            g1_mean = self.calculate_mean(g1_values)
            g1_std = self.calculate_std(g1_values, g1_mean)
            g2_mean = self.calculate_mean(g2_values)
            g2_std = self.calculate_std(g2_values, g2_mean)
            
            difference = g1_mean - g2_mean
            percent_change = (difference / g2_mean * 100) if g2_mean != 0 else 0
            
            # 效应量
            cohens_d = self.calculate_cohens_d(g1_values, g2_values)
            
            # t 检验
            t_stat, p_value = self.paired_t_test(g1_values, g2_values)
            
            # 显著性判断
            is_significant = p_value < self.alpha
            if p_value < 0.001:
                sig_level = "***"
            elif p_value < 0.01:
                sig_level = "**"
            elif p_value < 0.05:
                sig_level = "*"
            else:
                sig_level = "ns"
            
            results[metric] = ComparisonResult(
                metric_name=metric,
                group1_mean=g1_mean,
                group1_std=g1_std,
                group2_mean=g2_mean,
                group2_std=g2_std,
                difference=difference,
                percent_change=percent_change,
                cohens_d=cohens_d,
                t_statistic=t_stat,
                p_value=p_value,
                is_significant=is_significant,
                significance_level=sig_level,
            )
        
        return results

    def generate_summary_table(
        self,
        comparisons: Dict[str, ComparisonResult]
    ) -> List[Dict[str, Any]]:
        """
        生成汇总表格
        
        Args:
            comparisons: 对比结果
            
        Returns:
            表格数据
        """
        table = []
        for metric, result in comparisons.items():
            table.append({
                "metric": metric,
                "group1_mean": f"{result.group1_mean:.2f}",
                "group1_std": f"{result.group1_std:.2f}",
                "group2_mean": f"{result.group2_mean:.2f}",
                "group2_std": f"{result.group2_std:.2f}",
                "difference": f"{result.difference:.2f}",
                "percent_change": f"{result.percent_change:+.1f}%",
                "cohens_d": f"{result.cohens_d:.2f}",
                "p_value": f"{result.p_value:.4f}",
                "significance": result.significance_level,
            })
        return table


# ============================================
# 可视化辅助
# ============================================

def generate_radar_chart_data(
    comparisons: Dict[str, ComparisonResult],
    metrics_order: List[str] = None
) -> Dict[str, Any]:
    """
    生成雷达图数据
    
    Args:
        comparisons: 对比结果
        metrics_order: 指标顺序
        
    Returns:
        雷达图配置数据
    """
    if metrics_order is None:
        metrics_order = list(comparisons.keys())
    
    # 归一化数据（0-100）
    g1_values = []
    g2_values = []
    
    for metric in metrics_order:
        if metric in comparisons:
            result = comparisons[metric]
            # 使用百分比变化作为归一化依据
            g1_values.append(result.group1_mean)
            g2_values.append(result.group2_mean)
    
    return {
        "type": "radar",
        "data": {
            "labels": metrics_order,
            "datasets": [
                {
                    "label": "G1",
                    "data": g1_values,
                },
                {
                    "label": "G2",
                    "data": g2_values,
                },
            ],
        },
    }


def generate_forest_plot_data(
    comparisons: Dict[str, ComparisonResult]
) -> Dict[str, Any]:
    """
    生成森林图数据
    
    Args:
        comparisons: 对比结果
        
    Returns:
        森林图配置数据
    """
    data = []
    for metric, result in comparisons.items():
        data.append({
            "metric": metric,
            "effect_size": result.cohens_d,
            "ci_lower": result.cohens_d - 0.5,  # 简化 CI
            "ci_upper": result.cohens_d + 0.5,
            "p_value": result.p_value,
            "significant": result.is_significant,
        })
    
    return {
        "type": "forest",
        "data": data,
    }


# ============================================
# 便捷函数
# ============================================

def compare_groups(
    group1_data: Dict[str, List[float]],
    group2_data: Dict[str, List[float]]
) -> Dict[str, ComparisonResult]:
    """
    对比两组数据（便捷函数）
    
    Args:
        group1_data: 第一组数据
        group2_data: 第二组数据
        
    Returns:
        对比结果
    """
    analyzer = StatisticalAnalyzer()
    return analyzer.compare_groups(group1_data, group2_data)


if __name__ == "__main__":
    # 测试
    import random
    
    # 生成测试数据
    random.seed(42)
    
    g1_data = {
        "faithfulness": [random.uniform(0.5, 0.7) for _ in range(10)],
        "depth_score": [random.uniform(2.0, 3.0) for _ in range(10)],
        "citation_rate": [random.uniform(0.4, 0.6) for _ in range(10)],
    }
    
    g2_data = {
        "faithfulness": [random.uniform(0.8, 0.95) for _ in range(10)],
        "depth_score": [random.uniform(3.5, 4.5) for _ in range(10)],
        "citation_rate": [random.uniform(0.7, 0.9) for _ in range(10)],
    }
    
    results = compare_groups(g1_data, g2_data)
    
    print("对比结果:")
    print("-" * 80)
    print(f"{'指标':<20} {'G1 均值':<10} {'G2 均值':<10} {'变化':<10} {'Cohen d':<10} {'p 值':<10} {'显著性':<5}")
    print("-" * 80)
    
    for metric, result in results.items():
        print(f"{metric:<20} {result.group1_mean:<10.2f} {result.group2_mean:<10.2f} "
              f"{result.percent_change:<+10.1f}% {result.cohens_d:<10.2f} "
              f"{result.p_value:<10.4f} {result.significance_level:<5}")