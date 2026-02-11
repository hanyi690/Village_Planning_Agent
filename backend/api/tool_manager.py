"""
Unified Tool Manager - 统一的工具管理器

Centralizes tool initialization and lifecycle management.
All API endpoints should use this manager to access tools.
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)


class ToolManager:
    """
    Tool Manager - Singleton Pattern

    Manages CheckpointTool and FileManager instances with caching.
    """

    _instance: Optional['ToolManager'] = None
    _checkpoint_tools = {}  # project_name -> CheckpointTool
    _file_manager = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            logger.info("[ToolManager] Singleton instance created")
        return cls._instance

    def get_checkpoint_tool(self, project_name: str):
        """
        Get CheckpointTool instance (with caching)

        Args:
            project_name: Project/village name

        Returns:
            CheckpointTool instance
        """
        from src.tools.checkpoint_tool import CheckpointTool

        if project_name not in self._checkpoint_tools:
            self._checkpoint_tools[project_name] = CheckpointTool(project_name)
            logger.debug(f"[ToolManager] Created new CheckpointTool for {project_name}")
        else:
            logger.debug(f"[ToolManager] Reusing CheckpointTool for {project_name}")

        return self._checkpoint_tools[project_name]

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

    def clear_project_tools(self, project_name: str):
        """
        Clear cached tools for a specific project

        Args:
            project_name: Project name to clear
        """
        if project_name in self._checkpoint_tools:
            del self._checkpoint_tools[project_name]
            logger.info(f"[ToolManager] Cleared tools for {project_name}")

    def clear_all_tools(self):
        """Clear all cached tools (useful for testing)"""
        self._checkpoint_tools.clear()
        self._file_manager = None
        logger.info("[ToolManager] Cleared all cached tools")


# Global instance for easy import
tool_manager = ToolManager()


__all__ = ["ToolManager", "tool_manager"]
