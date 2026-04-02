"""
可达性分析测试脚本

测试金田村到周边区域的可达性分析
"""

import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from src.tools.adapters.analysis.accessibility_adapter import AccessibilityAdapter


def test_jintian_accessibility():
    """测试金田村可达性分析"""
    print("\n" + "="*60)
    print(" 金田村可达性分析测试")
    print("="*60)

    adapter = AccessibilityAdapter()

    # 金田村坐标（平远县泗水镇）
    jintian_center = (115.891, 24.567)

    # 测试 1: 驾车可达性分析
    print("\n【测试1】驾车可达性分析")
    print("-" * 40)

    destinations = [
        (116.1, 24.3, "梅州市区"),
        (115.7, 24.5, "平远县城"),
        (116.0, 24.6, "蕉岭县"),
    ]

    result = adapter.execute(
        "driving_accessibility",
        origin=jintian_center,
        destinations=[(d[0], d[1]) for d in destinations],
        max_time=60,
        max_distance=100
    )

    if result.success:
        print(f"✅ 分析成功")
        matrix = result.data.get("accessibility_matrix", [])
        for i, item in enumerate(matrix):
            dest_name = destinations[i][2] if i < len(destinations) else "未知"
            status = "可达" if item.get("is_reachable") else "不可达"
            distance = item.get("distance_km", 0)
            time = item.get("time_minutes", 0)
            print(f"  {dest_name}: {distance:.1f}km, {time:.0f}分钟 ({status})")
    else:
        print(f"❌ 分析失败: {result.error}")

    # 测试 2: 服务半径覆盖分析
    print("\n【测试2】服务半径覆盖分析")
    print("-" * 40)

    result = adapter.execute(
        "service_coverage",
        center=jintian_center,
        radius=5000,  # 5公里
        poi_type="学校"
    )

    if result.success:
        print(f"✅ 分析成功")
        summary = result.data.get("summary", {})
        print(f"  搜索半径: {result.metadata.get('radius', 0)}m")
        print(f"  设施数量: {summary.get('total_facilities', 0)}")
        print(f"  覆盖率: {summary.get('coverage_rate', 0) * 100:.1f}%")

        facilities = result.data.get("facilities", [])
        for i, f in enumerate(facilities[:5]):
            print(f"  {i+1}. {f.get('name', '未命名')} ({f.get('distance', 0):.0f}m)")
    else:
        print(f"❌ 分析失败: {result.error}")

    # 测试 3: POI 覆盖分析
    print("\n【测试3】多类型 POI 覆盖分析")
    print("-" * 40)

    result = adapter.execute(
        "poi_coverage",
        center=jintian_center,
        poi_types=["学校", "医院", "公园", "超市"]
    )

    if result.success:
        print(f"✅ 分析成功")
        coverage = result.data.get("coverage_by_type", {})
        for poi_type, info in coverage.items():
            status = "✓ 有覆盖" if info["in_range"] > 0 else "✗ 无覆盖"
            print(f"  {poi_type}: 范围内 {info['in_range']} 个 (半径 {info['radius']}m) {status}")
    else:
        print(f"❌ 分析失败: {result.error}")


def main():
    """主函数"""
    # 检查 API Key
    api_key = os.getenv("TIANDITU_API_KEY", "")
    if not api_key:
        print("\n⚠️ 警告: TIANDITU_API_KEY 未配置，测试可能失败")
        print("请在 .env 文件中设置 TIANDITU_API_KEY")
    else:
        print(f"\n✅ API Key 已配置: {api_key[:8]}...")

    try:
        test_jintian_accessibility()
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)