"""
GIS 适配器初始化诊断脚本
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 60)
print("GIS 适配器初始化诊断")
print("=" * 60)

# Step 1: 直接测试 OSMSourceProvider
print("\n[Step 1] 直接测试 OSMSourceProvider...")
from src.tools.adapters.data_fetch.gis_fetch_adapter import OSMSourceProvider

provider = OSMSourceProvider()
print(f"  is_available: {provider.is_available()}")
print(f"  is_api_configured: {provider.is_api_configured()}")

# 尝试直接调用 fetch_boundary
print("\n[Step 2] 直接调用 OSMSourceProvider.fetch_boundary...")
result = provider.fetch_boundary("平远县", level="district")
print(f"  success: {result.success}")
if result.success:
    features = result.geojson.get('features', [])
    print(f"  geojson features: {len(features)}")
    if features:
        print(f"  first feature name: {features[0].get('properties', {}).get('name', 'N/A')}")
else:
    print(f"  error: {result.error}")

# Step 3: 测试 GISDataFetchAdapter
print("\n[Step 3] 测试 GISDataFetchAdapter 初始化流程...")
from src.tools.adapters.data_fetch.gis_fetch_adapter import GISDataFetchAdapter

adapter = GISDataFetchAdapter()
print(f"  adapter.is_available: {adapter.is_available}")
print(f"  adapter._status: {adapter.status}")
print(f"  adapter._osm_provider is None: {adapter._osm_provider is None}")

if adapter._osm_provider:
    print(f"  adapter._osm_provider.is_available(): {adapter._osm_provider.is_available()}")

# Step 4: 比较 execute() 和 run()
print("\n[Step 4] 比较 execute() 和 run() 方法...")

# 使用 execute() (当前测试脚本的方式)
print("  [execute() 方式]")
result_exec = adapter.execute(analysis_type="boundary_fetch", location="平远县")
print(f"    success: {result_exec.success}")
if not result_exec.success:
    print(f"    error: {result_exec.error}")

# 检查 execute() 后 _osm_provider 状态
print(f"    _osm_provider after execute(): {adapter._osm_provider is not None}")

# 使用 run() (正确的方式)
print("  [run() 方式]")
result_run = adapter.run(analysis_type="boundary_fetch", location="平远县")
print(f"    success: {result_run.success}")

# 检查 run() 后 _osm_provider 状态
print(f"    _osm_provider after run(): {adapter._osm_provider is not None}")
if adapter._osm_provider:
    print(f"    _osm_provider.is_available(): {adapter._osm_provider.is_available()}")

if result_run.success:
    features = result_run.data.get('geojson', {}).get('features', [])
    print(f"    geojson features: {len(features)}")
else:
    print(f"    error: {result_run.error}")

print("\n" + "=" * 60)
print("诊断结论:")
if not result_exec.success and result_run.success:
    print("  问题确认: execute() 失败但 run() 成功")
    print("  解决方案: 测试脚本应使用 adapter.run() 而非 adapter.execute()")
elif not result_exec.success and not result_run.success:
    print("  问题确认: OSM API 连接问题或地理编码失败")
    print("  解决方案: 检查网络连接和地理编码服务配置")
else:
    print("  测试通过: 数据获取功能正常")
print("=" * 60)