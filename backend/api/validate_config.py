"""
Configuration validation - 验证环境配置
"""

import os
from typing import Any, Dict, List


def validate_config() -> Dict[str, Any]:
    """
    验证必要的环境变量

    Returns:
        Dict with keys:
        - valid: bool - Whether configuration is valid
        - errors: List[str] - List of error messages
        - warnings: List[str] - List of warning messages
    """
    errors = []
    warnings = []

    # Check API keys
    if not os.getenv("ZHIPUAI_API_KEY") and not os.getenv("OPENAI_API_KEY"):
        errors.append("缺少 LLM API 密钥：请设置 ZHIPUAI_API_KEY 或 OPENAI_API_KEY")

    # Check model configuration
    if not os.getenv("LLM_MODEL"):
        warnings.append("未设置 LLM_MODEL，将使用默认模型")

    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings
    }
