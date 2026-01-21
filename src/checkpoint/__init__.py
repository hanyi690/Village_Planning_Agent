"""
Checkpoint模块 - 支持状态持久化和恢复

提供checkpoint功能，支持：
1. 状态保存和加载
2. JSON格式存储
3. 回退和恢复
4. 索引管理
"""

from .checkpoint_manager import CheckpointManager
from .json_storage import JsonCheckpointStorage

__all__ = ['CheckpointManager', 'JsonCheckpointStorage']
