"""
SQLite CheckpointSaver for LangGraph
LangGraph 的 SQLite 检查点保存器

Implements LangGraph's Checkpoint protocol using SQLite as backend.
"""

import json
import msgpack
import threading
from datetime import datetime
from typing import Any, Dict, Generator, Iterator, Optional, Set, Tuple

from langchain_core.messages import BaseMessage
from langgraph.checkpoint import BaseCheckpointSaver, Checkpoint
from langgraph.checkpoint.serializer import SerializerProtocol

from ..utils.logger import get_logger

logger = get_logger(__name__)

# 定义运行时专用的key（不应持久化到checkpoint）
RUNTIME_ONLY_KEYS: Set[str] = {
    "messages",           # 由LangGraph单独处理
    "checkpoint_manager", # 检查点管理器
    "_streaming_queue",   # 流式队列管理器（包含线程锁等）
    "_storage_pipeline",  # 异步存储管道
    "_dimension_events",  # 维度事件列表
}


class SQLiteCheckpointSaver(BaseCheckpointSaver):
    """
    SQLite-based checkpoint saver for LangGraph

    Stores LangGraph checkpoints in SQLite database for persistence
    across server restarts.
    """

    def __init__(self, db_path: Optional[str] = None):
        """
        Initialize SQLite checkpoint saver

        Args:
            db_path: Path to SQLite database file (optional)
        """
        self.db_path = db_path
        logger.info(f"SQLiteCheckpointSaver initialized")

    def get(self, config: Dict[str, Any]) -> Optional[Checkpoint]:
        """
        Get checkpoint by config

        Args:
            config: Configuration dict with thread_id

        Returns:
            Checkpoint if found, None otherwise
        """
        try:
            thread_id = config.get("configurable", {}).get("thread_id")
            if not thread_id:
                return None

            # Query database for checkpoint
            from backend.database import get_planning_session

            session_data = get_planning_session(thread_id)
            if not session_data:
                return None

            # Extract state snapshot
            state_snapshot = session_data.get("state_snapshot")
            if not state_snapshot:
                return None

            # Convert to LangGraph checkpoint format
            checkpoint = self._state_to_checkpoint(state_snapshot)

            return checkpoint

        except Exception as e:
            logger.error(f"Failed to get checkpoint: {e}", exc_info=True)
            return None

    def put(
        self,
        config: Dict[str, Any],
        checkpoint: Checkpoint,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]
    {
        """
        Save checkpoint

        Args:
            config: Configuration dict with thread_id
            checkpoint: Checkpoint to save
            metadata: Optional metadata

        Returns:
            Configuration dict
        """
        try:
            thread_id = config.get("configurable", {}).get("thread_id")
            if not thread_id:
                return config

            # Convert checkpoint to state dict
            state = self._checkpoint_to_state(checkpoint)

            # Update database
            from backend.database import update_session_state

            update_session_state(thread_id, state)

            logger.debug(f"Saved checkpoint for thread: {thread_id}")
            return config

        except Exception as e:
            logger.error(f"Failed to save checkpoint: {e}", exc_info=True)
            return config

    def list(
        self,
        config: Dict[str, Any],
        limit: int = 10,
        before: Optional[Dict[str, Any]] = None
    ) -> Iterator[Checkpoint]:
        """
        List checkpoints for a thread

        Args:
            config: Configuration dict
            limit: Max number of checkpoints
            before: Optional filter

        Yields:
            Checkpoints
        """
        try:
            thread_id = config.get("configurable", {}).get("thread_id")
            if not thread_id:
                return

            # Query checkpoints from database
            from backend.database import list_checkpoints

            checkpoints = list_checkpoints(session_id=thread_id)

            for cp_data in checkpoints[:limit]:
                state = cp_data.get("state")
                if state:
                    checkpoint = self._state_to_checkpoint(state)
                    yield checkpoint

        except Exception as e:
            logger.error(f"Failed to list checkpoints: {e}", exc_info=True)

    def _is_serializable(self, value: Any) -> bool:
        """
        Check if value can be serialized by msgpack

        Args:
            value: Value to check

        Returns:
            True if serializable, False otherwise
        """
        if isinstance(value, (str, int, float, bool, type(None), list, dict)):
            return True
        # 检查嵌套字典和列表
        if isinstance(value, dict):
            return all(self._is_serializable(v) for v in value.values())
        if isinstance(value, list):
            return all(self._is_serializable(v) for v in value)
        # 排除不可序列化的类型
        if isinstance(value, (threading.Lock, threading.Thread)):
            return False
        # 其他类型尝试序列化测试
        try:
            msgpack.packb(value)
            return True
        except (msgpack.PackException, TypeError):
            return False

    def _state_to_checkpoint(self, state: Dict[str, Any]) -> Checkpoint:
        """
        Convert state dict to LangGraph checkpoint format

        Args:
            state: State dictionary

        Returns:
            Checkpoint tuple
        """
        # Extract relevant fields for checkpoint
        checkpoint_data = {
            "v": "1",  # Version
            "channel_values": {},
            "channel_versions": {},
            "versions_seen": {},
        }

        # Add state fields (excluding runtime-only keys)
        for key, value in state.items():
            # 跳过运行时专用的key
            if key in RUNTIME_ONLY_KEYS:
                continue

            # 类型检查：记录警告而非崩溃
            if not self._is_serializable(value):
                logger.warning(
                    f"[Checkpoint] 跳过不可序列化的字段 '{key}': "
                    f"类型={type(value).__name__}, "
                    f"这可能导致数据丢失，请考虑将其加入 RUNTIME_ONLY_KEYS"
                )
                continue

            checkpoint_data["channel_values"][key] = value

        # Handle messages separately (LangGraph will serialize them)
        if "messages" in state:
            checkpoint_data["channel_values"]["messages"] = state["messages"]

        return (checkpoint_data, {})

    def _checkpoint_to_state(self, checkpoint: Checkpoint) -> Dict[str, Any]:
        """
        Convert LangGraph checkpoint to state dict

        Args:
            checkpoint: Checkpoint tuple

        Returns:
            State dictionary
        """
        checkpoint_data, config = checkpoint

        # Extract channel values
        state = {}

        for key, value in checkpoint_data.get("channel_values", {}).items():
            state[key] = value

        # 恢复运行时对象的默认值（因为它们没有被序列化到checkpoint）
        # 这是防御性编程——确保即使运行时对象因为某种原因被保存了，也能正确恢复
        runtime_defaults = {
            "_streaming_queue": None,
            "_storage_pipeline": None,
            "_dimension_events": []
        }

        for key, default_value in runtime_defaults.items():
            if key not in state:
                state[key] = default_value

        return state


__all__ = ["SQLiteCheckpointSaver"]
