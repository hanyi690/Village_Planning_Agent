"""
GIS 脚本生成测试脚本

测试 LLM 生成 GIS 操作代码的能力
"""

import os
import sys

# 添加项目根目录到 Python 路径
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, project_root)

from dotenv import load_dotenv
load_dotenv()

from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter


def test_smart_fetch():
    """测试智能数据获取"""
    print("\n" + "="*60)
    print(" 智能数据获取测试")
    print("="*60)

    adapter = GISDataFetchAdapter()

    # 测试 1: 边界获取
    print("\n【测试1】边界获取 - 平远县")
    print("-" * 40)

    result = adapter.execute("boundary_fetch", location="平远县", level="county")

    if result.success:
        print(f"✅ 成功")
        print(f"  行政区划代码: {result.metadata.get('admin_code', 'N/A')}")
        print(f"  级别: {result.metadata.get('level', 'N/A')}")
        print(f"  中心坐标: {result.metadata.get('center', 'N/A')}")

        geojson = result.data.get("geojson")
        if geojson:
            features = geojson.get("features", [])
            print(f"  要素数量: {len(features)}")
    else:
        print(f"❌ 失败: {result.error}")

    # 测试 2: 乡镇边界获取
    print("\n【测试2】边界获取 - 泗水镇")
    print("-" * 40)

    result = adapter.execute("boundary_fetch", location="泗水镇", level="town")

    if result.success:
        print(f"✅ 成功")
        print(f"  名称: {result.metadata.get('location', 'N/A')}")
    else:
        print(f"❌ 失败: {result.error}")

    # 测试 3: 村级边界获取
    print("\n【测试3】边界获取 - 金田村")
    print("-" * 40)

    result = adapter.execute("boundary_fetch", location="金田村", level="village")

    if result.success:
        print(f"✅ 成功")
        print(f"  名称: {result.metadata.get('location', 'N/A')}")
    else:
        print(f"❌ 失败: {result.error}")


def test_code_templates():
    """测试代码模板"""
    print("\n" + "="*60)
    print(" 代码模板测试")
    print("="*60)

    adapter = GISDataFetchAdapter()

    # 查看边界获取代码模板
    print("\n【边界获取代码模板】")
    print("-" * 40)

    template = adapter._template_boundary_code("测试县")
    print(template[:500] + "..." if len(template) > 500 else template)


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
        test_smart_fetch()
        test_code_templates()
    except Exception as e:
        print(f"\n❌ 测试异常: {e}")
        import traceback
        traceback.print_exc()
        return False

    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)