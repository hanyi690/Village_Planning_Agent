"""
统一路径管理模块

提供项目路径的统一管理，确保无论从哪个目录运行，
都能正确找到项目根目录和相关资源目录。
"""

from __future__ import annotations

from pathlib import Path
import sys


def get_project_root() -> Path:
    """
    获取项目根目录的绝对路径

    通过查找标志性文件（如pyproject.toml、README.md等）来确定项目根目录。
    如果找不到，则从当前文件向上追溯。

    Returns:
        Path: 项目根目录的绝对路径
    """
    # 从当前文件开始向上查找
    current_file = Path(__file__).resolve()
    current_dir = current_file.parent

    # 向上查找，直到找到项目根目录的标志
    # 项目根目录应该包含: src/, backend/, frontend/, pyproject.toml等
    for parent in [current_dir] + list(current_dir.parents):
        # 检查是否是项目根目录
        indicators = [
            parent / "pyproject.toml",
            parent / "src",
            parent / "backend",
        ]

        if any(p.exists() for p in indicators):
            return parent

    # 如果找不到，使用相对路径作为fallback
    # 从 src/utils/paths.py 向上两级到达项目根目录
    fallback_root = current_file.parent.parent.parent
    return fallback_root


def get_results_dir() -> Path:
    """
    获取results目录的绝对路径

    Returns:
        Path: results目录路径，如果不存在则创建
    """
    project_root = get_project_root()
    results_dir = project_root / "results"

    # 如果不存在，创建它
    results_dir.mkdir(exist_ok=True)

    return results_dir


def get_data_dir() -> Path:
    """
    获取data目录的绝对路径

    Returns:
        Path: data目录路径
    """
    project_root = get_project_root()
    return project_root / "data"


def get_backend_dir() -> Path:
    """
    获取backend目录的绝对路径

    Returns:
        Path: backend目录路径
    """
    project_root = get_project_root()
    return project_root / "backend"


def get_frontend_dir() -> Path:
    """
    获取frontend目录的绝对路径

    Returns:
        Path: frontend目录路径
    """
    project_root = get_project_root()
    return project_root / "frontend"


def ensure_working_directory() -> None:
    """
    确保当前工作目录在项目根目录

    用于应用启动时调用，确保相对路径正确工作。
    """
    import os
    project_root = get_project_root()
    os.chdir(project_root)


# 添加项目根目录到Python路径（用于导入）
def add_project_to_path() -> None:
    """
    将项目根目录添加到sys.path，确保可以正确导入项目模块
    """
    project_root = str(get_project_root())
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


__all__ = [
    "get_project_root",
    "get_results_dir",
    "get_data_dir",
    "get_backend_dir",
    "get_frontend_dir",
    "ensure_working_directory",
    "add_project_to_path",
]
