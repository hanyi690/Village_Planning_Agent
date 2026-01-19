"""
村庄规划 Agent 运行入口

支持多种运行模式：
1. 完整规划流程（新版）
2. 仅现状分析
3. 快速规划
4. 旧版兼容模式

使用方法：
    # 完整规划流程
    python -m src.run_agent --mode full --project "某某村" --data village_data.txt

    # 仅现状分析
    python -m src.run_agent --mode analysis --project "某某村" --data village_data.txt

    # 快速规划
    python -m src.run_agent --mode quick --project "某某村" --data village_data.txt

    # 旧版兼容
    python -m src.run_agent --mode legacy --task "制定村庄规划"
"""

import argparse
import sys
from pathlib import Path

from .agent import (
    run_village_planning,
    run_analysis_only,
    quick_analysis,
    quick_planning,
    run_task,
    __version__,
    __architecture__
)
from .utils.logger import get_logger

logger = get_logger(__name__)


def read_village_data(file_path: str) -> str:
    """从文件读取村庄数据"""
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"数据文件不存在: {file_path}")

    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


def run_full_mode(args):
    """完整规划流程模式"""
    logger.info(f"开始完整规划流程: {args.project}")

    try:
        # 读取村庄数据
        if args.data:
            village_data = read_village_data(args.data)
        else:
            raise ValueError("完整规划模式需要提供 --data 参数")

        # 执行规划
        result = run_village_planning(
            project_name=args.project,
            village_data=village_data,
            task_description=args.task or "制定村庄总体规划方案",
            constraints=args.constraints or "无特殊约束",
            need_human_review=args.review,
            stream_mode=args.stream
        )

        # 输出结果
        if result['success']:
            print("\n" + "="*80)
            print("✅ 规划完成！")
            print("="*80)
            print(f"\n所有层级完成: {result.get('all_layers_completed', False)}")

            # 保存结果到文件
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result['final_output'])
                print(f"\n📄 结果已保存到: {args.output}")

            # 打印预览
            if args.verbose:
                print("\n" + "="*80)
                print("完整规划成果")
                print("="*80 + "\n")
                print(result['final_output'])
            else:
                print("\n" + "="*80)
                print("成果预览（前2000字符）")
                print("="*80 + "\n")
                print(result['final_output'][:2000])
                print("\n... (使用 --verbose 查看完整内容) ...")
        else:
            print(f"\n❌ 规划失败: {result.get('error', '未知错误')}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 执行失败: {str(e)}")
        sys.exit(1)


def run_analysis_mode(args):
    """仅现状分析模式"""
    logger.info(f"开始现状分析: {args.project}")

    try:
        # 读取村庄数据
        if args.data:
            village_data = read_village_data(args.data)
        else:
            raise ValueError("分析模式需要提供 --data 参数")

        # 执行分析
        result = run_analysis_only(
            project_name=args.project,
            village_data=village_data
        )

        # 输出结果
        if result['success']:
            print("\n" + "="*80)
            print("✅ 现状分析完成！")
            print("="*80)

            report = result['analysis_report']

            # 保存结果
            if args.output:
                output_path = Path(args.output)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                print(f"\n📄 分析报告已保存到: {args.output}")

            # 打印报告
            if args.verbose:
                print("\n" + "="*80)
                print("完整分析报告")
                print("="*80 + "\n")
                print(report)
            else:
                print("\n" + "="*80)
                print("报告预览（前2000字符）")
                print("="*80 + "\n")
                print(report[:2000])
                print("\n... (使用 --verbose 查看完整内容) ...")
        else:
            print(f"\n❌ 分析失败: {result.get('analysis_report', '未知错误')}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 执行失败: {str(e)}")
        sys.exit(1)


def run_quick_mode(args):
    """快速规划模式（便捷接口）"""
    logger.info(f"开始快速规划: {args.project}")

    try:
        # 读取村庄数据
        if args.data:
            village_data = read_village_data(args.data)
        else:
            raise ValueError("快速模式需要提供 --data 参数")

        # 执行快速规划
        result = quick_planning(
            project_name=args.project,
            village_data=village_data,
            task=args.task or "制定村庄规划"
        )

        # 输出结果
        print("\n" + "="*80)
        print("快速规划成果")
        print("="*80 + "\n")
        print(result)

        # 保存结果
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(result)
            print(f"\n📄 结果已保存到: {args.output}")

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 执行失败: {str(e)}")
        sys.exit(1)


def run_legacy_mode(args):
    """旧版兼容模式"""
    logger.info(f"使用旧版接口执行任务: {args.task}")

    # 发出迁移提示
    print("⚠️  注意: 你正在使用旧版接口，建议迁移到新版接口以获得更好的性能。")
    print("   使用 --mode full 查看新版功能。\n")

    try:
        result = run_task(
            task=args.task,
            constraints=None,
            use_knowledge=True
        )

        print("\n" + "="*80)
        print("任务执行结果")
        print("="*80 + "\n")
        print(result)

        # 保存结果
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(str(result))
            print(f"\n📄 结果已保存到: {args.output}")

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 执行失败: {str(e)}")
        sys.exit(1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="村庄规划 AI 助手 - 基于层级化 LangGraph 架构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整规划流程
  python -m src.run_agent --mode full --project "某某村" --data village_data.txt

  # 仅现状分析
  python -m src.run_agent --mode analysis --project "某某村" --data village_data.txt

  # 快速规划
  python -m src.run_agent --mode quick --project "某某村" --data village_data.txt

  # 旧版兼容
  python -m src.run_agent --mode legacy --task "制定村庄规划"

更多信息请参阅 README.md 和 SUBGRAPH_USAGE.md
        """
    )

    # 基本参数
    parser.add_argument(
        "--mode",
        type=str,
        choices=["full", "analysis", "quick", "legacy"],
        default="full",
        help="运行模式: full(完整规划), analysis(仅分析), quick(快速), legacy(旧版)"
    )

    parser.add_argument(
        "--project",
        type=str,
        help="项目/村庄名称"
    )

    parser.add_argument(
        "--data",
        type=str,
        help="村庄数据文件路径"
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
        help="输出文件路径"
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
        version=f"村庄规划 AI 助手 v{__version__} ({__architecture__})"
    )

    args = parser.parse_args()

    # 打印版本信息
    print(f"村庄规划 AI 助手 v{__version__} ({__architecture__})")
    print("="*80 + "\n")

    # 根据模式执行
    if args.mode == "full":
        run_full_mode(args)
    elif args.mode == "analysis":
        run_analysis_mode(args)
    elif args.mode == "quick":
        run_quick_mode(args)
    elif args.mode == "legacy":
        run_legacy_mode(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
