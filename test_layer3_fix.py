"""
测试 Layer 3 修复 - 验证配置键名一致性
"""

import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.config.dimension_metadata import get_dimension_config
from src.planners.generic_planner import GenericPlannerFactory


def test_dimension_config():
    """测试维度配置是否包含 prompt_key"""
    print("=" * 60)
    print("测试 1: 检查维度配置是否包含 prompt_key")
    print("=" * 60)

    test_dimensions = [
        ("location", 1),
        ("resource_endowment", 2),
        ("industry", 3),
        ("traffic", 3),
        ("infrastructure", 3),
        ("project_bank", 3),
    ]

    for dim_key, expected_layer in test_dimensions:
        config = get_dimension_config(dim_key)
        if config:
            has_prompt_key = "prompt_key" in config
            prompt_key = config.get("prompt_key", "MISSING")
            print(f"✓ {dim_key}: layer={config['layer']}, prompt_key={prompt_key}")
            assert config["layer"] == expected_layer, f"层级不匹配: {dim_key}"
            assert has_prompt_key, f"缺少 prompt_key: {dim_key}"
            
            # 验证 Layer 3 的 prompt_key 与 dimension_key 一致
            if expected_layer == 3:
                assert prompt_key == dim_key, f"Layer 3 键名不一致: {dim_key} -> {prompt_key}"
                print(f"  ✓ Layer 3 键名一致: {dim_key} == {prompt_key}")
        else:
            print(f"✗ {dim_key}: 配置未找到")
            raise AssertionError(f"配置未找到: {dim_key}")

    print("\n✓ 所有维度配置检查通过\n")


def test_planner_initialization():
    """测试 GenericPlanner 能正确初始化"""
    print("=" * 60)
    print("测试 2: 检查 GenericPlanner 初始化")
    print("=" * 60)

    test_dimensions = [
        ("location", 1),
        ("resource_endowment", 2),
        ("industry", 3),
        ("traffic", 3),
        ("infrastructure", 3),
        ("project_bank", 3),
    ]

    for dim_key, expected_layer in test_dimensions:
        try:
            planner = GenericPlannerFactory.create_planner(dim_key)
            print(f"✓ {dim_key}: 成功初始化 planner")
            print(f"  - layer: {planner.get_layer()}")
            print(f"  - dimension_key: {planner.dimension_key}")
            print(f"  - prompt_key: {planner.prompt_key}")
            print(f"  - result_key: {planner.get_result_key()}")

            assert planner.get_layer() == expected_layer, f"层级不匹配: {dim_key}"
            assert planner.prompt_key is not None, f"prompt_key 为 None: {dim_key}"
            
            # 验证 prompt_key 与 dimension_key 一致
            if expected_layer == 3:
                assert planner.prompt_key == planner.dimension_key, f"键名不一致: {planner.dimension_key} != {planner.prompt_key}"
                print(f"  ✓ 键名一致: {planner.dimension_key} == {planner.prompt_key}")
        except Exception as e:
            print(f"✗ {dim_key}: 初始化失败 - {e}")
            raise

    print("\n✓ 所有规划器初始化检查通过\n")


def test_prompt_loading():
    """测试 Prompt 模板加载"""
    print("=" * 60)
    print("测试 3: 检查 Prompt 模板加载")
    print("=" * 60)

    test_dimensions = [
        ("location", 1),
        ("resource_endowment", 2),
        ("industry", 3),
        ("traffic", 3),
    ]

    for dim_key, expected_layer in test_dimensions:
        try:
            planner = GenericPlannerFactory.create_planner(dim_key)

            if expected_layer == 1:
                # Layer 1 应该有 prompt_template
                has_template = bool(planner.prompt_template)
                print(f"✓ {dim_key}: prompt_template 长度={len(planner.prompt_template)}")
                assert has_template, f"Layer 1 应该有 prompt_template: {dim_key}"

            elif expected_layer == 2:
                # Layer 2 应该有 prompt_template
                has_template = bool(planner.prompt_template)
                print(f"✓ {dim_key}: prompt_template 长度={len(planner.prompt_template)}")
                assert has_template, f"Layer 2 应该有 prompt_template: {dim_key}"

            elif expected_layer == 3:
                # Layer 3 使用函数式 prompt，prompt_template 可以为空
                print(f"✓ {dim_key}: 使用函数式 prompt（prompt_template 可以为空）")

        except Exception as e:
            print(f"✗ {dim_key}: Prompt 加载失败 - {e}")
            raise

    print("\n✓ 所有 Prompt 加载检查通过\n")


def test_key_consistency():
    """测试键名一致性"""
    print("=" * 60)
    print("测试 4: 检查键名一致性")
    print("=" * 60)

    # 测试所有 Layer 3 维度
    layer3_dimensions = [
        "industry", "spatial_structure", "land_use_planning", 
        "settlement_planning", "traffic", "public_service", 
        "infrastructure", "ecological", "disaster_prevention", 
        "heritage", "landscape", "project_bank"
    ]

    for dim_key in layer3_dimensions:
        config = get_dimension_config(dim_key)
        if config:
            prompt_key = config.get("prompt_key")
            print(f"✓ {dim_key}: prompt_key={prompt_key}")
            
            # 验证键名一致
            assert prompt_key == dim_key, f"键名不一致: {dim_key} != {prompt_key}"
        else:
            print(f"✗ {dim_key}: 配置未找到")
            raise AssertionError(f"配置未找到: {dim_key}")

    print("\n✓ 所有 Layer 3 键名一致性检查通过\n")


if __name__ == "__main__":
    print("\n开始 Layer 3 统一配置验证...\n")

    try:
        test_dimension_config()
        test_planner_initialization()
        test_prompt_loading()
        test_key_consistency()

        print("=" * 60)
        print("✓✓✓ 所有测试通过！Layer 3 统一配置成功 ✓✓✓")
        print("=" * 60)

    except Exception as e:
        print("\n" + "=" * 60)
        print("✗✗✗ 测试失败！")
        print("=" * 60)
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
