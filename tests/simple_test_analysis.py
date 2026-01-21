"""
分析子图简化测试 - 生成完整的现状分析报告

使用方法：
    python -m tests.simple_test_analysis
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.subgraphs.analysis_subgraph import call_analysis_subgraph
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 测试数据
TEST_VILLAGE_DATA = """
某某村基本情况：

某某村位于XX市XX区，距离市中心25公里，距离高速路口12公里。县道穿村而过，交通便利。

全村320户，户籍人口1200人，常住人口980人，60岁以上老人280人。2024年村集体收入85万元，农民人均纯收入18000元/年。主要产业为水稻种植、茶叶种植、乡村旅游。

丘陵地貌，平均海拔150米，年均气温18.5℃，年降水量1600mm。森林覆盖率68%，有XX河穿村而过。

耕地2800亩，建设用地450亩，林地3200亩，水域230亩。土地利用以农业和林业为主。

对外道路为1条县道，村内道路硬化率80%。距离高铁站30公里。

有村小学、卫生室、文化活动中心、老年活动中心各1个。体育设施有篮球场1个，健身路径2处。

自来水入户率95%，无污水收集处理系统。4G网络全覆盖，宽带覆盖率60%。

村庄绿化率35%，有村级公园1个（15亩），百年以上古树8棵。

总建筑380栋，传统建筑45栋，危房12栋。建筑风格以江南民居为主。

始建于南宋，距今800余年。有区级文保单位古祠堂1处，传统制茶技艺为非遗项目。
"""


def main():
    """主测试函数"""
    print("\n" + "="*80)
    print("现状分析子图简化测试")
    print("="*80 + "\n")

    project_name = "某某村"
    raw_data = TEST_VILLAGE_DATA.strip()

    print(f"项目名称: {project_name}")
    print(f"输入数据长度: {len(raw_data)} 字符")
    print("\n开始分析...\n")

    start_time = datetime.now()

    try:
        # 调用分析子图
        result = call_analysis_subgraph(
            project_name=project_name,
            raw_data=raw_data
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # 输出结果
        print("\n" + "="*80)
        print("分析完成！")
        print("="*80)
        print(f"执行时间: {duration:.2f} 秒")
        print(f"报告长度: {len(result.get('analysis_report', ''))} 字符")

        # 安全地获取完成维度
        completed = result.get('completed_dimensions', [])
        if completed:
            print(f"完成的维度: {', '.join(completed)}")
        else:
            print("完成的维度: 信息不可用")

        print()

        # 保存报告
        output_dir = Path("tests/output/analysis")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"analysis_simple_{timestamp}.md"

        report_content = result.get('analysis_report', '')

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# {project_name} 现状分析报告\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
            f.write("---\n\n")
            f.write(report_content)

        print(f"报告已保存到: {output_file}")

        if report_content:
            print("\n" + "="*80)
            print("完整报告预览（前3000字符）:")
            print("="*80 + "\n")
            print(report_content[:3000])
            if len(report_content) > 3000:
                print("\n... (完整报告已保存到文件)")
        else:
            print("\n⚠️  警告：报告内容为空，可能存在配置问题")

        return 0

    except Exception as e:
        print(f"\n❌ 分析失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
