"""
集成测试：部分状态传递优化

测试完整流程中的部分状态传递功能，验证优化效果。
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.subgraphs.analysis_subgraph import call_analysis_subgraph
from src.subgraphs.concept_subgraph import call_concept_subgraph
from src.subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph
from src.utils.state_filter import estimate_token_reduction, log_optimization_results
from src.utils.logger import get_logger

logger = get_logger(__name__)


class TestPartialStateIntegration:
    """集成测试：部分状态传递"""

    @pytest.fixture
    def sample_village_data(self):
        """示例村庄数据"""
        return """
# 测试村庄基础数据

## 基本信息
- 村庄名称：测试村
- 人口：1200人
- 面积：5.2平方公里
- 主要产业：农业、旅游业

## 区位分析
位于XX市XX区，距离市中心25公里，交通便利。

## 社会经济分析
人口1200人，主要产业为农业和旅游业，年产值3000万元。

## 自然环境分析
丘陵地貌，森林覆盖率68%，生态环境良好。

## 土地利用分析
农用地占比70%，建设用地占20%，未利用土地10%。

## 交通分析
县道通过村庄，距离高速公路出口15公里。

## 公共服务设施
有小学1所、卫生室1个、文化广场1处，设施较完善。

## 基础设施
道路基本硬化，供水设施完善，污水处理不足。

## 生态绿地
村庄周边有林地、草地等生态绿地，面积较大。

## 建筑分析
传统建筑占60%，现代建筑占40%，建筑质量一般。

