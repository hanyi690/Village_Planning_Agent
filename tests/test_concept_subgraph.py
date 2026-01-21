"""
规划思路子图测试脚本

用于测试和验证规划思路子图的功能。

使用方法：
    python -m tests.test_concept_subgraph
    python -m tests.test_concept_subgraph --test direct
    python -m tests.test_concept_subgraph --test all --output custom/path
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.subgraphs.concept_subgraph import create_concept_subgraph, call_concept_subgraph
from src.utils.logger import get_logger
from tests.test_utils import (
    ensure_output_dirs,
    get_timestamp,
    save_to_markdown,
    generate_concept_summary,
    format_test_output,
    CONCEPT_OUTPUT_DIR,
    SUMMARY_OUTPUT_DIR
)

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


def test_subgraph_directly(output_dir: Path = CONCEPT_OUTPUT_DIR):
    """直接测试子图"""
    print("\n" + "="*80)
    print("测试1: 直接调用规划思路子图")
    print("="*80 + "\n")

    start_time = datetime.now()

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

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"最终报告长度: {len(result['final_concept'])} 字符")
    print(f"完成的维度分析: {len(result['concept_analyses'])} 个")

    # 打印最终报告预览
    print("\n" + "="*80)
    print("最终规划思路报告（预览前3000字符）")
    print("="*80 + "\n")
    print(result["final_concept"][:3000])
    print("\n... (完整报告已保存到文件) ...")

    # 保存结果到文件
    timestamp = get_timestamp()
    output_file = output_dir / f"concept_direct_{timestamp}.md"

    formatted_output = format_test_output(
        test_name="规划思路子图直接调用测试",
        test_type="direct",
        project_name="测试村",
        test_data=TEST_ANALYSIS_REPORT,
        report_content=result["final_concept"],
        start_time=start_time,
        end_time=end_time,
        additional_info={
            "状态": "成功",
            "报告长度": f"{len(result['final_concept'])} 字符",
            "完成维度": f"{len(result['concept_analyses'])} 个",
            "任务描述": "制定乡村振兴规划思路",
            "约束条件": "生态优先，绿色发展"
        }
    )

    save_to_markdown(formatted_output, output_file)
    print(f"\n报告已保存到: {output_file}")

    return {
        "success": True,
        "report_length": len(result['final_concept']),
        "output_file": str(output_file.relative_to(Path.cwd())),
        "start_time": start_time,
        "end_time": end_time
    }


def test_subgraph_wrapper(output_dir: Path = CONCEPT_OUTPUT_DIR):
    """测试包装函数"""
    print("\n" + "="*80)
    print("测试2: 使用包装函数调用子图")
    print("="*80 + "\n")

    start_time = datetime.now()

    result = call_concept_subgraph(
        project_name="测试村",
        analysis_report=TEST_ANALYSIS_REPORT,
        task_description="制定乡村振兴规划思路",
        constraints="生态优先，绿色发展"
    )

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"成功: {result['success']}")
    print(f"报告长度: {len(result['concept_report'])} 字符")

    if result['success']:
        print("\n报告预览（前2000字符）:")
        print("="*80)
        print(result['concept_report'][:2000])

        # 保存结果到文件
        timestamp = get_timestamp()
        output_file = output_dir / f"concept_wrapper_{timestamp}.md"

        formatted_output = format_test_output(
            test_name="规划思路子图包装函数测试",
            test_type="wrapper",
            project_name="测试村",
            test_data=TEST_ANALYSIS_REPORT,
            report_content=result['concept_report'],
            start_time=start_time,
            end_time=end_time,
            additional_info={
                "状态": "成功",
                "报告长度": f"{len(result['concept_report'])} 字符",
                "任务描述": "制定乡村振兴规划思路",
                "约束条件": "生态优先，绿色发展"
            }
        )

        save_to_markdown(formatted_output, output_file)
        print(f"\n报告已保存到: {output_file}")

        return {
            "success": True,
            "report_length": len(result['concept_report']),
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


def test_with_stream(output_dir: Path = CONCEPT_OUTPUT_DIR):
    """测试流式输出"""
    print("\n" + "="*80)
    print("测试3: 流式输出模式")
    print("="*80 + "\n")

    start_time = datetime.now()

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

    final_result = {}
    # 使用 stream 方法观察执行过程
    for event in subgraph.stream(initial_state, stream_mode="values"):
        # 打印当前执行的节点
        if isinstance(event, dict):
            if "concept_analyses" in event and len(event["concept_analyses"]) > 0:
                print(f"已完成 {len(event['concept_analyses'])} 个维度分析")
            if "final_concept" in event and event["final_concept"]:
                print("\n✅ 最终报告生成完成！")
                final_result = event

    end_time = datetime.now()

    print("\n流式执行完成！")

    # 保存结果到文件
    if final_result and final_result.get("final_concept"):
        timestamp = get_timestamp()
        output_file = output_dir / f"concept_stream_{timestamp}.md"

        formatted_output = format_test_output(
            test_name="规划思路子图流式输出测试",
            test_type="stream",
            project_name="测试村",
            test_data=TEST_ANALYSIS_REPORT,
            report_content=final_result["final_concept"],
            start_time=start_time,
            end_time=end_time,
            additional_info={
                "状态": "成功",
                "报告长度": f"{len(final_result['final_concept'])} 字符",
                "完成维度": f"{len(final_result.get('concept_analyses', []))} 个",
                "任务描述": "制定乡村振兴规划思路",
                "约束条件": "生态优先，绿色发展"
            }
        )

        save_to_markdown(formatted_output, output_file)
        print(f"\n报告已保存到: {output_file}")

        return {
            "success": True,
            "report_length": len(final_result['final_concept']),
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


def run_all_tests_and_summary(output_dir: Path = CONCEPT_OUTPUT_DIR):
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
    summary_content = generate_concept_summary(test_results)
    timestamp = get_timestamp()
    summary_file = SUMMARY_OUTPUT_DIR / f"concept_summary_{timestamp}.md"
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

    parser = argparse.ArgumentParser(description="测试规划思路子图")
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
    output_base_dir = CONCEPT_OUTPUT_DIR
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
