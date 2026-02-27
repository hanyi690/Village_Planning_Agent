"""
Unified Tool Manager - 统一的工具管理器

Centralizes tool initialization and lifecycle management.
All API endpoints should use this manager to access tools.

Note: CheckpointTool 已移除，现在统一使用 LangGraph AsyncSqliteSaver 进行检查点管理。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ToolManager:
    """
    Tool Manager - Singleton Pattern

    Manages FileManager instances with caching.
    Note: Checkpoint management is now handled by LangGraph AsyncSqliteSaver.
    """

    _instance: Optional['ToolManager'] = None
    _file_manager = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            logger.info("[ToolManager] Singleton instance created")
        return cls._instance

    def get_file_manager(self):
        """
        Get FileManager instance (singleton)

        Returns:
            FileManager instance
        """
        from src.tools.file_manager import FileManager

        if self._file_manager is None:
            self._file_manager = FileManager()
            logger.info("[ToolManager] Created new FileManager")

        return self._file_manager

    def clear_all_tools(self):
        """Clear all cached tools (useful for testing)"""
        self._file_manager = None
        logger.info("[ToolManager] Cleared all cached tools")


# Global instance for easy import
tool_manager = ToolManager()


__all__ = ["ToolManager", "tool_manager"]
