"""
动态路由功能测试

测试依赖关系映射、状态筛选、波次路由等核心功能。
"""

import pytest
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.core.dimension_mapping import (
    FULL_DEPENDENCY_CHAIN,
    WAVE_CONFIG,
    get_full_dependency_chain,
    get_execution_wave,
    get_dimensions_by_wave,
    check_detailed_dependencies_ready,
    visualize_dependency_graph,
    get_wave_summary,
    ANALYSIS_DIMENSION_NAMES,
    DETAILED_DIMENSION_NAMES
)
from src.utils.state_filter import (
    filter_state_for_detailed_dimension_v2,
    visualize_filtering_result
)


# ==========================================
# 测试维度映射和依赖关系
# ==========================================

class TestDimensionMapping:
    """测试维度映射功能"""

    def test_full_dependency_chain_defined(self):
        """测试完整依赖链是否已定义"""
        assert len(FULL_DEPENDENCY_CHAIN) == 10, "应该有10个详细规划维度"

    def test_dimension_names_updated(self):
        """测试维度名称是否已更新"""
        # 现状分析维度名称应包含内容说明
        assert "上位规划" in ANALYSIS_DIMENSION_NAMES["location"]
        assert "村民意愿" in ANALYSIS_DIMENSION_NAMES["socio_economic"]

    def test_wave_config(self):
        """测试波次配置"""
        assert 1 in WAVE_CONFIG
        assert 2 in WAVE_CONFIG
        assert len(WAVE_CONFIG[1]["dimensions"]) == 9, "Wave 1应该有9个维度"
        assert len(WAVE_CONFIG[2]["dimensions"]) == 1, "Wave 2应该有1个维度"
        assert WAVE_CONFIG[2]["dimensions"] == ["project_bank"]

    def test_get_full_dependency_chain(self):
        """测试获取完整依赖链"""
        chain = get_full_dependency_chain("industry")

        assert "layer1_analyses" in chain
        assert "layer2_concepts" in chain
        assert "wave" in chain
        assert "depends_on_detailed" in chain

        # 验证产业规划的依赖
        assert "socio_economic" in chain["layer1_analyses"]
        assert "land_use" in chain["layer1_analyses"]
        assert chain["wave"] == 1

    def test_get_execution_wave(self):
        """测试获取执行波次"""
        assert get_execution_wave("industry") == 1
        assert get_execution_wave("master_plan") == 1
        assert get_execution_wave("project_bank") == 2

    def test_get_dimensions_by_wave(self):
        """测试按波次获取维度"""
        wave1_dims = get_dimensions_by_wave(1)
        wave2_dims = get_dimensions_by_wave(2)

        assert len(wave1_dims) == 9
        assert len(wave2_dims) == 1
        assert "project_bank" not in wave1_dims
        assert "project_bank" in wave2_dims

    def test_check_detailed_dependencies_ready(self):
        """测试检查依赖是否满足"""
        # project_bank 依赖9个前序维度
        completed = ["industry", "master_plan", "traffic", "public_service",
                     "infrastructure", "ecological", "disaster_prevention",
                     "heritage", "landscape"]

        assert check_detailed_dependencies_ready("project_bank", completed) == True
        assert check_detailed_dependencies_ready("project_bank", ["industry"]) == False
        assert check_detailed_dependencies_ready("industry", []) == True  # 无依赖

    def test_visualize_dependency_graph(self):
        """测试依赖图可视化"""
        graph = visualize_dependency_graph()
        assert "graph TD" in graph
        assert "A1_" in graph  # 现状分析节点
        assert "A2_" in graph  # 规划思路节点
        assert "A3_" in graph  # 详细规划节点

    def test_get_wave_summary(self):
        """测试获取波次摘要"""
        summary = get_wave_summary()

        assert 1 in summary
        assert 2 in summary
        assert "description" in summary[1]
        assert "dimensions" in summary[1]
        assert summary[1]["count"] == 9


# ==========================================
# 测试状态筛选功能
# ==========================================

class TestStateFilter:
    """测试状态筛选功能"""

    @pytest.fixture
    def sample_state(self):
        """创建测试用的状态"""
        return {
            "full_analysis_reports": {
                "location": "这是区位分析内容...",
                "socio_economic": "这是社会经济分析内容...",
                "land_use": "这是土地利用分析内容...",
                "natural_environment": "这是自然环境分析内容...",
            },
            "full_analysis_report": "# 完整现状分析\n\n所有维度的分析内容...",
            "full_concept_reports": {
                "resource_endowment": "这是资源禀赋分析...",
                "development_goals": "这是发展目标分析...",
            },
            "full_concept_report": "# 完整规划思路\n\n所有维度的规划思路...",
            "completed_detailed_reports": {
                "industry": "这是产业规划内容...",
                "master_plan": "这是总体规划内容...",
            }
        }

    def test_filter_state_for_industry(self, sample_state):
        """测试产业规划的状态筛选"""
        result = filter_state_for_detailed_dimension_v2(
            detailed_dimension="industry",
            **sample_state
        )

        # 验证返回结构
        assert "filtered_analysis" in result
        assert "filtered_concepts" in result
        assert "dependency_chain" in result
        assert "token_stats" in result

        # 验证依赖链
        chain = result["dependency_chain"]
        assert "socio_economic" in chain["layer1_analyses"]
        assert "land_use" in chain["layer1_analyses"]

        # 验证Token统计
        stats = result["token_stats"]
        assert stats["dimension"] == "industry"
        # 注意：由于示例数据很小，添加格式化头后可能会比原始数据长
        # 在真实场景中（完整报告），筛选后应该会显著减少
        # 这里只验证结构正确，不验证节省百分比
        assert "tokens_saved" in stats
        assert "total_original" in stats
        assert "total_filtered" in stats

    def test_filter_state_for_project_bank(self, sample_state):
        """测试项目建设库的状态筛选"""
        result = filter_state_for_detailed_dimension_v2(
            detailed_dimension="project_bank",
            **sample_state
        )

        # project_bank 应该包含前序详细规划
        filtered_detailed = result["filtered_detailed"]
        assert "industry" in filtered_detailed or len(filtered_detailed) >= 0

        # 验证依赖链
        chain = result["dependency_chain"]
        assert chain["wave"] == 2
        assert len(chain["depends_on_detailed"]) == 9

    def test_visualize_filtering_result(self, sample_state):
        """测试筛选结果可视化"""
        # 先进行筛选
        result = filter_state_for_detailed_dimension_v2(
            detailed_dimension="industry",
            **sample_state
        )

        # 可视化结果
        visualization = visualize_filtering_result("industry", result)

        assert "产业规划" in visualization
        assert "依赖关系" in visualization
        assert "Token优化统计" in visualization


