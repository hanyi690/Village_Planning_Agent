"""Base node class for all graph nodes.

Defines the base interface and common functionality for all nodes.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from langchain_core.messages import AIMessage

from ..utils.logger import get_logger

logger = get_logger(__name__)


class BaseNode(ABC):
    """
    节点基类

    所有节点都应该继承此类并实现 execute() 方法。

    Example:
        >>> class MyNode(BaseNode):
        ...     def __init__(self):
        ...         super().__init__("MyNode")
        ...
        ...     def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        ...         result = do_something(state)
        ...         return {"output_key": result}
    """

    def __init__(self, node_name: str) -> None:
        """
        Initialize the node.

        Args:
            node_name: Node name (used for logging and debugging)
        """
        self.node_name = node_name

    @abstractmethod
    def execute(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Execute node logic (must be implemented by subclasses).

        Args:
            state: Current state

        Returns:
            State update dictionary
        """
        pass

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        """
        Callable interface for LangGraph.

        This allows node instances to be used directly as LangGraph node functions.

        Args:
            state: Current state

        Returns:
            State update dictionary
        """
        logger.info(f"[{self.node_name}] 开始执行")
        try:
            result = self.execute(state)
            logger.info(f"[{self.node_name}] 执行完成")
            return result
        except Exception as e:
            logger.error(f"[{self.node_name}] 执行失败: {e}")
            return self._build_error_response(e)

    def _build_error_response(self, error: Exception) -> dict[str, Any]:
        """
        Build error response (can be overridden by subclasses).

        Args:
            error: Exception object

        Returns:
            State update dictionary containing error information
        """
        return {
            "messages": [AIMessage(content=f"{self.node_name}执行失败: {error}")]
        }

    def validate_state(self, state: dict[str, Any], required_keys: list[str]) -> bool:
        """
        Validate that state contains all required keys.

        Args:
            state: Current state
            required_keys: List of required keys

        Returns:
            True if validation passes, False otherwise
        """
        missing_keys = [key for key in required_keys if key not in state]
        if missing_keys:
            logger.warning(f"[{self.node_name}] 缺少必需的状态键: {missing_keys}")
            return False
        return True

    def __repr__(self) -> str:  # pragma: no cover
        return f"{self.__class__.__name__}(name='{self.node_name}')"


__all__ = ["BaseNode"]
