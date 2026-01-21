"""
详细规划子图测试脚本

用于测试和验证详细规划子图的功能。

使用方法：
    python -m tests.test_detailed_plan_subgraph
    python -m tests.test_detailed_plan_subgraph --test direct
    python -m tests.test_detailed_plan_subgraph --test all --output custom/path
    python -m tests.test_detailed_plan_subgraph --test single --dimensions industry traffic
"""

import sys
import os
from datetime import datetime
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.subgraphs.detailed_plan_subgraph import create_detailed_plan_subgraph, call_detailed_plan_subgraph, ALL_DIMENSIONS
from src.utils.logger import get_logger
from tests.test_utils import (
    ensure_output_dirs,
    get_timestamp,
    save_to_markdown,
    format_test_output,
    DETAILED_OUTPUT_DIR,
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

## 十一、防灾减灾
存在山洪、滑坡风险，需加强防护。

## 十二、村庄风貌
整体风貌良好，传统建筑集中区域保持完整。
"""

TEST_PLANNING_CONCEPT = """
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
**发展层次**：
- 近期（1-3年）：完善基础设施，启动重点项目建设
- 中期（3-5年）：产业成型，品牌确立
- 远期（5-10年）：成为3A级景区，示范村

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


def test_subgraph_wrapper(output_dir: Path = DETAILED_OUTPUT_DIR):
    """测试包装函数 - 生成全部10个维度"""
    print("\n" + "="*80)
    print("测试1: 使用包装函数生成全部10个专业维度")
    print("="*80 + "\n")

    start_time = datetime.now()

    result = call_detailed_plan_subgraph(
        project_name="测试村",
        analysis_report=TEST_ANALYSIS_REPORT,
        planning_concept=TEST_PLANNING_CONCEPT,
        task_description="制定村庄详细规划",
        constraints="生态优先，绿色发展",
        required_dimensions=None  # 生成全部维度
    )

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"成功: {result['success']}")
    print(f"完成的维度: {result['completed_dimensions']}")
    print(f"报告长度: {len(result['detailed_plan_report'])} 字符")

    if result['success']:
        print("\n报告预览（前2000字符）:")
        print("="*80)
        print(result['detailed_plan_report'][:2000])

        # 保存结果到文件
        timestamp = get_timestamp()
        output_file = output_dir / f"detailed_all_{timestamp}.md"

        formatted_output = format_test_output(
            test_name="详细规划子图包装函数测试（全部维度）",
            test_type="wrapper_all",
            project_name="测试村",
            test_data=f"分析报告: {len(TEST_ANALYSIS_REPORT)} 字符\n规划思路: {len(TEST_PLANNING_CONCEPT)} 字符",
            report_content=result['detailed_plan_report'],
            start_time=start_time,
            end_time=end_time,
            additional_info={
                "状态": "成功",
                "报告长度": f"{len(result['detailed_plan_report'])} 字符",
                "完成维度": f"{len(result['completed_dimensions'])} 个 - {', '.join([d for d in result['completed_dimensions']])}",
                "任务描述": "制定村庄详细规划",
                "约束条件": "生态优先，绿色发展"
            }
        )

        save_to_markdown(formatted_output, output_file)
        print(f"\n报告已保存到: {output_file}")

        return {
            "success": True,
            "report_length": len(result['detailed_plan_report']),
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


def test_subgraph_partial(output_dir: Path = DETAILED_OUTPUT_DIR, dimensions: list = None):
    """测试包装函数 - 只生成指定维度"""
    if dimensions is None:
        dimensions = ["industry", "traffic", "infrastructure"]

    print("\n" + "="*80)
    print(f"测试2: 使用包装函数生成指定维度 ({len(dimensions)}个)")
    print("="*80 + "\n")

    start_time = datetime.now()

    result = call_detailed_plan_subgraph(
        project_name="测试村",
        analysis_report=TEST_ANALYSIS_REPORT,
        planning_concept=TEST_PLANNING_CONCEPT,
        task_description="制定村庄详细规划",
        constraints="生态优先，绿色发展",
        required_dimensions=dimensions
    )

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"成功: {result['success']}")
    print(f"完成的维度: {result['completed_dimensions']}")
    print(f"报告长度: {len(result['detailed_plan_report'])} 字符")

    if result['success']:
        # 保存结果到文件
        timestamp = get_timestamp()
        output_file = output_dir / f"detailed_partial_{timestamp}.md"

        formatted_output = format_test_output(
            test_name=f"详细规划子图包装函数测试（指定维度）",
            test_type="wrapper_partial",
            project_name="测试村",
            test_data=f"指定维度: {', '.join(dimensions)}",
            report_content=result['detailed_plan_report'],
            start_time=start_time,
            end_time=end_time,
            additional_info={
                "状态": "成功",
                "报告长度": f"{len(result['detailed_plan_report'])} 字符",
                "完成维度": f"{len(result['completed_dimensions'])} 个 - {', '.join(result['completed_dimensions'])}",
                "指定维度": ', '.join(dimensions)
            }
        )

        save_to_markdown(formatted_output, output_file)
        print(f"\n报告已保存到: {output_file}")

        return {
            "success": True,
            "report_length": len(result['detailed_plan_report']),
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


def test_subgraph_directly(output_dir: Path = DETAILED_OUTPUT_DIR):
    """直接测试子图"""
    print("\n" + "="*80)
    print("测试3: 直接调用详细规划子图（2个维度）")
    print("="*80 + "\n")

    start_time = datetime.now()

    # 创建子图
    subgraph = create_detailed_plan_subgraph()

    # 初始状态
    initial_state = {
        "project_name": "测试村",
        "analysis_report": TEST_ANALYSIS_REPORT,
        "planning_concept": TEST_PLANNING_CONCEPT,
        "task_description": "制定村庄详细规划",
        "constraints": "生态优先，绿色发展",
        "required_dimensions": ["industry", "master_plan"],  # 只生成2个维度
        "completed_dimensions": [],
        "current_dimension": "",
        "industry_plan": "",
        "master_plan": "",
        "traffic_plan": "",
        "public_service_plan": "",
        "infrastructure_plan": "",
        "ecological_plan": "",
        "disaster_prevention_plan": "",
        "heritage_plan": "",
        "landscape_plan": "",
        "project_bank": "",
        "need_review": False,
        "human_feedback": {},
        "revision_count": {},
        "dimension_plans": [],
        "final_detailed_plan": "",
        "consolidated_project_bank": "",
        "messages": []
    }

    print("开始执行详细规划...")
    print(f"指定生成维度: {initial_state['required_dimensions']}\n")

    # 执行子图
    result = subgraph.invoke(initial_state)

    end_time = datetime.now()

    print("\n" + "-"*80)
    print("执行完成！")
    print("-"*80)
    print(f"最终报告长度: {len(result['final_detailed_plan'])} 字符")
    print(f"完成的维度: {result['completed_dimensions']}")

    # 打印最终报告预览
    print("\n" + "="*80)
    print("最终详细规划报告（预览前3000字符）")
    print("="*80 + "\n")
    print(result["final_detailed_plan"][:3000])
    print("\n... (完整报告已保存到文件) ...")

    # 保存结果到文件
    timestamp = get_timestamp()
    output_file = output_dir / f"detailed_direct_{timestamp}.md"

    formatted_output = format_test_output(
        test_name="详细规划子图直接调用测试",
        test_type="direct",
        project_name="测试村",
        test_data=f"分析报告: {len(TEST_ANALYSIS_REPORT)} 字符\n规划思路: {len(TEST_PLANNING_CONCEPT)} 字符",
        report_content=result["final_detailed_plan"],
        start_time=start_time,
        end_time=end_time,
        additional_info={
            "状态": "成功",
            "报告长度": f"{len(result['final_detailed_plan'])} 字符",
            "完成维度": f"{len(result['completed_dimensions'])} 个 - {', '.join(result['completed_dimensions'])}",
            "任务描述": "制定村庄详细规划",
            "约束条件": "生态优先，绿色发展"
        }
    )

    save_to_markdown(formatted_output, output_file)
    print(f"\n报告已保存到: {output_file}")

    return {
        "success": True,
        "report_length": len(result['final_detailed_plan']),
        "output_file": str(output_file.relative_to(Path.cwd())),
        "start_time": start_time,
        "end_time": end_time
    }


def generate_detailed_summary(test_results: dict) -> str:
    """生成详细规划子图测试汇总报告"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    total_tests = len(test_results)
    passed = sum(1 for r in test_results.values() if r.get("success", False))
    failed = total_tests - passed

    lines = [
        "# 详细规划子图测试汇总报告\n",
        f"**生成时间**: {timestamp}",
        f"**测试模块**: 详细规划 (Detailed Planning Subgraph)\n",
        "## 测试概况",
        f"- 总测试数: {total_tests}",
        f"- 成功: {passed}",
        f"- 失败: {failed}\n",
        "## 各测试结果\n"
    ]

    for test_name, result in test_results.items():
        status_icon = "✅" if result.get("success", False) else "❌"
        report_length = result.get("report_length", 0)
        output_file = result.get("output_file", "无")

        lines.extend([
            f"### 测试: {test_name}",
            f"- 状态: {status_icon}",
            f"- 报告长度: {report_length} 字符",
            f"- 输出文件: `{output_file}`\n"
        ])

    lines.extend([
        "## 详细输出文件",
        "---",
        "以上测试报告均已保存在 `test/output/detailed/` 目录下。\n"
    ])

    return "\n".join(lines)


def run_all_tests_and_summary(output_dir: Path = DETAILED_OUTPUT_DIR):
    """运行所有测试并生成汇总报告"""
    test_results = {}

    try:
        result = test_subgraph_wrapper(output_dir)
        test_results["全部维度测试"] = result
    except Exception as e:
        logger.error(f"全部维度测试失败: {str(e)}", exc_info=True)
        test_results["全部维度测试"] = {"success": False, "error": str(e)}

    try:
        result = test_subgraph_partial(output_dir)
        test_results["部分维度测试"] = result
    except Exception as e:
        logger.error(f"部分维度测试失败: {str(e)}", exc_info=True)
        test_results["部分维度测试"] = {"success": False, "error": str(e)}

    try:
        result = test_subgraph_directly(output_dir)
        test_results["直接调用测试"] = result
    except Exception as e:
        logger.error(f"直接调用测试失败: {str(e)}", exc_info=True)
        test_results["直接调用测试"] = {"success": False, "error": str(e)}

    # 生成汇总报告
    summary_content = generate_detailed_summary(test_results)
    timestamp = get_timestamp()
    summary_file = SUMMARY_OUTPUT_DIR / f"detailed_summary_{timestamp}.md"
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

    parser = argparse.ArgumentParser(description="测试详细规划子图")
    parser.add_argument(
        "--test",
        type=str,
        choices=["all", "wrapper", "partial", "direct"],
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
    parser.add_argument(
        "--dimensions",
        type=str,
        nargs="+",
        choices=ALL_DIMENSIONS,
        default=None,
        help="指定要生成的维度（仅用于partial测试）"
    )

    args = parser.parse_args()

    # 确保输出目录存在
    ensure_output_dirs()

    # 设置自定义输出目录
    output_base_dir = DETAILED_OUTPUT_DIR
    if args.output:
        output_base_dir = Path(args.output)
        output_base_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.test == "all":
            run_all_tests_and_summary(output_base_dir)
        elif args.test == "wrapper":
            test_subgraph_wrapper(output_base_dir)
        elif args.test == "partial":
            test_subgraph_partial(output_base_dir, args.dimensions)
        elif args.test == "direct":
            test_subgraph_directly(output_base_dir)

        print("\n" + "="*80)
        print("✅ 所有测试完成！")
        print("="*80 + "\n")

    except Exception as e:
        logger.error(f"测试失败: {str(e)}", exc_info=True)
        print(f"\n❌ 测试失败: {str(e)}")
        import traceback
        traceback.print_exc()