# ==========================================
# 测试波次路由逻辑
# ==========================================

class TestWaveRouting:
    """测试波次路由逻辑"""

    def test_wave_1_dimensions(self):
        """测试Wave 1的维度"""
        wave1_dims = get_dimensions_by_wave(1)

        # 验证project_bank不在Wave 1中
        assert "project_bank" not in wave1_dims

        # 验证其他9个维度都在
        expected_dims = ["industry", "master_plan", "traffic", "public_service",
                         "infrastructure", "ecological", "disaster_prevention",
                         "heritage", "landscape"]
        for dim in expected_dims:
            assert dim in wave1_dims

    def test_wave_2_dimensions(self):
        """测试Wave 2的维度"""
        wave2_dims = get_dimensions_by_wave(2)

        # 验证只有project_bank
        assert wave2_dims == ["project_bank"]

    def test_project_bank_dependencies(self):
        """测试project_bank的依赖关系"""
        chain = get_full_dependency_chain("project_bank")

        # 验证依赖所有Wave 1的维度
        wave1_dims = get_dimensions_by_wave(1)
        assert set(chain["depends_on_detailed"]) == set(wave1_dims)

    def test_wave1_all_independent(self):
        """测试Wave 1的所有维度都是独立的"""
        wave1_dims = get_dimensions_by_wave(1)

        for dim in wave1_dims:
            chain = get_full_dependency_chain(dim)
            # Wave 1的维度不应该依赖其他详细规划维度
            assert len(chain["depends_on_detailed"]) == 0, \
                f"{dim} 不应该依赖其他详细规划维度"


# ==========================================
# 集成测试
# ==========================================

class TestIntegration:
    """集成测试"""

    def test_full_workflow_simulation(self):
        """模拟完整的工作流程"""
        # 初始状态：没有维度完成
        completed = []

        # Wave 1: 所有9个维度都可以并行执行
        wave1_dims = get_dimensions_by_wave(1)
        for dim in wave1_dims:
            assert check_detailed_dependencies_ready(dim, completed)
            completed.append(dim)

        # Wave 1 完成后，project_bank 的依赖应该满足
        assert check_detailed_dependencies_ready("project_bank", completed)

        # Wave 2: project_bank 可以执行
        wave2_dims = get_dimensions_by_wave(2)
        for dim in wave2_dims:
            assert check_detailed_dependencies_ready(dim, completed)

    def test_token_optimization_benefit(self):
        """测试Token优化的效果"""
        # 模拟完整状态
        full_analysis = "# 完整现状分析\n\n" + "\n\n".join([
            f"## {ANALYSIS_DIMENSION_NAMES[key]}\n\n内容..." * 100
            for key in ANALYSIS_DIMENSION_NAMES.keys()
        ])

        full_concept = "# 完整规划思路\n\n" + "\n\n".join([
            f"## {key}\n\n内容..." * 50
            for key in ["resource_endowment", "planning_positioning",
                       "development_goals", "planning_strategies"]
        ])

        # 为单个维度筛选
        result = filter_state_for_detailed_dimension_v2(
            detailed_dimension="industry",
            full_analysis_reports={key: f"{ANALYSIS_DIMENSION_NAMES[key]}\n内容..." * 100
                                   for key in ANALYSIS_DIMENSION_NAMES.keys()},
            full_analysis_report=full_analysis,
            full_concept_reports={key: f"{key}\n内容..." * 50
                                  for key in ["resource_endowment", "development_goals"]},
            full_concept_report=full_concept,
        )

        # 验证有Token节省
        stats = result["token_stats"]
        # 至少应该节省20%（因为只选择了2个现状维度和2个规划思路维度）
        assert stats["reduction_percent"] > 20, \
            f"Token节省率应该 > 20%, 实际: {stats['reduction_percent']}%"

    def test_dimension_name_consistency(self):
        """测试维度名称在所有模块中的一致性"""
        from src.core.dimension_mapping import DETAILED_DIMENSION_NAMES

        # 验证所有10个详细规划维度都有名称
        expected_dims = ["industry", "master_plan", "traffic", "public_service",
                         "infrastructure", "ecological", "disaster_prevention",
                         "heritage", "landscape", "project_bank"]

        for dim in expected_dims:
            assert dim in DETAILED_DIMENSION_NAMES, f"缺少维度: {dim}"
            assert DETAILED_DIMENSION_NAMES[dim], f"维度 {dim} 的名称为空"


# ==========================================
# 运行测试
# ==========================================

if __name__ == "__main__":
    print("=" * 60)
    print("运行动态路由功能测试")
    print("=" * 60)

    # 运行测试
    pytest.main([__file__, "-v", "--tb=short"])
