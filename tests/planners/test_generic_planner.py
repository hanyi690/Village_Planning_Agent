"""
GenericPlanner 单元测试

验证通用规划器的功能：
1. 所有 28 个维度都能正确加载
2. 每层的验证逻辑正确
3. Prompt 构建正确
4. 工具钩子功能正常
"""

import pytest
from src.planners.generic_planner import GenericPlanner, GenericPlannerFactory


class TestGenericPlanner:
    """测试 GenericPlanner 类"""

    def test_all_dimensions_loadable(self):
        """测试所有 28 个维度都能正确加载"""
        all_dims = [
            # Layer 1: 现状分析 (12个)
            "location", "socio_economic", "villager_wishes", "superior_planning",
            "natural_environment", "land_use", "traffic", "public_services",
            "infrastructure", "ecological_green", "architecture", "historical_culture",
            # Layer 2: 规划思路 (4个)
            "resource_endowment", "planning_positioning", "development_goals", "planning_strategies",
            # Layer 3: 详细规划 (12个)
            "industry", "spatial_structure", "land_use_planning", "settlement_planning",
            "traffic_planning", "public_service", "infrastructure_planning", "ecological",
            "disaster_prevention", "heritage", "landscape", "project_bank"
        ]

        for dim in all_dims:
            planner = GenericPlanner(dim)
            assert planner is not None
            assert planner.dimension_key == dim
            assert planner.layer in [1, 2, 3]

    def test_layer_validation(self):
        """测试每层的验证逻辑"""
        # Layer 1
        planner_l1 = GenericPlanner("location")
        assert planner_l1.layer == 1
        assert planner_l1.validate_state({"raw_data": "test data"})[0] == True
        assert planner_l1.validate_state({})[0] == False

        # Layer 2
        planner_l2 = GenericPlanner("resource_endowment")
        assert planner_l2.layer == 2
        state = {
            "analysis_report": "report",
            "task_description": "task",
            "constraints": "constraints"
        }
        assert planner_l2.validate_state(state)[0] == True
        assert planner_l2.validate_state({})[0] == False

        # Layer 3
        planner_l3 = GenericPlanner("industry")
        assert planner_l3.layer == 3
        state["completed_plans"] = {}
        # industry 没有前序依赖，所以应该通过
        assert planner_l3.validate_state(state)[0] == True

        # project_bank 依赖于所有其他维度，所以应该失败
        planner_l3_bank = GenericPlanner("project_bank")
        assert planner_l3_bank.validate_state(state)[0] == False  # 依赖不满足

    def test_prompt_building_layer1(self):
        """测试 Layer 1 的 Prompt 构建"""
        planner = GenericPlanner("location")
        state = {"raw_data": "测试村庄数据"}

        prompt = planner.build_prompt(state)
        assert "测试村庄数据" in prompt
        assert "区位分析" in prompt

    def test_prompt_building_layer2(self):
        """测试 Layer 2 的 Prompt 构建"""
        planner = GenericPlanner("resource_endowment")
        state = {
            "analysis_report": "分析报告",
            "dimension_reports": {"location": "区位分析"},
            "task_description": "制定规划",
            "constraints": "无约束"
        }

        prompt = planner.build_prompt(state)
        assert "资源禀赋" in prompt
        assert "制定规划" in prompt

    def test_prompt_building_layer3(self):
        """测试 Layer 3 的 Prompt 构建"""
        planner = GenericPlanner("industry")
        state = {
            "project_name": "测试村庄",
            "analysis_report": "分析报告",
            "planning_concept": "规划思路",
            "dimension_reports": {},
            "concept_dimension_reports": {},
            "completed_plans": {},
            "constraints": "无约束"
        }

        prompt = planner.build_prompt(state)
        assert "产业规划" in prompt
        assert "测试村庄" in prompt

    def test_result_key(self):
        """测试结果键名"""
        # Layer 1 和 Layer 2
        planner_l1 = GenericPlanner("location")
        assert planner_l1.get_result_key() == "analysis_result"

        planner_l2 = GenericPlanner("resource_endowment")
        assert planner_l2.get_result_key() == "concept_result"

        # Layer 3
        planner_l3 = GenericPlanner("industry")
        assert planner_l3.get_result_key() == "dimension_result"


class TestGenericPlannerFactory:
    """测试 GenericPlannerFactory 类"""

    def test_create_single_planner(self):
        """测试创建单个规划器"""
        planner = GenericPlannerFactory.create_planner("location")
        assert isinstance(planner, GenericPlanner)
        assert planner.dimension_key == "location"

    def test_create_all_planners(self):
        """测试批量创建所有规划器"""
        all_planners = GenericPlannerFactory.create_all_planners()
        assert len(all_planners) == 28  # 12 + 4 + 12

    def test_create_planners_by_layer(self):
        """测试按层级创建规划器"""
        # Layer 1
        layer1_planners = GenericPlannerFactory.create_all_planners(layer=1)
        assert len(layer1_planners) == 12

        # Layer 2
        layer2_planners = GenericPlannerFactory.create_all_planners(layer=2)
        assert len(layer2_planners) == 4

        # Layer 3
        layer3_planners = GenericPlannerFactory.create_all_planners(layer=3)
        assert len(layer3_planners) == 12


class TestToolRegistry:
    """测试 ToolRegistry 类"""

    def test_list_tools(self):
        """测试列出工具"""
        from src.tools.registry import ToolRegistry

        tools = ToolRegistry.list_tools()
        assert isinstance(tools, dict)
        # 应该包含内置工具
        assert "population_model_v1" in tools or "gis_coverage_calculator" in tools

    def test_execute_tool(self):
        """测试执行工具"""
        from src.tools.registry import ToolRegistry

        # 测试人口模型工具
        context = {"socio_economic": "人口：1000人"}
        result = ToolRegistry.execute_tool("population_model_v1", context)
        assert "人口预测结果" in result
        assert "1000" in result


if __name__ == "__main__":
    # 运行测试
    test = TestGenericPlanner()
    print("测试所有维度加载...")
    test.test_all_dimensions_loadable()
    print("✓ 所有 28 个维度都能正确加载")

    print("\n测试层级验证...")
    test.test_layer_validation()
    print("✓ 层级验证正确")

    print("\n测试 Prompt 构建...")
    test.test_prompt_building_layer1()
    test.test_prompt_building_layer2()
    test.test_prompt_building_layer3()
    print("✓ Prompt 构建正确")

    print("\n测试工厂类...")
    factory_test = TestGenericPlannerFactory()
    factory_test.test_create_all_planners()
    print("✓ 工厂类功能正常")

    print("\n✅ 所有测试通过！")
