"""
村庄规划 Agent 运行入口

支持多种运行模式：
1. 完整规划流程（full）
2. 仅现状分析（analysis）
3. 快速规划（quick）
4. 逐步执行模式（step）- 新增
5. 从checkpoint恢复（resume）- 新增

支持的文件格式：txt, pdf, docx, md, pptx, xlsx等

使用方法：
    # 完整规划流程
    python -m src.run_agent --mode full --project "某某村" --data village_data.txt

    # 仅现状分析
    python -m src.run_agent --mode analysis --project "某某村" --data village_data.txt

    # 快速规划
    python -m src.run_agent --mode quick --project "某某村" --data village_data.txt

    # 逐步执行模式（新增）
    python -m src.run_agent --mode step --project "某某村" --data village_data.txt

    # 从checkpoint恢复（新增）
    python -m src.run_agent --mode resume --project "某某村" --resume-from checkpoint_001_layer1_completed
"""

import argparse
import sys
from pathlib import Path

from .agent import (
    run_village_planning,
    run_analysis_only,
    quick_analysis,
    quick_planning,
    __version__,
    __architecture__
)
from .main_graph import resume_from_checkpoint
from .tools.file_manager import read_village_data as _read_village_data
from .utils.logger import get_logger
from .utils.output_manager import create_output_manager

logger = get_logger(__name__)


def read_village_data(file_path: str) -> str:
    """
    从文件读取村庄数据（兼容旧接口）

    现在支持多种格式：txt, pdf, docx, md, pptx, xlsx等
    建议使用 VillageDataManager.load_data() 获取更多功能
    """
    return _read_village_data(file_path)


def read_multiple_village_data(data_arg: str) -> tuple[str, list[str]]:
    """
    从单个或多个文件读取村庄数据

    Args:
        data_arg: 数据参数，可以是单个文件路径或逗号分隔的多个文件路径

    Returns:
        tuple: (合并后的内容, 成功加载的文件信息列表)
    """
    from .tools.file_manager import VillageDataManager

    # 检测多个文件（逗号分隔）
    if ',' in data_arg:
        file_paths = [f.strip() for f in data_arg.split(',')]
        logger.info(f"检测到多个文件输入 ({len(file_paths)} 个文件)")
    else:
        file_paths = [data_arg]
        logger.info("检测到单个文件输入")

    # 批量加载
    manager = VillageDataManager()
    result = manager.batch_load_files(file_paths, merge=True)

    if not result["success"]:
        raise ValueError(f"文件加载失败: {result.get('error', '未知错误')}")

    # 收集成功信息
    success_info = []
    for file_path in file_paths:
        single_result = manager.load_data(file_path)
        if single_result["success"]:
            meta = single_result["metadata"]
            success_info.append(f"✓ {meta.get('filename', file_path)} ({meta.get('size', 0)} 字符)")

    # 报告失败的文件
    if result["metadata"].get("errors"):
        logger.warning("部分文件加载失败:")
        for error in result["metadata"]["errors"]:
            logger.warning(f"  ✗ {error}")

    return result["content"], success_info


def run_full_mode(args):
    """完整规划流程模式"""
    logger.info(f"开始完整规划流程: {args.project}")

    try:
        # 读取村庄数据
        if args.data:
            village_data, file_info = read_multiple_village_data(args.data)
            logger.info(f"成功加载 {len(file_info)} 个文件:")
            for info in file_info:
                logger.info(f"  {info}")
        else:
            raise ValueError("完整规划模式需要提供 --data 参数")

        # 创建输出管理器
        custom_output_path = args.output if hasattr(args, 'output') and args.output else None

        # 执行规划（run_village_planning 会自动创建 OutputManager）
        result = run_village_planning(
            project_name=args.project,
            village_data=village_data,
            task_description=args.task or "制定村庄总体规划方案",
            constraints=args.constraints or "无特殊约束",
            need_human_review=args.review,
            stream_mode=args.stream,
            custom_output_path=custom_output_path
        )

        # 输出结果
        if result['success']:
            print("\n" + "="*80)
            print("✅ 规划完成！")
            print("="*80)
            print(f"\n所有层级完成: {result.get('all_layers_completed', False)}")

            # 显示保存位置（如果有 OutputManager）
            output_manager = result.get("output_manager")
            if output_manager:
                print(output_manager.get_console_message())

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
            village_data, file_info = read_multiple_village_data(args.data)
            logger.info(f"成功加载 {len(file_info)} 个文件:")
            for info in file_info:
                logger.info(f"  {info}")
        else:
            raise ValueError("分析模式需要提供 --data 参数")

        # 创建输出管理器
        custom_output_path = args.output if hasattr(args, 'output') and args.output else None
        output_manager = create_output_manager(
            project_name=args.project,
            custom_output_path=custom_output_path
        )

        # 确保输出目录存在
        output_manager.ensure_directories()

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

            # 如果使用默认输出结构，保存分层结果
            if output_manager.use_default_structure:
                dimension_reports = result.get("dimension_reports", {})
                output_manager.save_layer1_results(
                    combined_report=report,
                    dimension_reports=dimension_reports
                )
                print(output_manager.get_console_message())
            elif custom_output_path:
                # 使用自定义路径，仅保存综合报告
                output_path = Path(custom_output_path)
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(report)
                print(f"\n📄 分析报告已保存到: {custom_output_path}")

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
            village_data, file_info = read_multiple_village_data(args.data)
            logger.info(f"成功加载 {len(file_info)} 个文件:")
            for info in file_info:
                logger.info(f"  {info}")
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


