"""
命令行参数解析器

提供统一的命令行参数解析功能。
"""

import argparse
from typing import Optional


def create_main_parser() -> argparse.ArgumentParser:
    """
    创建主参数解析器

    Returns:
        ArgumentParser实例
    """
    parser = argparse.ArgumentParser(
        description="村庄规划 AI 助手 - 基于层级化 LangGraph 架构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整规划流程（单个文件）
  python -m src.cli.main --mode full --project "某某村" --data village_data.txt

  # 完整规划流程（多个文件）
  python -m src.cli.main --mode full --project "某某村" --data file1.txt,file2.pdf

  # 仅现状分析（多个文件）
  python -m src.cli.main --mode analysis --project "某某村" --data data1.txt,data2.pdf

  # 快速规划
  python -m src.cli.main --mode quick --project "某某村" --data village_data.txt

更多信息请参阅 README.md
        """
    )

    # 基本参数
    parser.add_argument(
        "--mode",
        type=str,
        choices=["full", "analysis", "quick", "step", "resume", "list-checkpoints"],
        default="full",
        help="运行模式: full(完整规划), analysis(仅分析), quick(快速), step(逐步执行), resume(从checkpoint恢复), list-checkpoints(列出checkpoint)"
    )

    parser.add_argument(
        "--project",
        type=str,
        help="项目/村庄名称"
    )

    parser.add_argument(
        "--data",
        type=str,
        help="村庄数据文件路径（支持单个文件或逗号分隔的多个文件）"
    )

    parser.add_argument(
        "--task",
        type=str,
        help="规划任务描述"
    )

    parser.add_argument(
        "--constraints",
        type=str,
        help="约束条件"
    )

    parser.add_argument(
        "--output", "-o",
        type=str,
        help="输出文件路径（可选，不指定则自动保存到 results/{项目名}/{时间戳}/）"
    )

    parser.add_argument(
        "--review",
        action="store_true",
        help="启用人工审核"
    )

    parser.add_argument(
        "--stream",
        action="store_true",
        help="使用流式输出"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示完整输出"
    )

    parser.add_argument(
        "--version",
        action="version",
        version="村庄规划 AI 助手 v2.1.0 (hierarchical-langgraph)"
    )

    # 逐步执行模式参数
    parser.add_argument(
        "--step-level",
        type=str,
        choices=["layer", "dimension", "skill"],
        default="layer",
        help="逐步执行的暂停级别: layer(每层暂停), dimension(每维度暂停), skill(每skill暂停)"
    )

    # 从checkpoint恢复参数
    parser.add_argument(
        "--resume-from",
        type=str,
        help="从指定checkpoint恢复执行"
    )

    parser.add_argument(
        "--list-checkpoints",
        action="store_true",
        help="列出项目的所有checkpoint（等同于 --mode list-checkpoints）"
    )

    return parser


def parse_args(args: Optional[list] = None) -> argparse.Namespace:
    """
    解析命令行参数

    Args:
        args: 参数列表（可选），如果不提供则使用sys.argv

    Returns:
        解析后的参数命名空间
    """
    parser = create_main_parser()
    parsed_args = parser.parse_args(args)

    # 处理 --list-checkpoints 参数
    if parsed_args.list_checkpoints:
        parsed_args.mode = "list-checkpoints"

    return parsed_args