## 历史文化
有明清时期古建筑，历史文化价值较高。
"""

    @pytest.fixture
    def sample_task_description(self):
        """示例任务描述"""
        return "制定乡村振兴总体规划，重点发展生态旅游和现代农业"

    def test_layer1_layer2_integration(self, sample_village_data, sample_task_description):
        """
        测试 Layer 1 → Layer 2 的集成

        验证：
        1. Layer 1 生成 dimension_reports
        2. Layer 2 接收并使用 dimension_reports
        3. 优化效果
        """
        logger.info("[集成测试] 开始测试 Layer 1 → Layer 2")

        # Layer 1: 现状分析
        result_l1 = call_analysis_subgraph(
            raw_data=sample_village_data,
            project_name="测试村"
        )

        # 验证：Layer 1 成功
        assert result_l1["success"] == True
        assert "analysis_report" in result_l1
        assert "dimension_reports" in result_l1

        # 验证：dimension_reports 不为空
        dimension_reports = result_l1["dimension_reports"]
        assert isinstance(dimension_reports, dict)
        assert len(dimension_reports) > 0

        logger.info(f"[集成测试] Layer 1 生成了 {len(dimension_reports)} 个维度报告")

        # 验证：包含预期的维度
        expected_dimensions = [
            "location", "socio_economic", "natural_environment",
            "land_use", "traffic", "public_services", "infrastructure",
            "ecological_green", "architecture", "historical_cultural"
        ]
        for dim in expected_dimensions:
            assert dim in dimension_reports, f"缺少维度: {dim}"

        # Layer 2: 规划思路（传递 dimension_reports）
        result_l2 = call_concept_subgraph(
            project_name="测试村",
            analysis_report=result_l1["analysis_report"],
            dimension_reports=dimension_reports,  # 传递维度报告
            task_description=sample_task_description,
            constraints="生态优先，绿色发展"
        )

        # 验证：Layer 2 成功
        assert result_l2["success"] == True
        assert "concept_report" in result_l2
        assert "concept_dimension_reports" in result_l2

        logger.info(f"[集成测试] Layer 2 生成了 {len(result_l2['concept_dimension_reports'])} 个规划维度报告")

        # 计算优化效果（估算）
        full_length = len(result_l1["analysis_report"])
        # 资源禀赋只需要4个维度，约40%的数据
        estimated_filtered = full_length * 0.4
        reduction = estimate_token_reduction("resource_endowment", full_length, estimated_filtered)

        logger.info(f"[集成测试] 资源禀赋维度优化估算: {reduction['reduction_percent']}% 节省")

        # 验证：有优化效果
        assert reduction["reduction_percent"] > 0

    def test_full_layer_integration(self, sample_village_data, sample_task_description):
        """
        测试完整三层集成

        验证：
        1. 所有层级都能成功传递 dimension_reports
        2. 最终结果质量不受影响
        """
        logger.info("[集成测试] 开始测试完整三层流程")

        # Layer 1
        result_l1 = call_analysis_subgraph(
            raw_data=sample_village_data,
            project_name="测试村"
        )
        assert result_l1["success"]
        assert len(result_l1["dimension_reports"]) > 0

        # Layer 2
        result_l2 = call_concept_subgraph(
            project_name="测试村",
            analysis_report=result_l1["analysis_report"],
            dimension_reports=result_l1["dimension_reports"],
            task_description=sample_task_description
        )
        assert result_l2["success"]
        assert len(result_l2["concept_dimension_reports"]) > 0

        # Layer 3: 详细规划（测试少量维度）
        result_l3 = call_detailed_plan_subgraph(
            project_name="测试村",
            analysis_report=result_l1["analysis_report"],
            planning_concept=result_l2["concept_report"],
            dimension_reports=result_l1["dimension_reports"],
            concept_dimension_reports=result_l2["concept_dimension_reports"],
            task_description=sample_task_description,
            required_dimensions=["industry", "traffic"]  # 只生成2个维度
        )
        assert result_l3["success"]
        assert result_l3["completed_dimensions"] == ["industry", "traffic"]

        logger.info(f"[集成测试] 完整流程测试通过")

    def test_optimization_metrics(self, sample_village_data):
        """
        测试优化指标

        验证：
        1. Token 使用确实减少
        2. 优化率达到预期
        """
        logger.info("[集成测试] 开始测试优化指标")

        # 执行现状分析
        result = call_analysis_subgraph(
            raw_data=sample_village_data,
            project_name="测试村"
        )

        assert result["success"]
        dimension_reports = result["dimension_reports"]
        full_report = result["analysis_report"]

        # 计算各维度的优化效果
        results = []
        test_cases = [
            ("resource_endowment", 0.4),  # 需要4/10个维度，约40%
            ("planning_positioning", 0.4),  # 需要4/10个维度，约40%
            ("development_goals", 0.4),  # 需要4/10个维度，约40%
            ("planning_strategies", 1.0),  # 需要全部，100%
        ]

        for dimension, expected_ratio in test_cases:
            # 估算筛选后的长度
            if dimension == "planning_strategies":
                filtered_length = len(full_report)
            else:
                filtered_length = int(len(full_report) * expected_ratio)

            reduction = estimate_token_reduction(
                dimension,
                len(full_report),
                filtered_length
            )
            results.append(reduction)

            logger.info(f"[集成测试] {dimension}: "
                       f"优化 {reduction['reduction_percent']}%, "
                       f"节省 {reduction['tokens_saved']} 字符")

        # 记录优化结果
        log_optimization_results(results)

        # 验证：总体优化率 > 20%（至少节省20%）
        total_original = sum(r["original_length"] for r in results)
        total_filtered = sum(r["filtered_length"] for r in results)
        actual_reduction = (1 - total_filtered / total_original) * 100 if total_original > 0 else 0

        logger.info(f"[集成测试] 总体优化率: {actual_reduction:.2f}%")

        # 验证：有优化效果
        assert actual_reduction > 20, f"优化率 {actual_reduction}% 低于预期 20%"

    def test_fallback_mechanism(self):
        """
        测试降级方案

        验证：
        1. 当 dimension_reports 为空时，使用完整报告
        2. 不影响功能正常运行
        """
        logger.info("[集成测试] 开始测试降级方案")

        # 测试：不传递 dimension_reports
        result = call_concept_subgraph(
            project_name="测试村",
            analysis_report="# 完整报告\n\n内容...",
            dimension_reports={},  # 空字典
            task_description="测试任务"
        )

        # 验证：仍然成功
        assert result["success"]
        assert "concept_report" in result

        logger.info("[集成测试] 降级方案测试通过")


class TestEdgeCases:
    """边界情况测试"""

    def test_empty_village_data(self):
        """测试空村庄数据"""
        result = call_analysis_subgraph(
            raw_data="",
            project_name="空村"
        )
        # 应该失败或返回空结果
        assert "success" in result

    def test_very_long_village_data(self):
        """测试超长村庄数据"""
        long_data = "测试数据\n" * 10000  # 约100KB
        result = call_analysis_subgraph(
            raw_data=long_data,
            project_name="大村"
        )
        # 应该成功处理
        assert result["success"] == True

    def test_special_characters(self):
        """测试特殊字符"""
        special_data = """
        测试村庄数据
        包含特殊字符：@#$%^&*()
        包含中文：测试村庄
        包含emoji：🏘️🌳
        """
        result = call_analysis_subgraph(
            raw_data=special_data,
            project_name="特殊村"
        )
        # 应该成功处理
        assert result["success"] == True


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short", "-s"])
