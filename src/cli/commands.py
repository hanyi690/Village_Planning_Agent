"""
命令执行器

提供各种模式的命令执行逻辑。
"""

import sys
import argparse
import functools
from pathlib import Path
from typing import Dict, Any

from ..agent import (
    run_village_planning,
    run_analysis_only,
    quick_planning,
    __version__,
    __architecture__
)
from ..orchestration.main_graph import resume_from_checkpoint
from ..tools.file_manager import VillageDataManager
from ..tools.checkpoint_tool import CheckpointTool
from ..utils.logger import get_logger
from ..utils.output_manager import create_output_manager

logger = get_logger(__name__)


def read_multiple_village_data(data_arg: str) -> tuple[str, list[str]]:
    """
    从单个或多个文件读取村庄数据

    Args:
        data_arg: 数据参数，可以是单个文件路径或逗号分隔的多个文件路径

    Returns:
        tuple: (合并后的内容, 成功加载的文件信息列表)
    """
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


def _handle_command_errors(func):
    """命令执行错误处理装饰器"""
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except ValueError as e:
            # 参数错误，不需要完整堆栈
            logger.error(f"参数错误: {str(e)}")
            print(f"\n❌ {str(e)}")
            sys.exit(1)
        except Exception as e:
            # 其他错误，记录完整堆栈
            logger.error(f"执行失败: {str(e)}", exc_info=True)
            print(f"\n❌ 执行失败: {str(e)}")
            sys.exit(1)
    return wrapper


