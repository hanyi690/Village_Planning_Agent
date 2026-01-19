"""
现状分析子图测试脚本

用于测试和验证现状分析子图的功能。

使用方法：
    python -m test.test_analysis_subgraph
    python -m test.test_analysis_subgraph --test direct
    python -m test.test_analysis_subgraph --test all --output custom/path
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.subgraphs.analysis_subgraph import create_analysis_subgraph, call_analysis_subgraph
from src.utils.logger import get_logger
from test.test_utils import (
    ensure_output_dirs,
    get_timestamp,
    save_to_markdown,
    generate_analysis_summary,
    format_test_output,
    ANALYSIS_OUTPUT_DIR,
    SUMMARY_OUTPUT_DIR
)

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


def test_subgraph_directly(output_dir: Path = ANALYSIS_OUTPUT_DIR):
    """直接测试子图"""
    print("\n" + "="*80)
    print("测试1: 直接调用子图")
    print("="*80 + "\n")

    start_time = datetime.now()

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

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"最终报告长度: {len(result['final_report'])} 字符")
    print(f"完成的维度分析: {len(result['analyses'])} 个")

    # 打印最终报告预览
    print("\n" + "="*80)
    print("最终现状分析报告（预览前2000字符）")
    print("="*80 + "\n")
    print(result["final_report"][:2000])
    print("\n... (完整报告已保存到文件) ...")

    # 保存结果到文件
    timestamp = get_timestamp()
    output_file = output_dir / f"analysis_direct_{timestamp}.md"

    formatted_output = format_test_output(
        test_name="现状分析子图直接调用测试",
        test_type="direct",
        project_name="某某村",
        test_data=TEST_VILLAGE_DATA,
        report_content=result["final_report"],
        start_time=start_time,
        end_time=end_time,
        additional_info={
            "状态": "成功",
            "报告长度": f"{len(result['final_report'])} 字符",
            "完成维度": f"{len(result['analyses'])} 个"
        }
    )

    save_to_markdown(formatted_output, output_file)
    print(f"\n报告已保存到: {output_file}")

    return {
        "success": True,
        "report_length": len(result['final_report']),
        "output_file": str(output_file.relative_to(Path.cwd())),
        "start_time": start_time,
        "end_time": end_time
    }


def test_subgraph_wrapper(output_dir: Path = ANALYSIS_OUTPUT_DIR):
    """测试包装函数"""
    print("\n" + "="*80)
    print("测试2: 使用包装函数调用子图")
    print("="*80 + "\n")

    start_time = datetime.now()

    result = call_analysis_subgraph(
        raw_data=TEST_VILLAGE_DATA,
        project_name="某某村"
    )

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"成功: {result['success']}")
    print(f"报告长度: {len(result['analysis_report'])} 字符")

    if result['success']:
        print("\n报告预览（前1500字符）:")
        print("="*80)
        print(result['analysis_report'][:1500])

        # 保存结果到文件
        timestamp = get_timestamp()
        output_file = output_dir / f"analysis_wrapper_{timestamp}.md"

        formatted_output = format_test_output(
            test_name="现状分析子图包装函数测试",
            test_type="wrapper",
            project_name="某某村",
            test_data=TEST_VILLAGE_DATA,
            report_content=result['analysis_report'],
            start_time=start_time,
            end_time=end_time,
            additional_info={
                "状态": "成功",
                "报告长度": f"{len(result['analysis_report'])} 字符"
            }
        )

        save_to_markdown(formatted_output, output_file)
        print(f"\n报告已保存到: {output_file}")

        return {
            "success": True,
            "report_length": len(result['analysis_report']),
            "output_file": str(output_file.relative_to(Path.cwd())),
            "start_time": start_time,
            "end_time": end_time
        }
    else:
        return {
            "success": False,
            "report_length": 0,
            "output_file": "无",
            "start_time": start_time,
            "end_time": end_time
        }


def test_with_stream(output_dir: Path = ANALYSIS_OUTPUT_DIR):
    """测试流式输出"""
    print("\n" + "="*80)
    print("测试3: 流式输出模式")
    print("="*80 + "\n")

    start_time = datetime.now()

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

    final_result = {}
    # 使用 stream 方法观察执行过程
    for event in subgraph.stream(initial_state, stream_mode="values"):
        # 打印当前执行的节点
        if isinstance(event, dict):
            if "analyses" in event and len(event["analyses"]) > 0:
                print(f"已完成 {len(event['analyses'])} 个维度分析")
            if "final_report" in event and event["final_report"]:
                print("\n✅ 最终报告生成完成！")
                final_result = event

    end_time = datetime.now()

    print("\n流式执行完成！")

    # 保存结果到文件
    if final_result and final_result.get("final_report"):
        timestamp = get_timestamp()
        output_file = output_dir / f"analysis_stream_{timestamp}.md"

        formatted_output = format_test_output(
            test_name="现状分析子图流式输出测试",
            test_type="stream",
            project_name="某某村",
            test_data=TEST_VILLAGE_DATA,
            report_content=final_result["final_report"],
            start_time=start_time,
            end_time=end_time,
            additional_info={
                "状态": "成功",
                "报告长度": f"{len(final_result['final_report'])} 字符",
                "完成维度": f"{len(final_result.get('analyses', []))} 个"
            }
        )

        save_to_markdown(formatted_output, output_file)
        print(f"\n报告已保存到: {output_file}")

        return {
            "success": True,
            "report_length": len(final_result['final_report']),
            "output_file": str(output_file.relative_to(Path.cwd())),
            "start_time": start_time,
            "end_time": end_time
        }
    else:
        return {
            "success": False,
            "report_length": 0,
            "output_file": "无",
            "start_time": start_time,
            "end_time": end_time
        }


def run_all_tests_and_summary(output_dir: Path = ANALYSIS_OUTPUT_DIR):
    """运行所有测试并生成汇总报告"""
    test_results = {}

    try:
        # 运行所有测试
        result = test_subgraph_directly(output_dir)
        test_results["直接调用测试"] = result
    except Exception as e:
        logger.error(f"直接调用测试失败: {str(e)}", exc_info=True)
        test_results["直接调用测试"] = {"success": False, "error": str(e)}

    try:
        result = test_subgraph_wrapper(output_dir)
        test_results["包装函数测试"] = result
    except Exception as e:
        logger.error(f"包装函数测试失败: {str(e)}", exc_info=True)
        test_results["包装函数测试"] = {"success": False, "error": str(e)}

    try:
        result = test_with_stream(output_dir)
        test_results["流式输出测试"] = result
    except Exception as e:
        logger.error(f"流式输出测试失败: {str(e)}", exc_info=True)
        test_results["流式输出测试"] = {"success": False, "error": str(e)}

    # 生成汇总报告
    summary_content = generate_analysis_summary(test_results)
    timestamp = get_timestamp()
    summary_file = SUMMARY_OUTPUT_DIR / f"analysis_summary_{timestamp}.md"
    save_to_markdown(summary_content, summary_file)

    print("\n" + "="*80)
    print("测试汇总")
    print("="*80)
    print(f"\n汇总报告已保存到: {summary_file.relative_to(Path.cwd())}")

    passed = sum(1 for r in test_results.values() if r.get("success", False))
    total = len(test_results)
    print(f"测试结果: {passed}/{total} 通过")

    return test_results


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
    parser.add_argument(
        "--output",
        "-o",
        type=str,
        default=None,
        help="自定义输出目录（相对于test/output）"
    )

    args = parser.parse_args()

    # 确保输出目录存在
    ensure_output_dirs()

    # 设置自定义输出目录
    output_base_dir = ANALYSIS_OUTPUT_DIR
    if args.output:
        output_base_dir = Path(args.output)
        output_base_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.test == "all":
            run_all_tests_and_summary(output_base_dir)
        elif args.test == "direct":
            test_subgraph_directly(output_base_dir)
        elif args.test == "wrapper":
            test_subgraph_wrapper(output_base_dir)
        elif args.test == "stream":
            test_with_stream(output_base_dir)

        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80 + "\n")

    except Exception as e:
        logger.error(f"测试失败: {str(e)}", exc_info=True)
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
