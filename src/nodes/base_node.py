"""
节点基类

定义所有节点的基础接口和通用功能。
"""

from abc import ABC, abstractmethod
from typing import Dict, Any
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

    def __init__(self, node_name: str):
        """
        初始化节点

        Args:
            node_name: 节点名称（用于日志和调试）
        """
        self.node_name = node_name

    @abstractmethod
    def execute(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行节点逻辑（子类必须实现）

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        pass

    def __call__(self, state: Dict[str, Any]) -> Dict[str, Any]:
        """
        可调用接口，用于LangGraph

        这使得节点实例可以直接用作LangGraph的节点函数。

        Args:
            state: 当前状态

        Returns:
            状态更新字典
        """
        logger.info(f"[{self.node_name}] 开始执行")
        try:
            result = self.execute(state)
            logger.info(f"[{self.node_name}] 执行完成")
            return result
        except Exception as e:
            logger.error(f"[{self.node_name}] 执行失败: {e}")
            return self._build_error_response(e)

    def _build_error_response(self, error: Exception) -> Dict[str, Any]:
        """
        构建错误响应（子类可重写）

        Args:
            error: 异常对象

        Returns:
            包含错误信息的状态更新字典
        """
        return {
            "messages": [AIMessage(content=f"{self.node_name}执行失败: {error}")]
        }

    def validate_state(self, state: Dict[str, Any], required_keys: list) -> bool:
        """
        验证状态是否包含必需的键

        Args:
            state: 当前状态
            required_keys: 必需的键列表

        Returns:
            True 如果验证通过，False 否则
        """
        missing_keys = [key for key in required_keys if key not in state]
        if missing_keys:
            logger.warning(f"[{self.node_name}] 缺少必需的状态键: {missing_keys}")
            return False
        return True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name='{self.node_name}')"


__all__ = ["BaseNode"]
