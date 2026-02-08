"""
InteractiveTool - DEPRECATED

This module is deprecated and only kept for CLI mode compatibility.
Web applications should use WebReviewTool instead.

To use CLI mode:
    from src.tools.interactive_tool import InteractiveTool  # noqa

To use web mode:
    from src.tools.web_review_tool import WebReviewTool

提供交互式命令行界面功能：
1. 人工审查报告（approve/reject/rollback）
2. 逐步执行模式（命令交互）
3. 进度显示
4. 菜单系统

遵循tool pattern：所有方法返回结构化Dict结果。

Deprecated in v5.0 - Use WebReviewTool for web applications
"""

import sys
from typing import Dict, Any, Optional, List

from ..utils.logger import get_logger
from ..utils.checkpoint_manager import get_checkpoint_manager

logger = get_logger(__name__)

# Deprecation warning
import warnings
warnings.warn(
    "InteractiveTool is deprecated for web applications. Use WebReviewTool instead.",
    DeprecationWarning,
    stacklevel=2
)


# ==========================================
# 交互式工具类
# ==========================================

class InteractiveTool:
    """
    交互式工具

    提供人工审查和CLI交互功能，遵循tool pattern。
    """

    # 颜色代码
    COLOR_RESET = "\033[0m"
    COLOR_RED = "\033[91m"
    COLOR_GREEN = "\033[92m"
    COLOR_YELLOW = "\033[93m"
    COLOR_BLUE = "\033[94m"
    COLOR_CYAN = "\033[96m"
    COLOR_BOLD = "\033[1m"

    # 分页显示
    PAGE_SIZE = 30

    def __init__(self, use_colors: bool = True):
        """
        初始化交互式工具

        Args:
            use_colors: 是否使用颜色
        """
        self.use_colors = use_colors and self._supports_color()
        self.review_history: List[Dict[str, Any]] = []
        self.command_history: List[str] = []

    def _has_stdin(self) -> bool:
        """检测是否有可用的标准输入（用于区分CLI和Web环境）"""
        try:
            # Try to read from stdin without blocking
            import select
            if hasattr(select, 'select'):
                # Unix-like systems
                return bool(select.select([sys.stdin], [], [], 0)[0])
            else:
                # Windows or no select available - try a different approach
                # Check if stdin is a TTY
                return sys.stdin.isatty()
        except:
            # If detection fails, assume we have stdin
            return True

    def _supports_color(self) -> bool:
        """检测终端是否支持颜色"""
        try:
            if sys.platform == 'win32':
                try:
                    import colorama
                    colorama.init()
                    return True
                except ImportError:
                    return False
            return True
        except:
            return False

    def _colorize(self, text: str, color: str) -> str:
        """给文本添加颜色"""
        if self.use_colors:
            return f"{color}{text}{self.COLOR_RESET}"
        return text

    # ==========================================
    # 人工审查功能
    # ==========================================

    def review_content(
        self,
        content: str,
        title: str,
        allow_rollback: bool = False,
        available_checkpoints: Optional[List[Dict[str, Any]]] = None,
        available_dimensions: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """
        审查内容

        Args:
            content: 要审查的内容
            title: 标题
            allow_rollback: 是否允许回退
            available_checkpoints: 可用的checkpoint列表
            available_dimensions: 可用维度列表（用于维度级修复）

        Returns:
            结构化结果字典 {
                "success": bool,
                "action": str,  # approve/reject/rollback/quit/cancel
                "feedback": str,
                "checkpoint_id": str,
                "target_dimensions": List[str],  # 选择的维度（可选）
                "error": str
            }
        """
        try:
            # Check if running in web environment (no stdin)
            if not self._has_stdin():
                logger.warning("[InteractiveTool] Web environment detected (no stdin), auto-approving review")
                return {
                    "success": True,
                    "action": "approve",
                    "feedback": "",
                    "checkpoint_id": "",
                    "error": ""
                }

            print("\n" + "=" * 80)
            print(self._colorize(f"  人工审查: {title}", self.COLOR_BOLD + self.COLOR_CYAN))
            print("=" * 80 + "\n")

            # 显示摘要
            self._show_summary(content)

            while True:
                # 显示菜单
                print("\n" + "-" * 80)
                print("请选择操作:")
                print("-" * 80)
                print("  1. [A]pprove - 通过审查，继续执行")
                print("  2. [R]eject - 驳回，需要修复")
                print("  3. [V]iew - 查看完整内容")
                if allow_rollback and available_checkpoints:
                    print("  4. [L]Rollback - 回退到之前的checkpoint")
                print("  5. [Q]uit - 退出程序")
                print("-" * 80)

                choice = input(f"\n请输入选择 (A/R/V{'/L' if allow_rollback and available_checkpoints else ''}/Q): ").strip().upper()

                if choice in ['A', 'APPROVE', '1']:
                    result = self._handle_approve()
                    self.review_history.append(result)
                    return {
                        "success": True,
                        "action": result["action"],
                        "feedback": result["feedback"],
                        "checkpoint_id": "",
                        "error": ""
                    }
                elif choice in ['R', 'REJECT', '2']:
                    result = self._handle_reject(available_dimensions)
                    self.review_history.append(result)
                    return {
                        "success": True,
                        "action": result["action"],
                        "feedback": result["feedback"],
                        "checkpoint_id": "",
                        "target_dimensions": result.get("target_dimensions"),
                        "error": ""
                    }
                elif choice in ['V', 'VIEW', '3']:
                    self._handle_view(content)
                    continue
                elif choice in ['L', 'ROLLBACK', '4'] and allow_rollback and available_checkpoints:
                    result = self._handle_rollback(available_checkpoints)
                    self.review_history.append(result)
                    return {
                        "success": True,
                        "action": result["action"],
                        "feedback": result["feedback"],
                        "checkpoint_id": result.get("checkpoint_id", ""),
                        "error": ""
                    }
                elif choice in ['Q', 'QUIT', '5']:
                    result = self._handle_quit()
                    self.review_history.append(result)
                    return {
                        "success": True,
                        "action": result["action"],
                        "feedback": result["feedback"],
                        "checkpoint_id": "",
                        "error": ""
                    }
                else:
                    print(self._colorize("无效的选择，请重试。", self.COLOR_RED))

        except EOFError:
            # Web environment or stdin closed - auto-approve to continue execution
            logger.warning("[InteractiveTool] EOF detected (web environment), auto-approving review")
            return {
                "success": True,
                "action": "approve",
                "feedback": "",
                "checkpoint_id": "",
                "error": ""
            }
        except Exception as e:
            logger.error(f"[InteractiveTool] 审查内容时出错: {e}")
            return {
                "success": False,
                "action": "cancel",
                "feedback": "",
                "checkpoint_id": "",
                "error": str(e)
            }

    def _show_summary(self, content: str):
        """显示内容摘要"""
        lines = content.split('\n')
        total_lines = len(lines)
        total_chars = len(content)

        # 显示统计信息
        print(f"内容长度: {total_chars} 字符, {total_lines} 行\n")

        # 显示前15行预览
        preview_lines = min(15, total_lines)
        print("内容预览（前{}行）:".format(preview_lines))
        print("-" * 80)

        for i, line in enumerate(lines[:preview_lines]):
            print(f"{i+1:3d}. {line}")

        if total_lines > preview_lines:
            print(f"\n... (还有 {total_lines - preview_lines} 行，使用 [V]iew 查看完整内容) ...")

        print("-" * 80)

    def _handle_approve(self) -> Dict[str, Any]:
        """处理通过操作"""
        print("\n" + self._colorize("✓ 审查通过，将继续执行下一阶段。", self.COLOR_GREEN))
        return {
            "action": "approve",
            "feedback": ""
        }

    def _handle_reject(self, available_dimensions: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        处理驳回操作 - 增强版：支持精确选择维度

        Args:
            available_dimensions: 可用维度列表（可选）

        Returns:
            结果字典，包含action, feedback, 和可选的target_dimensions
        """
        print("\n" + self._colorize("✗ 审查驳回，请选择需要修复的维度。", self.COLOR_YELLOW))

        # 1. 显示可用维度
        selected_dimensions = None
        if available_dimensions:
            print("\n可用维度:")
            for i, dim in enumerate(available_dimensions, 1):
                print(f"  {i}. {dim}")

            # 2. 用户选择维度
            while True:
                choice = input("\n请选择需要修复的维度（多个用逗号分隔，如 1,3,5，按回车跳过）: ").strip()

                if not choice:
                    # 跳过维度选择，使用自动识别
                    print(self._colorize("已跳过维度选择，将通过反馈关键词自动识别维度。", self.COLOR_YELLOW))
                    selected_dimensions = None
                    break

                try:
                    # 解析选择
                    selected_indices = [int(x.strip()) for x in choice.split(',')]
                    selected_dimensions = [
                        available_dimensions[i-1]
                        for i in selected_indices
                        if 0 < i <= len(available_dimensions)
                    ]

                    if not selected_dimensions:
                        print(self._colorize("无效的选择，请重试。", self.COLOR_RED))
                        continue

                    print(f"\n已选择的维度: {', '.join(selected_dimensions)}")
                    break
                except ValueError:
                    print(self._colorize("输入格式错误，请使用数字，多个用逗号分隔。", self.COLOR_RED))
        else:
            # 没有提供维度列表，使用默认的自动识别
            print(self._colorize("未提供维度列表，将通过反馈关键词自动识别维度。", self.COLOR_YELLOW))

        # 3. 输入反馈
        while True:
            feedback = input("\n请输入反馈意见（按回车完成输入）: ").strip()

            if not feedback:
                print(self._colorize("反馈不能为空，请重新输入。", self.COLOR_RED))
                continue

            # 4. 确认
            print("\n修复配置:")
            print("-" * 80)
            if selected_dimensions:
                print(f"目标维度: {', '.join(selected_dimensions)}")
            else:
                print(f"目标维度: 自动识别（通过反馈关键词）")
            print(f"反馈意见: {feedback}")
            print("-" * 80)

            confirm = input("\n确认提交? (Y/N): ").strip().upper()

            if confirm == 'Y':
                print("\n" + self._colorize("✓ 反馈已提交，将触发修复流程。", self.COLOR_GREEN))
                result = {
                    "action": "reject",
                    "feedback": feedback
                }
                # 添加目标维度字段
                if selected_dimensions:
                    result["target_dimensions"] = selected_dimensions
                return result

    def _handle_view(self, content: str):
        """处理查看完整内容操作"""
        print("\n" + "=" * 80)
        print("完整内容")
        print("=" * 80 + "\n")

        lines = content.split('\n')

        # 分页显示
        current_line = 0

        while current_line < len(lines):
            # 显示一页
            end_line = min(current_line + self.PAGE_SIZE, len(lines))

            for i in range(current_line, end_line):
                print(f"{i+1:4d}. {lines[i]}")

            current_line = end_line

            # 如果还有更多内容，暂停
            if current_line < len(lines):
                print(f"\n--- 显示 {current_line}/{len(lines)} 行 ---")
                cmd = input("按回车继续，输入 'q' 退出查看: ").strip().lower()

                if cmd == 'q':
                    break

                print()  # 空行分隔

        print("\n" + "=" * 80)
        print("内容显示完成")
        print("=" * 80)

    def _handle_rollback(self, available_checkpoints: List[Dict[str, Any]]) -> Dict[str, Any]:
        """处理回退操作"""
        print("\n" + self._colorize("↺ 回退操作", self.COLOR_YELLOW))
        print("=" * 80)

        # 显示可用checkpoint
        print("\n可用的Checkpoint:")
        print("-" * 80)

        for i, cp in enumerate(available_checkpoints, 1):
            layer = cp.get("layer", "?")
            description = cp.get("description", "")
            checkpoint_id = cp.get("checkpoint_id", "")

            print(f"{i}. Layer {layer}: {description}")
            print(f"   ID: {checkpoint_id}")
            if cp.get("timestamp"):
                print(f"   时间: {cp['timestamp']}")
            print()

        print("-" * 80)

        while True:
            choice = input("\n请选择要回退到的Checkpoint编号 (输入0取消): ").strip()

            if choice == '0':
                print("已取消回退操作。")
                return {
                    "action": "cancel",
                    "feedback": ""
                }

            try:
                index = int(choice) - 1
                if 0 <= index < len(available_checkpoints):
                    selected = available_checkpoints[index]
                    checkpoint_id = selected["checkpoint_id"]

                    # 确认回退
                    confirm = input(
                        f"\n确认回退到 '{selected['description']}'? "
                        f"这会删除之后的生成文件。(Y/N): "
                    ).strip().upper()

                    if confirm == 'Y':
                        print("\n" + self._colorize(f"✓ 将回退到: {checkpoint_id}", self.COLOR_GREEN))

                        return {
                            "action": "rollback",
                            "feedback": f"回退到 {selected['description']}",
                            "checkpoint_id": checkpoint_id
                        }
                    else:
                        print("已取消回退操作。")
                        return {
                            "action": "cancel",
                            "feedback": ""
                        }
                else:
                    print(self._colorize("无效的编号，请重试。", self.COLOR_RED))
            except ValueError:
                print(self._colorize("请输入有效的数字。", self.COLOR_RED))

    def _handle_quit(self) -> Dict[str, Any]:
        """处理退出操作"""
        print("\n" + self._colorize("程序已退出。", self.COLOR_YELLOW))
        return {
            "action": "quit",
            "feedback": "用户退出"
        }

    # ==========================================
    # 逐步执行模式功能
    # ==========================================

    def show_progress(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        显示执行进度

        Args:
            state: 当前状态

        Returns:
            结构化结果字典 {
                "success": bool,
                "error": str
            }
        """
        try:
            print("\n" + "=" * 80)
            print(self._colorize("  执行进度", self.COLOR_BOLD + self.COLOR_CYAN))
            print("=" * 80)

            # 项目信息
            print(f"\n项目: {state.get('project_name', '未知')}")
            print(f"当前层级: Layer {state.get('current_layer', 1)}")

            # 各层完成状态
            print("\n完成状态:")
            layer_1_done = state.get("layer_1_completed", False)
            layer_2_done = state.get("layer_2_completed", False)
            layer_3_done = state.get("layer_3_completed", False)

            print(f"  Layer 1 (现状分析): {'✓' if layer_1_done else '○'}")
            print(f"  Layer 2 (规划思路): {'✓' if layer_2_done else '○'}")
            print(f"  Layer 3 (详细规划): {'✓' if layer_3_done else '○'}")

            # 最后的checkpoint
            last_cp = state.get("last_checkpoint_id", "")
            if last_cp:
                print(f"\n最后Checkpoint: {last_cp}")

            print("=" * 80)

            return {
                "success": True,
                "error": ""
            }

        except Exception as e:
            logger.error(f"[InteractiveTool] 显示进度时出错: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    def show_menu(self) -> Dict[str, Any]:
        """
        显示交互式菜单并获取用户输入

        Returns:
            结构化结果字典 {
                "success": bool,
                "command": str,
                "error": str
            }
        """
        try:
            print("\n可用命令:")
            print("-" * 80)
            print("  next / continue - 继续执行下一步")
            print("  status          - 查看当前状态")
            print("  checkpoints     - 列出所有checkpoint")
            print("  rollback <id>   - 回退到指定checkpoint")
            print("  review          - 审查当前报告（预览模式）")
            print("  review -f       - 审查当前报告（完整审查模式）")
            print("  help            - 显示帮助信息")
            print("  quit / exit     - 退出程序")
            print("-" * 80)

            cmd = input(f"\n{self._colorize('>>> ', self.COLOR_GREEN)}").strip()
            if cmd:
                self.command_history.append(cmd)

            return {
                "success": True,
                "command": cmd,
                "error": ""
            }

        except (EOFError, KeyboardInterrupt):
            print("\n" + self._colorize("检测到中断信号，正在退出...", self.COLOR_YELLOW))
            return {
                "success": True,
                "command": "quit",
                "error": ""
            }
        except Exception as e:
            logger.error(f"[InteractiveTool] 显示菜单时出错: {e}")
            return {
                "success": False,
                "command": "",
                "error": str(e)
            }

    def execute_command(
        self,
        command: str,
        state: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        执行命令

        Args:
            command: 命令字符串
            state: 当前状态

        Returns:
            结构化结果字典 {
                "success": bool,
                "action": str,  # continue/rollback/review/quit/none
                "checkpoint_id": str,
                "modified_state": dict,
                "error": str
            }
        """
        try:
            parts = command.lower().split()
            cmd = parts[0] if parts else ""

            if cmd in ['next', 'continue', 'n', 'c']:
                return self._cmd_next(state)
            elif cmd in ['status', 's']:
                return self._cmd_status(state)
            elif cmd in ['checkpoints', 'cp', 'list']:
                return self._cmd_checkpoints(state)
            elif cmd in ['rollback', 'rb']:
                if len(parts) < 2:
                    print(self._colorize("用法: rollback <checkpoint_id>", self.COLOR_YELLOW))
                    return {
                        "success": True,
                        "action": "none",
                        "checkpoint_id": "",
                        "modified_state": {},
                        "error": ""
                    }
                return self._cmd_rollback(parts[1], state)
            elif cmd in ['review', 'rv']:
                # 检查 --feedback 或 -f 标志
                full_review = '--feedback' in parts or '-f' in parts
                return self._cmd_review(state, full_review=full_review)
            elif cmd in ['help', 'h', '?']:
                return self._cmd_help()
            elif cmd in ['quit', 'exit', 'q']:
                return self._cmd_quit()
            else:
                print(self._colorize(f"未知命令: {cmd}，输入 'help' 查看帮助。", self.COLOR_YELLOW))
                return {
                    "success": True,
                    "action": "none",
                    "checkpoint_id": "",
                    "modified_state": {},
                    "error": ""
                }

        except Exception as e:
            logger.error(f"[InteractiveTool] 执行命令时出错: {e}")
            return {
                "success": False,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": str(e)
            }

    def _cmd_next(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """继续执行下一步"""
        print("\n" + self._colorize("继续执行...", self.COLOR_GREEN))
        return {
            "success": True,
            "action": "continue",
            "checkpoint_id": "",
            "modified_state": {},
            "error": ""
        }

    def _cmd_status(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """查看当前状态"""
        self.show_progress(state)

        # 显示更多信息
        print("\n详细信息:")
        print("-" * 80)

        # 报告长度
        if state.get("analysis_report"):
            print(f"现状分析报告: {len(state['analysis_report'])} 字符")
        if state.get("planning_concept"):
            print(f"规划思路报告: {len(state['planning_concept'])} 字符")
        if state.get("detailed_plan"):
            print(f"详细规划报告: {len(state['detailed_plan'])} 字符")

        # 模式信息
        step_mode = state.get("step_mode", False)
        step_level = state.get("step_level", "layer")
        print(f"逐步模式: {'启用 (' + step_level + ')' if step_mode else '禁用'}")

        print("-" * 80)

        return {
            "success": True,
            "action": "none",
            "checkpoint_id": "",
            "modified_state": {},
            "error": ""
        }

    def _cmd_checkpoints(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有checkpoint"""
        checkpoint_manager = get_checkpoint_manager(
            project_name=state.get("project_name", "default"),
            timestamp=state.get("session_id")
        )

        if not checkpoint_manager:
            print(self._colorize("Checkpoint管理器未初始化。", self.COLOR_YELLOW))
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

        # 新版本CheckpointTool
        result = checkpoint_manager.list()
        checkpoints = result.get("checkpoints", [])

        if not checkpoints:
            print(self._colorize("没有可用的checkpoint。", self.COLOR_YELLOW))
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

        print("\n可用的Checkpoint:")
        print("-" * 80)

        for i, cp in enumerate(checkpoints, 1):
            layer = cp.get("layer", "?")
            description = cp.get("description", "")
            checkpoint_id = cp.get("checkpoint_id", "")

            print(f"{i}. Layer {layer}: {description}")
            print(f"   ID: {checkpoint_id}")
            if cp.get("timestamp"):
                print(f"   时间: {cp['timestamp']}")

        print("-" * 80)
        print(f"共 {len(checkpoints)} 个checkpoint")
        print("-" * 80)

        return {
            "success": True,
            "action": "none",
            "checkpoint_id": "",
            "modified_state": {},
            "error": ""
        }

    def _cmd_rollback(self, checkpoint_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """回退到指定checkpoint"""
        print("\n" + self._colorize(f"回退到checkpoint: {checkpoint_id}", self.COLOR_YELLOW))

        # 确认
        confirm = input("确认回退? 这会删除之后的生成文件。(Y/N): ").strip().upper()

        if confirm == 'Y':
            print(self._colorize("✓ 将执行回退操作", self.COLOR_GREEN))
            return {
                "success": True,
                "action": "rollback",
                "checkpoint_id": checkpoint_id,
                "modified_state": {},
                "error": ""
            }
        else:
            print("已取消回退操作。")
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

    def _cmd_review(self, state: Dict[str, Any], full_review: bool = False) -> Dict[str, Any]:
        """审查当前报告

        Args:
            state: 当前状态
            full_review: 是否启用完整审查模式（--feedback参数）
        """
        if full_review:
            return self._cmd_review_full(state)
        else:
            return self._cmd_review_preview(state)

    def _cmd_review_preview(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """预览模式（显示前500字符）"""
        # 获取当前层级对应的内容
        current_layer = state.get("current_layer", 1)

        if current_layer == 2:
            content = state.get("analysis_report", "")
            title = "现状分析报告"
        elif current_layer == 3:
            content = state.get("planning_concept", "")
            title = "规划思路报告"
        elif current_layer >= 4:
            content = state.get("detailed_plan", "")
            title = "详细规划报告"
        else:
            print(self._colorize("当前没有可审查的报告。", self.COLOR_YELLOW))
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

        if not content:
            print(self._colorize("报告内容为空。", self.COLOR_YELLOW))
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

        # 显示报告预览
        print(f"\n{title}:")
        print("-" * 80)
        preview = content[:500]
        print(preview)
        if len(content) > 500:
            print("\n... (使用 review -f 查看完整审查) ...")
        print("-" * 80)

        return {
            "success": True,
            "action": "none",
            "checkpoint_id": "",
            "modified_state": {},
            "error": ""
        }

    def _cmd_review_full(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """完整审查模式（支持 approve/reject/rollback）"""
        # 1. 获取当前层级对应的内容
        current_layer = state.get("current_layer", 1)

        if current_layer == 2:
            content = state.get("analysis_report", "")
            title = "现状分析报告"
        elif current_layer == 3:
            content = state.get("planning_concept", "")
            title = "规划思路报告"
        elif current_layer >= 4:
            content = state.get("detailed_plan", "")
            title = "详细规划报告"
        else:
            print(self._colorize("当前没有可审查的报告。", self.COLOR_YELLOW))
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

        if not content:
            print(self._colorize("报告内容为空。", self.COLOR_YELLOW))
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

        # 2. 获取checkpoint列表（用于回退）
        checkpoint_manager = get_checkpoint_manager(
            project_name=state.get("project_name", "default"),
            timestamp=state.get("session_id")
        )
        available_checkpoints = []
        if checkpoint_manager:
            list_result = checkpoint_manager.list()
            if list_result["success"]:
                available_checkpoints = list_result["checkpoints"]

        # 3. 调用现有的 review_content UI
        result = self.review_content(
            content=content,
            title=title,
            allow_rollback=True,
            available_checkpoints=available_checkpoints
        )

        action = result.get("action", "")

        if action == "reject":
            # 关键：直接设置 human_feedback 和 need_revision
            feedback = result.get("feedback", "")
            print(f"\n{self._colorize('✓ 反馈已记录，输入', self.COLOR_GREEN)} 'next' {self._colorize('触发修复。', self.COLOR_GREEN)}")
            return {
                "success": True,
                "action": "reject",
                "checkpoint_id": "",
                "modified_state": {
                    "human_feedback": feedback,      # 复用现有字段
                    "need_revision": True,           # 复用现有字段
                },
                "error": ""
            }
        elif action == "rollback":
            checkpoint_id = result.get("checkpoint_id", "")
            print(f"\n{self._colorize('✓ 回退已选择，输入', self.COLOR_GREEN)} 'next' {self._colorize('执行回退。', self.COLOR_GREEN)}")
            return {
                "success": True,
                "action": "rollback",
                "checkpoint_id": checkpoint_id,
                "modified_state": {
                    "trigger_rollback": True,
                    "rollback_target": checkpoint_id,
                },
                "error": ""
            }
        elif action == "approve":
            print(f"\n{self._colorize('✓ 审查通过，输入', self.COLOR_GREEN)} 'next' {self._colorize('继续。', self.COLOR_GREEN)}")
            return {
                "success": True,
                "action": "approve",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }
        elif action == "quit":
            return {
                "success": True,
                "action": "quit",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }
        else:
            return {
                "success": True,
                "action": "none",
                "checkpoint_id": "",
                "modified_state": {},
                "error": ""
            }

    def _cmd_help(self) -> Dict[str, Any]:
        """显示帮助信息"""
        print("\n" + "=" * 80)
        print("帮助信息")
        print("=" * 80)

        commands = [
            ("next / continue", "继续执行下一步"),
            ("status", "查看当前状态和进度"),
            ("checkpoints", "列出所有可用的checkpoint"),
            ("rollback <id>", "回退到指定的checkpoint"),
            ("review", "审查当前层级的报告（预览模式）"),
            ("review -f / review --feedback", "审查当前层级的报告（完整审查模式）"),
            ("help", "显示此帮助信息"),
            ("quit / exit", "退出程序")
        ]

        for cmd, desc in commands:
            print(f"  {cmd:20s} - {desc}")

        print("\n示例:")
        print("  >>> next")
        print("  >>> rollback checkpoint_001_layer1_completed")
        print("  >>> status")

        print("=" * 80)

        return {
            "success": True,
            "action": "none",
            "checkpoint_id": "",
            "modified_state": {},
            "error": ""
        }

    def _cmd_quit(self) -> Dict[str, Any]:
        """退出程序"""
        print("\n" + self._colorize("程序已退出。", self.COLOR_YELLOW))
        return {
            "success": True,
            "action": "quit",
            "checkpoint_id": "",
            "modified_state": {},
            "error": ""
        }

    def get_review_history(self) -> List[Dict[str, Any]]:
        """获取审查历史"""
        return self.review_history.copy()

    def get_command_history(self) -> List[str]:
        """获取命令历史"""
        return self.command_history.copy()


# ==========================================
# 便捷函数
# ==========================================

def review_report(
    content: str,
    title: str,
    allow_rollback: bool = False,
    available_checkpoints: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """
    便捷函数：审查报告

    Args:
        content: 报告内容
        title: 报告标题
        allow_rollback: 是否允许回退
        available_checkpoints: 可用的checkpoint列表

    Returns:
        审查结果字典 {
            "action": str,
            "feedback": str,
            "checkpoint_id": str
        }
    """
    tool = InteractiveTool()
    result = tool.review_content(content, title, allow_rollback, available_checkpoints)
    return {
        "action": result["action"],
        "feedback": result["feedback"],
        "checkpoint_id": result["checkpoint_id"]
    }


def show_progress_and_wait(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    便捷函数：显示进度并等待用户命令

    Args:
        state: 当前状态

    Returns:
        命令执行结果字典 {
            "action": str,
            "checkpoint_id": str
        }
    """
    tool = InteractiveTool()
    tool.show_progress(state)

    while True:
        menu_result = tool.show_menu()
        if not menu_result["success"]:
            continue

        command = menu_result["command"]
        exec_result = tool.execute_command(command, state)

        action = exec_result.get("action", "")

        if action in ["continue", "rollback", "quit"]:
            return {
                "action": action,
                "checkpoint_id": exec_result.get("checkpoint_id", "")
            }


__all__ = [
    "InteractiveTool",
    "review_report",
    "show_progress_and_wait",
]
