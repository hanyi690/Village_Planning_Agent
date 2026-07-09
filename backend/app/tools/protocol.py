"""ToolResult — standardized tool execution result."""

from dataclasses import dataclass, field
from typing import Any, Dict, Literal, Optional


@dataclass
class ToolResult:
    """Standardized tool execution result (never raises exceptions)."""

    status: Literal["success", "partial", "error"]
    data: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def success(self) -> bool:
        return self.status == "success"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "data": self.data,
            "error": self.error,
            "metadata": self.metadata,
        }


__all__ = ["ToolResult"]
