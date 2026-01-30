"""
状态构建器 - 提供流畅的状态更新API

轻量级工具类，用于统一状态字典更新模式。
"""

from typing import Dict, Any, Generic, TypeVar
from langchain_core.messages import AIMessage, HumanMessage

T = TypeVar('T', bound=Dict[str, Any])


class StateBuilder(Generic[T]):
    """
    状态构建器 - 提供流畅的状态更新API

    用于构建状态更新字典，支持链式调用。

    Example:
        >>> builder = StateBuilder()
        >>> updates = builder.set("key1", "value1").set("key2", "value2").build()
        >>> print(updates)
        {'key1': 'value1', 'key2': 'value2'}
    """

    def __init__(self, original_state: T = None):
        """
        初始化状态构建器

        Args:
            original_state: 原始状态（可选，仅用于 build_full()）
        """
        self.original_state = original_state or {}
        self.updates: Dict[str, Any] = {}

    def set(self, key: str, value: Any) -> 'StateBuilder[T]':
        """
        设置字段

        Args:
            key: 字段名
            value: 字段值

        Returns:
            Self，支持链式调用
        """
        self.updates[key] = value
        return self

    def set_multiple(self, updates: Dict[str, Any]) -> 'StateBuilder[T]':
        """
        批量设置

        Args:
            updates: 字段更新字典

        Returns:
            Self，支持链式调用
        """
        self.updates.update(updates)
        return self

    def add_message(self, content: str, role: str = "ai") -> 'StateBuilder[T]':
        """
        添加消息到messages列表

        Args:
            content: 消息内容
            role: 角色 ("ai" 或 "human")

        Returns:
            Self，支持链式调用
        """
        if "messages" not in self.updates:
            self.updates["messages"] = []

        msg = AIMessage(content=content) if role == "ai" else HumanMessage(content=content)
        self.updates["messages"].append(msg)
        return self

    def append_to(self, key: str, value: Any) -> 'StateBuilder[T]':
        """
        追加值到列表字段

        Args:
            key: 字段名（必须是列表）
            value: 要追加的值

        Returns:
            Self，支持链式调用
        """
        if key not in self.updates:
            self.updates[key] = []
        elif not isinstance(self.updates[key], list):
            self.updates[key] = [self.updates[key]]

        self.updates[key].append(value)
        return self

    def merge(self, other_updates: Dict[str, Any]) -> 'StateBuilder[T]':
        """
        合并另一个状态更新字典

        Args:
            other_updates: 另一个状态更新字典

        Returns:
            Self，支持链式调用
        """
        self.updates = {**self.updates, **other_updates}
        return self

    def build(self) -> Dict[str, Any]:
        """
        构建状态更新（仅包含变更）

        Returns:
            仅包含变更的字典
        """
        return self.updates

    def build_full(self) -> Dict[str, Any]:
        """
        构建完整状态（原始+更新）

        Returns:
            原始状态与更新合并后的完整字典
        """
        return {**self.original_state, **self.updates}

    def has_updates(self) -> bool:
        """
        检查是否有待应用的更新

        Returns:
            True 如果有更新，False 否则
        """
        return len(self.updates) > 0

    def clear(self) -> 'StateBuilder[T]':
        """
        清空所有更新

        Returns:
            Self，支持链式调用
        """
        self.updates.clear()
        return self

    def __repr__(self) -> str:
        return f"StateBuilder(updates={self.updates})"


__all__ = ["StateBuilder"]
