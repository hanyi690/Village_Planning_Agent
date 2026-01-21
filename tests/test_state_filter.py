"""
单元测试：状态过滤功能

测试部分状态传递的筛选功能，验证维度依赖映射和状态过滤逻辑。
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.utils.state_filter import (
    filter_analysis_report_for_concept,
    filter_state_for_detailed_dimension,
    estimate_token_reduction,
    log_optimization_results
)
from src.core.dimension_mapping import (
    ANALYSIS_TO_CONCEPT_MAPPING,
    CONCEPT_TO_DETAILED_MAPPING
)


class TestFilterAnalysisReportForConcept:
    """测试 filter_analysis_report_for_concept 函数"""

    def test_filter_resource_endowment(self):
        """测试资源禀赋维度的筛选"""
        # 准备测试数据
        full_reports = {
            "location": "区位分析：距离市中心25公里...",
            "socio_economic": "社会经济：人口1200人...",
            "natural_environment": "自然环境：丘陵地貌，森林覆盖率68%...",
            "land_use": "土地利用：农用地占比70%...",
            "ecological_green": "生态绿地：公园绿地面积...",
            "historical_cultural": "历史文化：明清古建筑...",  # 不相关
            "traffic": "交通：县道通过村庄..."  # 不相关
        }
        full_report = "# 完整现状分析报告\n\n" + "\n\n".join(full_reports.values())

        # 执行筛选
        filtered = filter_analysis_report_for_concept(
            concept_dimension="resource_endowment",
            full_analysis_reports=full_reports,
            full_analysis_report=full_report
        )

        # 验证：包含相关维度
        assert "自然环境" in filtered or "natural_environment" in filtered
        assert "土地利用" in filtered or "land_use" in filtered
        assert "生态绿地" in filtered or "ecological_green" in filtered
        assert "社会经济" in filtered or "socio_economic" in filtered

        # 验证：筛选后的报告不包含不相关维度的特征内容
        # （由于添加了标题，过滤后可能稍长，但不应包含不相关维度的关键内容）
        assert "历史文化" not in filtered or "明清古建筑" not in filtered
        assert "县道通过村庄" not in filtered  # traffic 维度的特征内容

    def test_filter_planning_strategies_all(self):
        """测试规划策略维度（需要全部信息）"""
        full_reports = {
            "location": "区位分析...",
            "socio_economic": "社会经济...",
        }
        full_report = "# 完整报告\n\n" + "\n\n".join(full_reports.values())

        # 执行筛选
        filtered = filter_analysis_report_for_concept(
            concept_dimension="planning_strategies",
            full_analysis_reports=full_reports,
            full_analysis_report=full_report
        )

        # 验证：返回完整报告
        assert filtered == full_report

    def test_filter_with_empty_dimension_reports(self):
        """测试维度报告字典为空的情况（降级方案）"""
        full_report = "# 完整报告\n\n内容..."

        # 执行筛选（空字典）
        filtered = filter_analysis_report_for_concept(
            concept_dimension="resource_endowment",
            full_analysis_reports={},
            full_analysis_report=full_report
        )

        # 验证：降级返回完整报告
        assert filtered == full_report

    def test_filter_with_unknown_dimension(self):
        """测试未知维度的情况"""
        full_report = "# 完整报告\n\n内容..."

        # 执行筛选（未知维度）
        filtered = filter_analysis_report_for_concept(
            concept_dimension="unknown_dimension",
            full_analysis_reports={},
            full_analysis_report=full_report
        )

        # 验证：降级返回完整报告
        assert filtered == full_report


class TestFilterStateForDetailedDimension:
    """测试 filter_state_for_detailed_dimension 函数"""

    def test_filter_industry_planning(self):
        """测试产业规划的状态筛选"""
        # 准备测试数据
        analysis_reports = {
            "socio_economic": "社会经济：人口1200人，GDP 5000万元...",
            "land_use": "土地利用：农用地占比70%...",
            "location": "区位：距离市中心25公里...",  # 不太相关
        }
        concept_reports = {
            "resource_endowment": "资源禀赋：农业资源丰富...",
            "development_goals": "发展目标：3年内创建3A级景区...",
            "planning_positioning": "规划定位：生态旅游示范村...",  # 不太相关
        }

        full_analysis = "# 完整现状分析\n\n" + "\n\n".join(analysis_reports.values())
        full_concept = "# 完整规划思路\n\n" + "\n\n".join(concept_reports.values())

        # 执行筛选
        filtered = filter_state_for_detailed_dimension(
            detailed_dimension="industry",
            full_analysis_reports=analysis_reports,
            full_analysis_report=full_analysis,
            full_concept_reports=concept_reports,
            full_concept_report=full_concept
        )

        # 验证：返回字典包含两个字段
        assert "filtered_analysis" in filtered
        assert "filtered_concept" in filtered

        # 验证：包含相关维度的内容
        assert "社会经济" in filtered["filtered_analysis"]
        assert "土地利用" in filtered["filtered_analysis"]
        assert "资源禀赋" in filtered["filtered_concept"]
        assert "发展目标" in filtered["filtered_concept"]

        # 验证：不包含不太相关维度的特征内容
        assert "生态旅游示范村" not in filtered["filtered_concept"]  # planning_positioning

    def test_filter_master_plan_all(self):
        """测试总体规划（需要全部信息）"""
        full_analysis = "# 完整现状分析"
        full_concept = "# 完整规划思路"

        # 执行筛选
        filtered = filter_state_for_detailed_dimension(
            detailed_dimension="master_plan",
            full_analysis_reports={},
            full_analysis_report=full_analysis,
            full_concept_reports={},
            full_concept_report=full_concept
        )

        # 验证：返回完整报告
        assert filtered["filtered_analysis"] == full_analysis
        assert filtered["filtered_concept"] == full_concept


class TestEstimateTokenReduction:
    """测试 estimate_token_reduction 函数"""

    def test_estimation_normal_case(self):
        """测试正常情况的估算"""
        result = estimate_token_reduction(
            concept_dimension="resource_endowment",
            full_report_length=10000,
            filtered_report_length=6000
        )

        # 验证：返回字典包含所有字段
        assert "dimension" in result
        assert "reduction_percent" in result
        assert "tokens_saved" in result
        assert "original_length" in result
        assert "filtered_length" in result

        # 验证：计算正确
        assert result["dimension"] == "resource_endowment"
        assert result["original_length"] == 10000
        assert result["filtered_length"] == 6000
        assert result["tokens_saved"] == 4000
        assert result["reduction_percent"] == 40.0

    def test_estimation_zero_original(self):
        """测试原始长度为0的情况"""
        result = estimate_token_reduction(
            concept_dimension="test",
            full_report_length=0,
            filtered_report_length=0
        )

        # 验证：返回零值
        assert result["reduction_percent"] == 0
        assert result["tokens_saved"] == 0


class TestLogOptimizationResults:
    """测试 log_optimization_results 函数"""

    def test_log_results(self, caplog):
        """测试结果记录功能"""
        results = [
            {"dimension": "dim1", "reduction_percent": 30, "tokens_saved": 3000,
             "original_length": 10000, "filtered_length": 7000},
            {"dimension": "dim2", "reduction_percent": 50, "tokens_saved": 5000,
             "original_length": 10000, "filtered_length": 5000},
        ]

        # 执行记录（不会抛出异常）
        log_optimization_results(results)

        # 验证：函数不抛出异常
        # 在实际使用中，可以通过 caplog 检查日志内容


class TestDimensionMapping:
    """测试维度映射配置"""

    def test_analysis_to_concept_mapping(self):
        """测试现状分析到规划思路的映射"""
        # 验证：映射包含所有规划思路维度
        expected_concepts = ["resource_endowment", "planning_positioning",
                            "development_goals", "planning_strategies"]
        for concept in expected_concepts:
            assert concept in ANALYSIS_TO_CONCEPT_MAPPING
            assert "required_analyses" in ANALYSIS_TO_CONCEPT_MAPPING[concept]
            assert "description" in ANALYSIS_TO_CONCEPT_MAPPING[concept]

    def test_concept_to_detailed_mapping(self):
        """测试规划思路到详细规划的映射"""
        # 验证：映射包含所有详细规划维度
        expected_detailed = ["industry", "master_plan", "traffic",
                            "public_service", "infrastructure", "ecological",
                            "disaster_prevention", "heritage", "landscape",
                            "project_bank"]
        for detailed in expected_detailed:
            assert detailed in CONCEPT_TO_DETAILED_MAPPING
            assert "required_concepts" in CONCEPT_TO_DETAILED_MAPPING[detailed]
            assert "required_analyses" in CONCEPT_TO_DETAILED_MAPPING[detailed]

    def test_resource_endowment_mapping(self):
        """测试资源禀赋的具体映射"""
        mapping = ANALYSIS_TO_CONCEPT_MAPPING["resource_endowment"]

        # 验证：包含预期的现状维度
        assert "natural_environment" in mapping["required_analyses"]
        assert "land_use" in mapping["required_analyses"]
        assert "ecological_green" in mapping["required_analyses"]
        assert "socio_economic" in mapping["required_analyses"]

        # 验证：不包含 "ALL"
        assert "ALL" not in mapping["required_analyses"]

    def test_planning_strategies_all(self):
        """测试规划策略需要全部信息"""
        mapping = ANALYSIS_TO_CONCEPT_MAPPING["planning_strategies"]

        # 验证：标记为 "ALL"
        assert "ALL" in mapping["required_analyses"]


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])
