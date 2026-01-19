"""
概念子图简化测试 - 生成完整的规划思路报告

使用方法：
    python -m test.simple_test_concept
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.subgraphs.concept_subgraph import call_concept_subgraph
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 测试数据（使用分析报告的输出）
TEST_ANALYSIS_REPORT = """
# 某某村现状综合分析报告

## 一、总体概况

某某村位于XX市XX区，距离市中心25公里，交通便利。全村320户，户籍人口1200人，常住人口980人。村域面积6.2平方公里，耕地2800亩，林地3200亩。

## 二、社会经济

2024年村集体收入85万元，农民人均纯收入18000元/年。主要产业为水稻种植、茶叶种植、乡村旅游。人口老龄化问题较为突出，60岁以上老人280人。

## 三、自然条件

丘陵地貌，平均海拔150米，年均气温18.5℃，年降水量1600mm。森林覆盖率68%，XX河穿村而过，生态环境良好。

## 四、基础设施

对外道路为1条县道，村内道路硬化率80%。自来水入户率95%，无污水收集处理系统。4G网络全覆盖，宽带覆盖率60%。

## 五、公共服务

有村小学、卫生室、文化活动中心、老年活动中心各1个。体育设施有篮球场1个，健身路径2处。

## 六、建筑风貌

总建筑380栋，传统建筑45栋，危房12栋。建筑风格以江南民居为主。

## 七、历史文化

始建于南宋，距今800余年。有区级文保单位古祠堂1处，传统制茶技艺为非遗项目。

## 八、核心问题

1. 基础设施滞后，公共服务设施不足
2. 产业结构单一，经济水平一般
3. 人口老龄化严重，劳动力流失
4. 文化遗产保护意识不足
5. 生态环境面临压力

## 九、发展建议

1. 加快基础设施建设，完善公共服务设施
2. 优化产业结构，发展特色产业
3. 吸引人才回流，缓解人口老龄化
4. 加强文化遗产保护，传承非物质文化遗产
5. 加强生态环境保护，实现可持续发展
"""


def main():
    """主测试函数"""
    print("\n" + "="*80)
    print("规划思路子图简化测试")
    print("="*80 + "\n")

    project_name = "某某村"
    analysis_report = TEST_ANALYSIS_REPORT.strip()

    print(f"项目名称: {project_name}")
    print(f"分析报告长度: {len(analysis_report)} 字符")
    print("\n开始生成规划思路...\n")

    start_time = datetime.now()

    try:
        # 调用概念子图
        result = call_concept_subgraph(
            project_name=project_name,
            analysis_report=analysis_report
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # 输出结果
        print("\n" + "="*80)
        print("规划思路生成完成！")
        print("="*80)
        print(f"执行时间: {duration:.2f} 秒")
        print(f"报告长度: {len(result.get('concept_report', ''))} 字符")
        print()

        # 保存报告
        output_dir = Path("test/output/concept")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"concept_simple_{timestamp}.md"

        report_content = result.get('concept_report', '')

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# {project_name} 规划思路报告\n\n")
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
        print(f"\n❌ 规划思路生成失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
