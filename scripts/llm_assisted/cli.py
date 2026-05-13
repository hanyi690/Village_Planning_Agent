"""
CLI - Command Line Interface V2.0

Entry point for LLM-assisted generation pipeline.
"""

import argparse
import json
import logging
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from scripts.llm_assisted.pipeline import PipelineV2, PipelineResultV2, run_pipeline_v2


def setup_logging(verbose: bool = False):
    """Configure logging based on verbosity"""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="LLM辅助村庄规划文本生成工具 V2.0",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例用法:
  # V2.0 基本用法（指定三层文件）
  python scripts/llm_assisted/cli.py --layer1 docs/planning_export/layer1_现状分析.md --layer2 docs/planning_export/layer2_规划思路.md --layer3 docs/planning_export/layer3_详细规划.md --project 金田村

  # 详细模式
  python scripts/llm_assisted/cli.py --layer1 layer1.md --layer2 layer2.md --layer3 layer3.md --project 金田村 --verbose

  # JSON输出
  python scripts/llm_assisted/cli.py --layer1 layer1.md --layer2 layer2.md --layer3 layer3.md --project 金田村 --json
        """
    )

    parser.add_argument(
        "--layer1", "-l1",
        required=True,
        help="Layer1 Markdown文件路径（现状分析）"
    )

    parser.add_argument(
        "--layer2", "-l2",
        required=True,
        help="Layer2 Markdown文件路径（规划思路）"
    )

    parser.add_argument(
        "--layer3", "-l3",
        required=True,
        help="Layer3 Markdown文件路径（详细规划）"
    )

    parser.add_argument(
        "--output", "-o",
        default="output",
        help="输出目录路径 (默认: output)"
    )

    parser.add_argument(
        "--project", "-p",
        default="村庄规划",
        help="项目名称 (默认: 村庄规划)"
    )

    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="启用详细日志"
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="以JSON格式输出结果"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Validate input files
    for name, path in [("layer1", args.layer1), ("layer2", args.layer2), ("layer3", args.layer3)]:
        if not Path(path).exists():
            print(f"错误: {name}文件不存在: {path}", file=sys.stderr)
            sys.exit(1)

    # Run pipeline
    print(f"开始处理: {args.project}")
    print(f"Layer1: {args.layer1}")
    print(f"Layer2: {args.layer2}")
    print(f"Layer3: {args.layer3}")
    print(f"输出目录: {args.output}")
    print()

    try:
        result = run_pipeline_v2(
            layer1_path=args.layer1,
            layer2_path=args.layer2,
            layer3_path=args.layer3,
            output_dir=args.output,
            project_name=args.project
        )

        # Output result
        if args.json:
            output = {
                "success": result.success,
                "output_path": result.output_path,
                "markdown_path": result.markdown_path,
                "quality_report_path": result.quality_report_path,
                "knowledge_path": result.knowledge_path,
                "article_count": result.article_count,
                "quality_score": result.quality_score,
                "quality_passed": result.quality_passed,
                "prefab_count": result.prefab_count,
                "background_count": result.background_count,
                "execution_time_seconds": result.execution_time_seconds,
                "errors": result.errors,
                "warnings": result.warnings,
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print("\n" + "=" * 50)
            print("处理完成")
            print("=" * 50)
            print(f"状态: {'成功' if result.success else '失败'}")
            print(f"输出文件: {result.output_path}")
            print(f"Markdown文件: {result.markdown_path}")
            print(f"质量报告: {result.quality_report_path}")
            print(f"知识库: {result.knowledge_path}")
            print(f"生成条文: {result.article_count}/22")
            print(f"质量评分: {result.quality_score:.1f}分")
            print(f"质量通过: {'是' if result.quality_passed else '否'}")
            print(f"预制件数: {result.prefab_count}")
            print(f"背景信息数: {result.background_count}")
            print(f"执行时间: {result.execution_time_seconds:.2f}秒")

            if result.errors:
                print("\n错误:")
                for error in result.errors:
                    print(f"  - {error}")

            if result.warnings:
                print("\n警告:")
                for warning in result.warnings:
                    print(f"  - {warning}")

        sys.exit(0 if result.success else 1)

    except KeyboardInterrupt:
        print("\n用户中断")
        sys.exit(130)

    except Exception as e:
        print(f"\n错误: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