def run_step_mode(args):
    """逐步执行模式（新增）"""
    logger.info(f"开始逐步执行模式: {args.project}")

    try:
        # 读取村庄数据
        if args.data:
            village_data, file_info = read_multiple_village_data(args.data)
            logger.info(f"成功加载 {len(file_info)} 个文件:")
            for info in file_info:
                logger.info(f"  {info}")
        else:
            raise ValueError("逐步执行模式需要提供 --data 参数")

        # 创建输出管理器
        custom_output_path = args.output if hasattr(args, 'output') and args.output else None

        # 执行规划（启用step_mode）
        result = run_village_planning(
            project_name=args.project,
            village_data=village_data,
            task_description=args.task or "制定村庄总体规划方案",
            constraints=args.constraints or "无特殊约束",
            need_human_review=args.review,
            stream_mode=args.stream,
            custom_output_path=custom_output_path,
            step_mode=True,  # 启用逐步执行模式
            step_level=getattr(args, 'step_level', 'layer')
        )

        # 输出结果
        if result['success']:
            print("\n" + "="*80)
            print("✅ 逐步执行完成！")
            print("="*80)
            print(f"\n所有层级完成: {result.get('all_layers_completed', False)}")

            # 显示保存位置
            output_manager = result.get("output_manager")
            if output_manager:
                print(output_manager.get_console_message())

        else:
            print(f"\n❌ 执行失败: {result.get('error', '未知错误')}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 执行失败: {str(e)}")
        sys.exit(1)


def run_resume_mode(args):
    """从checkpoint恢复执行（新增）"""
    logger.info(f"从checkpoint恢复执行: {args.project}")

    try:
        # 检查必要参数
        if not hasattr(args, 'resume_from') or not args.resume_from:
            raise ValueError("恢复模式需要提供 --resume-from 参数")

        checkpoint_id = args.resume_from

        # 创建输出管理器
        custom_output_path = args.output if hasattr(args, 'output') and args.output else None
        output_manager = create_output_manager(
            project_name=args.project,
            custom_output_path=custom_output_path
        )

        # 从checkpoint恢复
        result = resume_from_checkpoint(
            checkpoint_id=checkpoint_id,
            project_name=args.project,
            output_manager=output_manager
        )

        # 输出结果
        if result['success']:
            print("\n" + "="*80)
            print("✅ 恢复执行完成！")
            print("="*80)
            print(f"\n从checkpoint恢复: {result.get('resumed_from', '未知')}")
            print(f"所有层级完成: {result.get('all_layers_completed', False)}")

            # 显示保存位置
            output_manager = result.get("output_manager")
            if output_manager:
                print(output_manager.get_console_message())

        else:
            print(f"\n❌ 恢复执行失败: {result.get('error', '未知错误')}")
            sys.exit(1)

    except Exception as e:
        logger.error(f"执行失败: {str(e)}", exc_info=True)
        print(f"\n❌ 执行失败: {str(e)}")
        sys.exit(1)


def list_checkpoints(args):
    """列出所有checkpoint（新增）"""
    logger.info(f"列出项目checkpoint: {args.project}")

    try:
        from .checkpoint.checkpoint_manager import CheckpointManager

        checkpoint_manager = CheckpointManager(args.project)
        checkpoints = checkpoint_manager.list_checkpoints()

        if not checkpoints:
            print(f"\n没有找到项目 '{args.project}' 的checkpoint")
            return

        print("\n" + "="*80)
        print(f"项目 '{args.project}' 的Checkpoint列表")
        print("="*80 + "\n")

        for i, cp in enumerate(checkpoints, 1):
            layer = cp.get("layer", "?")
            description = cp.get("description", "")
            checkpoint_id = cp.get("checkpoint_id", "")
            timestamp = cp.get("timestamp", "")

            print(f"{i}. Layer {layer}: {description}")
            print(f"   ID: {checkpoint_id}")
            if timestamp:
                print(f"   时间: {timestamp}")
            print()

        print("="*80)
        print(f"共 {len(checkpoints)} 个checkpoint")

    except Exception as e:
        logger.error(f"列出checkpoint失败: {str(e)}")
        print(f"\n❌ 列出checkpoint失败: {str(e)}")
        sys.exit(1)


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description="村庄规划 AI 助手 - 基于层级化 LangGraph 架构",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  # 完整规划流程（单个文件）
  python -m src.run_agent --mode full --project "某某村" --data village_data.txt

  # 完整规划流程（多个文件）
  python -m src.run_agent --mode full --project "某某村" --data file1.txt,file2.pdf

  # 仅现状分析（多个文件）
  python -m src.run_agent --mode analysis --project "某某村" --data data1.txt,data2.pdf

  # 快速规划
  python -m src.run_agent --mode quick --project "某某村" --data village_data.txt

更多信息请参阅 README.md 和 SUBGRAPH_USAGE.md
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
        version=f"村庄规划 AI 助手 v{__version__} ({__architecture__})"
    )

    # 新增参数：逐步执行模式
    parser.add_argument(
        "--step-level",
        type=str,
        choices=["layer", "dimension", "skill"],
        default="layer",
        help="逐步执行的暂停级别: layer(每层暂停), dimension(每维度暂停), skill(每skill暂停)"
    )

    # 新增参数：从checkpoint恢复
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

    args = parser.parse_args()

    # 处理 --list-checkpoints 参数
    if args.list_checkpoints:
        args.mode = "list-checkpoints"

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
    elif args.mode == "step":
        run_step_mode(args)
    elif args.mode == "resume":
        run_resume_mode(args)
    elif args.mode == "list-checkpoints":
        list_checkpoints(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