class CommandRunner:
    """命令执行器"""

    def __init__(self, args: argparse.Namespace):
        """
        初始化命令执行器

        Args:
            args: 解析后的命令行参数
        """
        self.args = args

    def _load_village_data(self, mode_name: str) -> tuple[str, list[str]]:
        """
        统一处理村庄数据加载

        Args:
            mode_name: 模式名称（用于错误消息）

        Returns:
            (village_data, file_info)

        Raises:
            ValueError: 当未提供 --data 参数时
        """
        if not self.args.data:
            raise ValueError(f"{mode_name}需要提供 --data 参数")

        village_data, file_info = read_multiple_village_data(self.args.data)
        logger.info(f"成功加载 {len(file_info)} 个文件:")
        for info in file_info:
            logger.info(f"  {info}")

        return village_data, file_info

    def _print_success(self, message: str):
        """打印成功消息"""
        print("\n" + "="*80)
        print(f"✅ {message}！")
        print("="*80)

    def _print_error(self, message: str, exit_code: int = 1):
        """打印错误消息并退出"""
        print(f"\n❌ {message}")
        sys.exit(exit_code)

    def _print_content_preview(self, content: str, title: str = "完整报告"):
        """打印内容预览"""
        if self.args.verbose:
            print("\n" + "="*80)
            print(f"{title}")
            print("="*80 + "\n")
            print(content)
        else:
            print("\n" + "="*80)
            print(f"内容预览（前2000字符）")
            print("="*80 + "\n")
            print(content[:2000])
            print("\n... (使用 --verbose 查看完整内容) ...")

    def _create_output_manager(self):
        """创建输出管理器"""
        return create_output_manager(
            project_name=self.args.project,
            custom_output_path=self.args.output
        )

    def _save_to_file(self, content: str, output_path: str):
        """保存内容到文件"""
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        print(f"\n📄 内容已保存到: {output_path}")

    def run(self):
        """基于mode执行"""
        mode = self.args.mode

        if mode == "full":
            self.run_full_mode()
        elif mode == "analysis":
            self.run_analysis_mode()
        elif mode == "quick":
            self.run_quick_mode()
        elif mode == "step":
            self.run_step_mode()
        elif mode == "resume":
            self.run_resume_mode()
        elif mode == "list-checkpoints":
            self.list_checkpoints()
        else:
            logger.error(f"未知模式: {mode}")
            sys.exit(1)

    @_handle_command_errors
    def run_full_mode(self):
        """完整规划流程模式"""
        logger.info(f"开始完整规划流程: {self.args.project}")

        # 统一数据加载
        village_data, _ = self._load_village_data("完整规划模式")

        # 执行规划
        result = run_village_planning(
            project_name=self.args.project,
            village_data=village_data,
            task_description=self.args.task or "制定村庄总体规划方案",
            constraints=self.args.constraints or "无特殊约束",
            need_human_review=self.args.review,
            stream_mode=self.args.stream,
            custom_output_path=self.args.output
        )

        # 统一输出处理
        if result['success']:
            self._print_success("规划完成")
            print(f"\n所有层级完成: {result.get('all_layers_completed', False)}")

            # 显示保存位置
            from ..utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            session_id = result.get("session_id")
            output_manager = registry.get(session_id) if session_id else None
            if output_manager:
                print(output_manager.get_console_message())

            # 打印内容预览
            self._print_content_preview(result['final_output'], "完整规划成果")
        else:
            self._print_error(f"规划失败: {result.get('error', '未知错误')}")

    @_handle_command_errors
    def run_analysis_mode(self):
        """仅现状分析模式"""
        logger.info(f"开始现状分析: {self.args.project}")

        # 统一数据加载
        village_data, _ = self._load_village_data("分析模式")

        # 创建输出管理器
        output_manager = self._create_output_manager()
        output_manager.ensure_directories()

        # 执行分析
        result = run_analysis_only(
            project_name=self.args.project,
            village_data=village_data
        )

        # 输出结果
        if result['success']:
            self._print_success("现状分析完成")

            report = result['analysis_report']

            # 如果使用默认输出结构，保存分层结果
            if output_manager.use_default_structure:
                dimension_reports = result.get("dimension_reports", {})
                output_manager.save_layer1_results(
                    combined_report=report,
                    dimension_reports=dimension_reports
                )
                print(output_manager.get_console_message())
            elif self.args.output:
                # 使用自定义路径，仅保存综合报告
                self._save_to_file(report, self.args.output)

            # 打印内容预览
            self._print_content_preview(report, "完整分析报告")
        else:
            self._print_error(f"分析失败: {result.get('analysis_report', '未知错误')}")

    @_handle_command_errors
    def run_quick_mode(self):
        """快速规划模式（便捷接口）"""
        logger.info(f"开始快速规划: {self.args.project}")

        # 统一数据加载
        village_data, _ = self._load_village_data("快速模式")

        # 执行快速规划
        result = quick_planning(
            project_name=self.args.project,
            village_data=village_data,
            task=self.args.task or "制定村庄规划"
        )

        # 输出结果
        print("\n" + "="*80)
        print("快速规划成果")
        print("="*80 + "\n")
        print(result)

        # 保存结果
        if self.args.output:
            self._save_to_file(result, self.args.output)

    @_handle_command_errors
    def run_step_mode(self):
        """逐步执行模式"""
        logger.info(f"开始逐步执行模式: {self.args.project}")

        # 统一数据加载
        village_data, _ = self._load_village_data("逐步执行模式")

        # 执行规划（启用step_mode）
        result = run_village_planning(
            project_name=self.args.project,
            village_data=village_data,
            task_description=self.args.task or "制定村庄总体规划方案",
            constraints=self.args.constraints or "无特殊约束",
            need_human_review=self.args.review,
            stream_mode=self.args.stream,
            custom_output_path=self.args.output,
            step_mode=True,
            step_level=getattr(self.args, 'step_level', 'layer')
        )

        # 输出结果
        if result['success']:
            self._print_success("逐步执行完成")
            print(f"\n所有层级完成: {result.get('all_layers_completed', False)}")

            # 显示保存位置
            from ..utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            session_id = result.get("session_id")
            output_manager = registry.get(session_id) if session_id else None
            if output_manager:
                print(output_manager.get_console_message())
        else:
            self._print_error(f"执行失败: {result.get('error', '未知错误')}")

    @_handle_command_errors
    def run_resume_mode(self):
        """从checkpoint恢复执行"""
        logger.info(f"从checkpoint恢复执行: {self.args.project}")

        # 检查必要参数
        if not hasattr(self.args, 'resume_from') or not self.args.resume_from:
            raise ValueError("恢复模式需要提供 --resume-from 参数")

        checkpoint_id = self.args.resume_from

        # 创建输出管理器
        output_manager = self._create_output_manager()

        # 从checkpoint恢复
        result = resume_from_checkpoint(
            checkpoint_id=checkpoint_id,
            project_name=self.args.project,
            output_manager=output_manager
        )

        # 输出结果
        if result['success']:
            self._print_success("恢复执行完成")
            print(f"\n从checkpoint恢复: {result.get('resumed_from', '未知')}")
            print(f"所有层级完成: {result.get('all_layers_completed', False)}")

            # 显示保存位置
            from ..utils.output_manager_registry import get_output_manager_registry
            registry = get_output_manager_registry()
            session_id = result.get("session_id")
            output_manager = registry.get(session_id) if session_id else None
            if output_manager:
                print(output_manager.get_console_message())
        else:
            self._print_error(f"恢复执行失败: {result.get('error', '未知错误')}")

    @_handle_command_errors
    def list_checkpoints(self):
        """列出所有checkpoint"""
        logger.info(f"列出项目checkpoint: {self.args.project}")

        checkpoint_manager = CheckpointTool(self.args.project)
        list_result = checkpoint_manager.list()

        if not list_result["success"] or not list_result["checkpoints"]:
            print(f"\n没有找到项目 '{self.args.project}' 的checkpoint")
            return

        checkpoints = list_result["checkpoints"]

        print("\n" + "="*80)
        print(f"项目 '{self.args.project}' 的Checkpoint列表")
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
