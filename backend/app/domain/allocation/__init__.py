"""Portfolio allocation contracts and the selection adapter."""

from .model import AllocationAssignment, AllocationStatus, PortfolioDecision
from .service import build_portfolio_decision

__all__ = [
    "AllocationAssignment",
    "AllocationStatus",
    "PortfolioDecision",
    "build_portfolio_decision",
]
