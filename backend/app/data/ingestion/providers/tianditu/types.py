"""Tianditu API result types."""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class TiandituResult:
    """Tianditu API result envelope."""

    success: bool
    data: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


__all__ = ["TiandituResult"]
