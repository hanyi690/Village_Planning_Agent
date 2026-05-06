"""
Test Spatial Text Parser - 解析完整规划报告提取空间信息

测试脚本：
1. 加载 layer3_完整报告.md
2. 使用 SpatialTextParser 解析提取空间信息
3. 输出 JSON 结构化数据
"""

import json
import sys
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tools.core.spatial_text_parser import SpatialTextParser


def main():
    """主测试函数"""
    print("=" * 60)
    print("测试: SpatialTextParser - 从完整报告提取空间信息")
    print("=" * 60)

    # 读取完整报告
    report_path = project_root / "docs" / "layer3_完整报告.md"
    if not report_path.exists():
        print(f"错误: 报告文件不存在 - {report_path}")
        return

    with open(report_path, "r", encoding="utf-8") as f:
        report_text = f.read()

    print(f"报告长度: {len(report_text)} 字符")

    # 创建解析器（不使用地理编码，避免API调用）
    parser = SpatialTextParser(village_name="金田村", city="平远县")

    # 解析报告
    print("\n开始解析...")
    result = parser.parse_report(report_text)

    # 输出提取结果
    print("\n" + "-" * 40)
    print("提取结果:")
    print(f"  功能区: {len(result.zones)} 个")
    for zone in result.zones[:5]:  # 只显示前5个
        print(f"    - {zone.zone_type}: {zone.name} ({zone.percentage}% / {zone.area_ha}ha)")

    print(f"  设施点: {len(result.facilities)} 个")
    for facility in result.facilities[:5]:
        print(f"    - {facility.facility_type}: {facility.status}")

    print(f"  发展轴线: {len(result.axes)} 个")
    for axis in result.axes[:5]:
        print(f"    - {axis.axis_type}: {axis.name}")

    print(f"  敏感区: {len(result.sensitivities)} 个")
    for sensitivity in result.sensitivities[:5]:
        print(f"    - {sensitivity.sensitivity_level}: {sensitivity.zone_type} ({sensitivity.count}个)")

    print(f"  居民点: {len(result.settlements)} 个")
    for settlement in result.settlements[:5]:
        print(f"    - {settlement.settlement_type}: {settlement.name}")

    # 转换为字典（不调用地理编码）
    extraction_dict = {
        "zones": [
            {
                "name": z.name,
                "zone_type": z.zone_type,
                "percentage": z.percentage,
                "area_ha": z.area_ha,
                "description": z.description,
            }
            for z in result.zones
        ],
        "facilities": [
            {
                "name": f.name,
                "facility_type": f.facility_type,
                "status": f.status,
                "location_hint": f.location_hint,
                "description": f.description,
            }
            for f in result.facilities
        ],
        "axes": [
            {
                "name": a.name,
                "axis_type": a.axis_type,
                "path_hint": a.path_hint,
                "description": a.description,
            }
            for a in result.axes
        ],
        "sensitivities": [
            {
                "zone_type": s.zone_type,
                "sensitivity_level": s.sensitivity_level,
                "count": s.count,
                "description": s.description,
            }
            for s in result.sensitivities
        ],
        "settlements": [
            {
                "name": s.name,
                "settlement_type": s.settlement_type,
                "description": s.description,
            }
            for s in result.settlements
        ],
        "raw_data": result.raw_data,
    }

    # 保存输出
    output_path = project_root / "output" / "spatial_extraction.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(extraction_dict, f, ensure_ascii=False, indent=2)

    print(f"\n输出已保存: {output_path}")
    print("=" * 60)
    print("测试完成!")
    print("=" * 60)


if __name__ == "__main__":
    main()