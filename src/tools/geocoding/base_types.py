"""GIS Provider 统一结果类型基类"""

from dataclasses import dataclass, field
from typing import Dict, Any, Optional


@dataclass
class GeoProviderResult:
    """GIS Provider 返回结果基类"""
    success: bool
    data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


__all__ = ["GeoProviderResult"]