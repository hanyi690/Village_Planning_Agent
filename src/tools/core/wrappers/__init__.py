"""
Wrappers Module - 工具适配层

提供 GIS 工具 Wrapper 的基础类和辅助函数。
具体的 Wrapper 定义在 gis_tool_wrappers.py 中。
"""

from .base import (
    BaseToolWrapper,
    format_success_response,
    format_error_response,
    wrap_tool_response,
)

__all__ = [
    'BaseToolWrapper',
    'format_success_response',
    'format_error_response',
    'wrap_tool_response',
]