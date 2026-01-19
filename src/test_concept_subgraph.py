"""
规划思路子图测试脚本

用于测试和验证规划思路子图的功能。

使用方法：
    python -m src.test_concept_subgraph
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.subgraphs.concept_subgraph import create_concept_subgraph, call_concept_subgraph
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
"""


def test_subgraph_directly():
    """直接测试子图"""
    print("\n" + "="*80)
    print("测试1: 直接调用规划思路子图")
    print("="*80 + "\n")

    # 创建子图
    subgraph = create_concept_subgraph()

    # 初始状态
    initial_state = {
        "analysis_report": TEST_ANALYSIS_REPORT,
        "project_name": "测试村",
        "task_description": "制定乡村振兴规划思路",
        "constraints": "生态优先，绿色发展",
        "dimensions": [],
        "concept_analyses": [],
        "final_concept": "",
        "messages": []
    }

    print("开始执行规划思路分析...")
    print(f"输入分析报告长度: {len(TEST_ANALYSIS_REPORT)} 字符\n")

    # 执行子图
    result = subgraph.invoke(initial_state)

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"最终报告长度: {len(result['final_concept'])} 字符")
    print(f"完成的维度分析: {len(result['concept_analyses'])} 个")

    # 打印最终报告
    print("\n" + "="*80)
    print("最终规划思路报告")
    print("="*80 + "\n")
    print(result["final_concept"][:3000])  # 打印前3000字符
    print("\n... (报告已截断，完整内容见 final_concept 字段) ...")

    return result


def test_subgraph_wrapper():
    """测试包装函数"""
    print("\n" + "="*80)
    print("测试2: 使用包装函数调用子图")
    print("="*80 + "\n")

    result = call_concept_subgraph(
        project_name="测试村",
        analysis_report=TEST_ANALYSIS_REPORT,
        task_description="制定乡村振兴规划思路",
        constraints="生态优先，绿色发展"
    )

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"成功: {result['success']}")
    print(f"报告长度: {len(result['concept_report'])} 字符")

    if result['success']:
        print("\n报告预览（前2000字符）:")
        print("="*80)
        print(result['concept_report'][:2000])

    return result


def test_with_stream():
    """测试流式输出"""
    print("\n" + "="*80)
    print("测试3: 流式输出模式")
    print("="*80 + "\n")

    subgraph = create_concept_subgraph()

    initial_state = {
        "analysis_report": TEST_ANALYSIS_REPORT,
        "project_name": "测试村",
        "task_description": "制定乡村振兴规划思路",
        "constraints": "生态优先，绿色发展",
        "dimensions": [],
        "concept_analyses": [],
        "final_concept": "",
        "messages": []
    }

    print("开始流式执行...\n")

    # 使用 stream 方法观察执行过程
    for event in subgraph.stream(initial_state, stream_mode="values"):
        # 打印当前执行的节点
        if isinstance(event, dict):
            if "concept_analyses" in event and len(event["concept_analyses"]) > 0:
                print(f"已完成 {len(event['concept_analyses'])} 个维度分析")
            if "final_concept" in event and event["final_concept"]:
                print("\n✅ 最终报告生成完成！")

    print("\n流式执行完成！")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="测试规划思路子图")
    parser.add_argument(
        "--test",
        type=str,
        choices=["direct", "wrapper", "stream", "all"],
        default="all",
        help="选择测试类型"
    )

    args = parser.parse_args()

    try:
        if args.test == "direct" or args.test == "all":
            test_subgraph_directly()

        if args.test == "wrapper" or args.test == "all":
            test_subgraph_wrapper()

        if args.test == "stream" or args.test == "all":
            test_with_stream()

        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80 + "\n")

    except Exception as e:
        logger.error(f"测试失败: {str(e)}", exc_info=True)
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
