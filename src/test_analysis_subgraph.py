"""
现状分析子图测试脚本

用于测试和验证现状分析子图的功能。

使用方法：
    python -m src.test_analysis_subgraph
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.subgraphs.analysis_subgraph import create_analysis_subgraph, call_analysis_subgraph
from src.utils.logger import get_logger

logger = get_logger(__name__)


# 测试数据
TEST_VILLAGE_DATA = """
# 某某村基础数据

## 基本信息
- 村庄名称：某某村
- 所属乡镇：XX镇
- 地理位置：位于XX市XX区，距离市中心25公里
- 经纬度：东经120°30'，北纬30°15'
- 行政区划面积：5.2平方公里
- 建成区面积：0.8平方公里

## 人口与经济
- 总户数：320户
- 户籍人口：1200人
- 常住人口：980人
- 外出务工人口：220人
- 60岁以上老人：280人（占户籍人口23.3%）
- 2024年村集体收入：85万元
- 农民人均纯收入：18000元/年
- 主要产业：水稻种植、茶叶种植、乡村旅游

## 自然环境
- 地形：丘陵地貌，平均海拔150米
- 气候：亚热带季风气候，年均气温18.5℃，年降水量1600mm
- 河流：村内有XX河穿村而过，水质良好
- 森林覆盖率：68%
- 生态公益林：1200亩

## 土地利用
- 耕地：2800亩（其中水田2200亩，旱地600亩）
- 建设用地：450亩
- 林地：3200亩
- 水域：230亩
- 其他用地：520亩

## 道路交通
- 对外道路：1条县道，宽度6米，水泥路面
- 村内道路：主干道3.5公里，硬化率80%
- 距离高速路口：12公里
- 距离高铁站：30公里
- 距离最近的公交站点：3公里（村口）

## 公共服务设施
- 村小学：1所，6个班级，120名学生
- 村卫生室：1个，村医2名
- 文化活动中心：1个，建筑面积200平方米
- 老年活动中心：1个
- 体育设施：篮球场1个，健身路径2处
- 超市/便利店：3家

## 基础设施
- 供水：自来水入户率95%，水源来自山泉水
- 排水：无污水收集处理系统，自然排放
- 供电：农网改造完成，供电稳定
- 通信：4G网络全覆盖，宽带覆盖率60%
- 垃圾处理：垃圾收集点5个，由镇统一清运
- 公厕：2座

## 建筑状况
- 总建筑栋数：380栋
- 传统建筑：45栋（建于1980年代前）
- 新建建筑：120栋（2010年后建）
- 危房：12栋
- 建筑风格：以江南民居风格为主，白墙黑瓦

## 生态环境
- 村内绿化：村庄绿化率35%
- 公园绿地：1个村级公园，面积15亩
- 古树名木：百年以上古树8棵
- 生态廊道：沿河生态廊道1.2公里

## 历史文化
- 建村历史：始建于南宋时期，距今800余年
- 历史人物：XX（清朝进士）
- 文物保护单位：村古祠堂1处（区级文保单位）
- 非物质文化遗产：传统制茶技艺
- 民俗活动：每年清明节祭祖、中秋庙会
"""


def test_subgraph_directly():
    """直接测试子图"""
    print("\n" + "="*80)
    print("测试1: 直接调用子图")
    print("="*80 + "\n")

    # 创建子图
    subgraph = create_analysis_subgraph()

    # 初始状态
    initial_state = {
        "raw_data": TEST_VILLAGE_DATA,
        "project_name": "某某村",
        "subjects": [],
        "analyses": [],
        "final_report": "",
        "messages": []
    }

    print("开始执行现状分析...")
    print(f"输入数据长度: {len(TEST_VILLAGE_DATA)} 字符\n")

    # 执行子图
    result = subgraph.invoke(initial_state)

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"最终报告长度: {len(result['final_report'])} 字符")
    print(f"完成的维度分析: {len(result['analyses'])} 个")

    # 打印最终报告
    print("\n" + "="*80)
    print("最终现状分析报告")
    print("="*80 + "\n")
    print(result["final_report"][:2000])  # 打印前2000字符
    print("\n... (报告已截断，完整内容见final_report字段) ...")

    return result


def test_subgraph_wrapper():
    """测试包装函数"""
    print("\n" + "="*80)
    print("测试2: 使用包装函数调用子图")
    print("="*80 + "\n")

    result = call_analysis_subgraph(
        raw_data=TEST_VILLAGE_DATA,
        project_name="某某村"
    )

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"成功: {result['success']}")
    print(f"报告长度: {len(result['analysis_report'])} 字符")

    if result['success']:
        print("\n报告预览（前1500字符）:")
        print("="*80)
        print(result['analysis_report'][:1500])

    return result


def test_with_stream():
    """测试流式输出"""
    print("\n" + "="*80)
    print("测试3: 流式输出模式")
    print("="*80 + "\n")

    subgraph = create_analysis_subgraph()

    initial_state = {
        "raw_data": TEST_VILLAGE_DATA,
        "project_name": "某某村",
        "subjects": [],
        "analyses": [],
        "final_report": "",
        "messages": []
    }

    print("开始流式执行...\n")

    # 使用 stream 方法观察执行过程
    for event in subgraph.stream(initial_state, stream_mode="values"):
        # 打印当前执行的节点
        if isinstance(event, dict):
            if "analyses" in event and len(event["analyses"]) > 0:
                print(f"已完成 {len(event['analyses'])} 个维度分析")
            if "final_report" in event and event["final_report"]:
                print("\n✅ 最终报告生成完成！")

    print("\n流式执行完成！")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="测试现状分析子图")
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
