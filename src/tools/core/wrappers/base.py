"""
Base Wrapper - 工具 Wrapper 基类

提供统一的工具适配模式，减少重复代码。
"""

from typing import Dict, Any, List, Optional, Callable
import json


class BaseToolWrapper:
    """
    工具 Wrapper 基类

    统一的工具适配模式：
    - 参数提取
    - 函数调用
    - 结果格式化

    子类只需实现 _get_params() 和 _extract_result_fields()
    """

    def __init__(
        self,
        core_function: Callable,
        param_mapping: Optional[Dict[str, str]] = None,
        success_fields: Optional[List[str]] = None
    ):
        """
        Args:
            core_function: 核心工具函数
            param_mapping: 参数映射 (context_key -> function_param)
            success_fields: 成功时提取的字段列表
        """
        self.core_function = core_function
        self.param_mapping = param_mapping or {}
        self.success_fields = success_fields or []

    def _get_params(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """从 context 提取参数"""
        params = {}
        for context_key, func_param in self.param_mapping.items():
            value = context.get(context_key)
            if value is not None:
                params[func_param] = value
        return params

    def _extract_result_fields(self, result: Dict[str, Any]) -> Dict[str, Any]:
        """从结果提取字段"""
        data = result.get("data", {})
        return {name: data.get(name) for name in self.success_fields if data.get(name) is not None}

    def execute(self, context: Dict[str, Any]) -> str:
        """
        执行工具并返回 JSON 格式结果

        Args:
            context: ToolRegistry 执行上下文

        Returns:
            JSON 字符串响应
        """
        try:
            params = self._get_params(context)
            result = self.core_function(**params)

            if result.get("success"):
                fields = self._extract_result_fields(result)
                return json.dumps({"success": True, **fields}, ensure_ascii=False)
            else:
                return json.dumps({
                    "success": False,
                    "error": result.get("error", "Unknown error")
                }, ensure_ascii=False)

        except Exception as e:
            return json.dumps({"success": False, "error": str(e)}, ensure_ascii=False)


def format_success_response(data_fields: Dict[str, Any]) -> str:
    """格式化成功响应"""
    return json.dumps({"success": True, **data_fields}, ensure_ascii=False)


def format_error_response(error: str) -> str:
    """格式化错误响应"""
    return json.dumps({"success": False, "error": error}, ensure_ascii=False)


def wrap_tool_response(result: Dict[str, Any], success_fields: List[str]) -> str:
    """
    通用 wrapper 模式: 格式化结果为 JSON 响应

    Args:
        result: 工具执行结果字典
        success_fields: 成功时从 data 中提取的字段列表

    Returns:
        JSON 字符串响应
    """
    if result.get("success"):
        data = result.get("data", {})
        fields = {name: data.get(name) for name in success_fields if data.get(name) is not None}
        return format_success_response(fields)
    else:
        return format_error_response(result.get("error", "Unknown error"))


__all__ = [
    'BaseToolWrapper',
    'format_success_response',
    'format_error_response',
    'wrap_tool_response',
]