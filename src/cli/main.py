"""
CLI主入口

村庄规划Agent的统一命令行入口。
"""

import sys

from .arg_parsers import parse_args
from .commands import CommandRunner
from ..agent import __version__, __architecture__


def main():
    """主函数"""
    # 解析参数
    args = parse_args()

    # 打印版本信息
    print(f"村庄规划 AI 助手 v{__version__} ({__architecture__})")
    print("="*80 + "\n")

    # 创建并执行命令
    runner = CommandRunner(args)
    runner.run()


if __name__ == "__main__":
    main()
