"""
交互式命令行界面 (Interactive CLI)

提供逐步执行模式的交互式命令行界面，支持：
1. 显示执行进度
2. 命令处理（next/status/rollback/help/quit）
3. 状态查看
"""

import sys
from typing import Dict, Any, Optional, List
from ..utils.logger import get_logger

logger = get_logger(__name__)


class InteractiveCLI:
    """
    交互式命令行界面

    用于逐步执行模式的命令交互。
    """

    # 颜色代码
    COLOR_RESET = "\033[0m"
    COLOR_GREEN = "\033[92m"
    COLOR_YELLOW = "\033[93m"
    COLOR_BLUE = "\033[94m"
    COLOR_CYAN = "\033[96m"
    COLOR_BOLD = "\033[1m"

    def __init__(self, use_colors: bool = True):
        """
        初始化CLI

        Args:
            use_colors: 是否使用颜色
        """
        self.use_colors = use_colors and self._supports_color()
        self.command_history: List[str] = []
        self.current_state: Optional[Dict[str, Any]] = None

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

    def show_progress(self, state: Dict[str, Any]):
        """
        显示执行进度

        Args:
            state: 当前状态
        """
        self.current_state = state

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

    def show_menu(self) -> str:
        """
        显示交互式菜单

        Returns:
            用户选择的命令
        """
        print("\n可用命令:")
        print("-" * 80)
        print("  next / continue - 继续执行下一步")
        print("  status          - 查看当前状态")
        print("  checkpoints     - 列出所有checkpoint")
        print("  rollback <id>   - 回退到指定checkpoint")
        print("  review          - 审查当前报告")
        print("  help            - 显示帮助信息")
        print("  quit / exit     - 退出程序")
        print("-" * 80)

        while True:
            try:
                cmd = input(f"\n{self._colorize('>>> ', self.COLOR_GREEN)}").strip()
                if cmd:
                    self.command_history.append(cmd)
                return cmd
            except (EOFError, KeyboardInterrupt):
                print("\n" + self._colorize("检测到中断信号，正在退出...", self.COLOR_YELLOW))
                return "quit"

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
            执行结果字典 {
                "action": str,  # continue/rollback/review/quit
                "checkpoint_id": str,  # 目标checkpoint ID（如果是rollback）
                "modified_state": dict  # 修改后的状态（如果需要）
            }
        """
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
                return {"action": "none"}
            return self._cmd_rollback(parts[1], state)
        elif cmd in ['review', 'rv']:
            return self._cmd_review(state)
        elif cmd in ['help', 'h', '?']:
            return self._cmd_help()
        elif cmd in ['quit', 'exit', 'q']:
            return self._cmd_quit()
        else:
            print(self._colorize(f"未知命令: {cmd}，输入 'help' 查看帮助。", self.COLOR_YELLOW))
            return {"action": "none"}

    def _cmd_next(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """继续执行下一步"""
        print("\n" + self._colorize("继续执行...", self.COLOR_GREEN))
        return {"action": "continue"}

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

        return {"action": "none"}

    def _cmd_checkpoints(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """列出所有checkpoint"""
        checkpoint_manager = state.get("checkpoint_manager")

        if not checkpoint_manager:
            print(self._colorize("Checkpoint管理器未初始化。", self.COLOR_YELLOW))
            return {"action": "none"}

        checkpoints = checkpoint_manager.list_checkpoints()

        if not checkpoints:
            print(self._colorize("没有可用的checkpoint。", self.COLOR_YELLOW))
            return {"action": "none"}

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

        return {"action": "none"}

    def _cmd_rollback(self, checkpoint_id: str, state: Dict[str, Any]) -> Dict[str, Any]:
        """回退到指定checkpoint"""
        print("\n" + self._colorize(f"回退到checkpoint: {checkpoint_id}", self.COLOR_YELLOW))

        # 确认
        confirm = input("确认回退? 这会删除之后的生成文件。(Y/N): ").strip().upper()

        if confirm == 'Y':
            print(self._colorize("✓ 将执行回退操作", self.COLOR_GREEN))
            return {
                "action": "rollback",
                "checkpoint_id": checkpoint_id
            }
        else:
            print("已取消回退操作。")
            return {"action": "none"}

    def _cmd_review(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """审查当前报告"""
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
            return {"action": "none"}

        if not content:
            print(self._colorize("报告内容为空。", self.COLOR_YELLOW))
            return {"action": "none"}

        # 显示报告预览
        print(f"\n{title}:")
        print("-" * 80)
        preview = content[:500]
        print(preview)
        if len(content) > 500:
            print("\n... (使用其他命令查看完整内容) ...")
        print("-" * 80)

        return {"action": "none"}

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
            ("review", "审查当前层级的报告"),
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

        return {"action": "none"}

    def _cmd_quit(self) -> Dict[str, Any]:
        """退出程序"""
        print("\n" + self._colorize("程序已退出。", self.COLOR_YELLOW))
        return {"action": "quit"}

    def get_command_history(self) -> List[str]:
        """获取命令历史"""
        return self.command_history.copy()


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    print("=== 测试InteractiveCLI ===\n")

    cli = InteractiveCLI()

    # 模拟状态
    test_state = {
        "project_name": "测试村",
        "current_layer": 2,
        "layer_1_completed": True,
        "layer_2_completed": False,
        "layer_3_completed": False,
        "analysis_report": "这是现状分析报告内容...",
        "planning_concept": "",
        "detailed_plan": "",
        "step_mode": True,
        "step_level": "layer",
        "last_checkpoint_id": "checkpoint_001_layer1_completed",
        "checkpoint_manager": None
    }

    # 显示进度
    cli.show_progress(test_state)

    # 显示菜单
    print("\n输入命令测试 (输入 'quit' 退出):")

    while True:
        command = cli.show_menu()
        result = cli.execute_command(command, test_state)

        if result.get("action") == "quit":
            break
        elif result.get("action") == "continue":
            print("继续执行...")
            break
