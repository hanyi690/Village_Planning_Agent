"""
人工审查界面 (Review UI)

提供命令行交互式审查功能，支持：
1. 显示报告摘要和全文
2. Approve/Reject/Modify/View/Rollback操作
3. 用户反馈收集
"""

import sys
from typing import Dict, Any, Optional, List
from ..utils.logger import get_logger

logger = get_logger(__name__)


class ReviewUI:
    """
    人工审查界面

    提供交互式命令行界面用于人工审查报告内容。
    """

    # 颜色代码（ANSI）
    COLOR_RESET = "\033[0m"
    COLOR_RED = "\033[91m"
    COLOR_GREEN = "\033[92m"
    COLOR_YELLOW = "\033[93m"
    COLOR_BLUE = "\033[94m"
    COLOR_CYAN = "\033[96m"
    COLOR_BOLD = "\033[1m"

    # 每页显示行数
    PAGE_SIZE = 30

    def __init__(self, use_colors: bool = True):
        """
        初始化审查界面

        Args:
            use_colors: 是否使用颜色（Windows可能不支持）
        """
        self.use_colors = use_colors and self._supports_color()
        self.history: List[Dict[str, Any]] = []

    def _supports_color(self) -> bool:
        """检测终端是否支持颜色"""
        try:
            # Windows检测
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

    def review_content(
        self,
        content: str,
        title: str,
        allow_rollback: bool = True,
        available_checkpoints: Optional[List[Dict[str, Any]]] = None
    ) -> Dict[str, Any]:
        """
        审查内容

        Args:
            content: 要审查的内容
            title: 标题
            allow_rollback: 是否允许回退
            available_checkpoints: 可用的checkpoint列表

        Returns:
            审查结果字典 {
                "action": str,  # approve/reject/modify/view/rollback/quit
                "feedback": str,  # 用户反馈
                "checkpoint_id": str  # 目标checkpoint ID（如果action是rollback）
            }
        """
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
                return self._handle_approve()
            elif choice in ['R', 'REJECT', '2']:
                return self._handle_reject()
            elif choice in ['V', 'VIEW', '3']:
                self._handle_view(content)
            elif choice in ['L', 'ROLLBACK', '4'] and allow_rollback and available_checkpoints:
                return self._handle_rollback(available_checkpoints)
            elif choice in ['Q', 'QUIT', '5']:
                return self._handle_quit()
            else:
                print(self._colorize("无效的选择，请重试。", self.COLOR_RED))

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

        result = {
            "action": "approve",
            "feedback": ""
        }

        self.history.append(result)
        return result

    def _handle_reject(self) -> Dict[str, Any]:
        """处理驳回操作"""
        print("\n" + self._colorize("✗ 审查驳回，请提供修复意见。", self.COLOR_YELLOW))

        while True:
            feedback = input("\n请输入反馈意见（按回车完成输入）: ").strip()

            if not feedback:
                print(self._colorize("反馈不能为空，请重新输入。", self.COLOR_RED))
                continue

            # 确认反馈
            print("\n您的反馈意见:")
            print("-" * 80)
            print(feedback)
            print("-" * 80)

            confirm = input("\n确认提交反馈? (Y/N): ").strip().upper()

            if confirm == 'Y':
                print("\n" + self._colorize("✓ 反馈已提交，将触发修复流程。", self.COLOR_GREEN))

                result = {
                    "action": "reject",
                    "feedback": feedback
                }

                self.history.append(result)
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
                return {"action": "cancel", "feedback": ""}

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

                        result = {
                            "action": "rollback",
                            "feedback": f"回退到 {selected['description']}",
                            "checkpoint_id": checkpoint_id
                        }

                        self.history.append(result)
                        return result
                    else:
                        print("已取消回退操作。")
                        return {"action": "cancel", "feedback": ""}
                else:
                    print(self._colorize("无效的编号，请重试。", self.COLOR_RED))
            except ValueError:
                print(self._colorize("请输入有效的数字。", self.COLOR_RED))

    def _handle_quit(self) -> Dict[str, Any]:
        """处理退出操作"""
        print("\n" + self._colorize("程序已退出。", self.COLOR_YELLOW))

        result = {
            "action": "quit",
            "feedback": "用户退出"
        }

        self.history.append(result)
        return result

    def get_history(self) -> List[Dict[str, Any]]:
        """获取审查历史"""
        return self.history.copy()


# ==========================================
# 测试入口
# ==========================================

if __name__ == "__main__":
    # 测试ReviewUI
    print("=== 测试ReviewUI ===\n")

    ui = ReviewUI()

    # 测试数据
    test_content = """
# 测试现状分析报告

## 一、地理位置
测试村位于XX省XX市，距县城30公里。

## 二、人口状况
全村共1200人，其中劳动力800人。

## 三、经济发展
以农业为主，主要种植水稻、小麦。

## 四、基础设施
道路硬化率80%，自来水覆盖率100%。

## 五、公共服务
有村级卫生室1个，小学1所。

## 六、生态环境
植被覆盖率60%，无工业污染。

## 七、历史文化
建村历史300年，有古建筑3处。

## 八、治理状况
村委会健全，村民自治良好。

## 九、发展约束
土地资源有限，资金短缺。

## 十、发展潜力
交通便利，适合发展乡村旅游。
""" * 5  # 重复几次以增加长度

    test_checkpoints = [
        {
            "checkpoint_id": "checkpoint_001_layer1_completed",
            "layer": 1,
            "description": "Layer 1 现状分析完成",
            "timestamp": "2024-01-01T12:00:00"
        },
        {
            "checkpoint_id": "checkpoint_002_layer2_completed",
            "layer": 2,
            "description": "Layer 2 规划思路完成",
            "timestamp": "2024-01-01T13:00:00"
        }
    ]

    result = ui.review_content(
        content=test_content,
        title="现状分析报告",
        allow_rollback=True,
        available_checkpoints=test_checkpoints
    )

    print(f"\n审查结果: {result}")
