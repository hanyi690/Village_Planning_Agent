"""
Checkpoint工具全局管理器

避免将 CheckpointTool 实例存储在状态中，解决 msgpack 序列化问题。
"""

from __future__ import annotations

from typing import Dict, Optional
from ..tools.checkpoint_tool import CheckpointTool
from ..utils.logger import get_logger

logger = get_logger(__name__)

# 全局 CheckpointTool 实例缓存
_checkpoint_managers: Dict[str, CheckpointTool] = {}


def get_checkpoint_manager(
    project_name: str,
    timestamp: Optional[str] = None
) -> CheckpointTool:
    """获取或创建 CheckpointTool 实例"""
    key = f"{project_name}_{timestamp or 'default'}"

    if key not in _checkpoint_managers:
        logger.info(f"[CheckpointManager] 创建新的 CheckpointTool: {key}")
        _checkpoint_managers[key] = CheckpointTool(
            project_name=project_name,
            timestamp=timestamp
        )

    return _checkpoint_managers[key]


def clear_checkpoint_manager(project_name: str, timestamp: Optional[str] = None):
    """清除缓存的 CheckpointTool 实例"""
    key = f"{project_name}_{timestamp or 'default'}"
    if key in _checkpoint_managers:
        del _checkpoint_managers[key]
        logger.info(f"[CheckpointManager] 已清除: {key}")
