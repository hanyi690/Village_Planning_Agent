"""高德地图 API 返回结果类型"""
from dataclasses import dataclass
from typing import Dict, Any, Optional


@dataclass
class AmapResult:
    """高德地图 API 返回结果"""
    success: bool
    data: Dict[str, Any]
    metadata: Dict[str, Any]
    error: Optional[str] = None


__all__ = ["AmapResult"]