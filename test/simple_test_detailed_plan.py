"""
详细规划子图简化测试 - 生成完整的详细规划报告

使用方法：
    python -m test.simple_test_detailed_plan
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.subgraphs.detailed_plan_subgraph import call_detailed_plan_subgraph
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 测试数据
TEST_ANALYSIS_REPORT = """
# 某某村现状分析报告

## 一、区位分析
某某村位于XX市XX区，距离市中心25公里，距离高速路口12公里。县道穿村而过，交通便利。

## 二、社会经济分析
全村320户，户籍人口1200人，常住人口980人，60岁以上老人280人。2024年村集体收入85万元，农民人均纯收入18000元/年。主要产业为水稻种植、茶叶种植、乡村旅游。

## 三、自然环境分析
丘陵地貌，平均海拔150米，年均气温18.5℃，年降水量1600mm。森林覆盖率68%，有XX河穿村而过。

## 四、土地利用分析
耕地2800亩，建设用地450亩，林地3200亩，水域230亩。土地利用以农业和林业为主。

## 五、道路交通分析
对外道路为1条县道，村内道路硬化率80%。距离高铁站30公里。

## 六、公共服务设施
有村小学、卫生室、文化活动中心、老年活动中心各1个。体育设施有篮球场1个，健身路径2处。

## 七、基础设施
自来水入户率95%，无污水收集处理系统。4G网络全覆盖，宽带覆盖率60%。

## 八、生态绿地
村庄绿化率35%，有村级公园1个（15亩），百年以上古树8棵。

## 九、建筑状况
总建筑380栋，传统建筑45栋，危房12栋。建筑风格以江南民居为主。

## 十、历史文化
始建于南宋，距今800余年。有区级文保单位古祠堂1处，传统制茶技艺为非遗项目。

## 十一、防灾减灾
存在山洪、滑坡风险，需加强防护。

## 十二、村庄风貌
整体风貌良好，传统建筑集中区域保持完整。
"""


TEST_CONCEPT_REPORT = """
# 某某村规划思路报告

## 一、资源禀赋分析
**自然资源**：村域面积6.2平方公里，耕地2800亩，林地3200亩，森林覆盖率68%，XX河穿村而过。
**人文资源**：800余年建村史，古祠堂1处，传统制茶技艺非遗。
**经济资源**：水稻、茶叶产业基础，乡村旅游起步。
**区位优势**：距市中心25公里，交通便利。

## 二、规划定位
**区域定位**：市郊生态旅游度假目的地
**功能定位**：生态农业+文化旅游+休闲度假
**产业定位**：主导产业-生态农业、乡村旅游；配套产业-农产品加工、文创产业
**形象定位**："江南茶乡·古韵新村"

## 三、发展目标
**总体目标**：5年内建成3A级景区，年接待游客10万人次，村集体收入突破200万元。

**近期目标（1-3年）**：
- 完成道路硬化、污水处理等基础设施
- 启动古村修复、茶园提升项目
- 建成游客中心、民宿3-5家

**中期目标（3-5年）**：
- 产业体系完善，产业链形成
- 创建3A级景区
- 年接待游客5万人次

**远期目标（5-10年）**：
- 产业成熟，品牌确立
- 年接待游客10万人次
- 村集体收入200万元

## 四、规划策略
**空间布局策略**：一心（游客中心）、两轴（主路景观轴、滨水景观轴）、三区（古村保护区、农业体验区、生态休闲区）
**产业发展策略**：提升茶产业，发展乡村旅游，培育文创产业
**生态保护策略**：划定生态红线，保护XX河水质，提升森林质量
**文化传承策略**：保护古建筑，传承制茶技艺，挖掘历史文化
**基础设施策略**：完善路网，建设污水处理系统，提升网络覆盖
**社会治理策略**：成立旅游合作社，引进专业人才，创新利益分配机制
"""


def main():
    """主测试函数"""
    print("\n" + "="*80)
    print("详细规划子图简化测试")
    print("="*80 + "\n")

    project_name = "某某村"
    analysis_report = TEST_ANALYSIS_REPORT.strip()
    concept_report = TEST_CONCEPT_REPORT.strip()

    print(f"项目名称: {project_name}")
    print(f"分析报告长度: {len(analysis_report)} 字符")
    print(f"概念报告长度: {len(concept_report)} 字符")
    print("\n开始生成详细规划（10个维度）...\n")
    print("提示：这可能需要几分钟时间，请耐心等待...\n")

    start_time = datetime.now()

    try:
        # 调用详细规划子图（生成全部10个维度）
        result = call_detailed_plan_subgraph(
            project_name=project_name,
            analysis_report=analysis_report,
            planning_concept=concept_report,
            task_description="制定村庄详细规划",
            constraints="生态优先，绿色发展"
        )

        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()

        # 检查结果
        if not result.get('success', False):
            print(f"\n❌ 详细规划生成失败")
            if 'error' in result:
                print(f"错误信息: {result['error']}")
            return 1

        # 输出结果
        print("\n" + "="*80)
        print("详细规划生成完成！")
        print("="*80)
        print(f"执行时间: {duration:.2f} 秒 ({duration/60:.1f} 分钟)")
        print(f"报告长度: {len(result.get('detailed_plan_report', ''))} 字符")

        # 安全地获取完成维度
        completed = result.get('completed_dimensions', [])
        if completed:
            print(f"完成的维度: {len(completed)} 个")

            # 显示各维度规划长度
            print("\n各维度规划统计:")
            for dim in completed:
                plan_key = f"{dim}_plan"
                if plan_key in result:
                    plan = result[plan_key]
                    print(f"  - {dim}: {len(plan)} 字符")
        else:
            print("完成的维度: 信息不可用")

        print()

        # 保存报告
        output_dir = Path("test/output/detailed")
        output_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_file = output_dir / f"detailed_simple_{timestamp}.md"

        report_content = result.get('detailed_plan_report', '')

        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(f"# {project_name} 详细规划报告\n\n")
            f.write(f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**执行时长**: {duration:.2f} 秒\n")
            if completed:
                f.write(f"**完成维度**: {len(completed)} 个\n\n")
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
                print(f"\n总计 {len(report_content)} 字符")
        else:
            print("\n⚠️  警告：报告内容为空，可能存在配置问题")

        return 0

    except Exception as e:
        print(f"\n❌ 详细规划生成失败: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
