"""Connection layer - API credential, rate limit, and session management.

Phase 2: concrete connections for tianditu / amap / gd_tianditu,
plus the shared RateLimiter. Drivers (Phase 3) obtain connections via
ConnectionRegistry.require(name).
"""

from __future__ import annotations

from .amap import AmapConnection
from .base import Connection, ConnectionRegistry
from .gd_tianditu import GDTiandituConnection
from .rate_limiter import RateLimiter
from .tianditu import TiandituConnection

__all__ = [
    "Connection",
    "ConnectionRegistry",
    "RateLimiter",
    "TiandituConnection",
    "AmapConnection",
    "GDTiandituConnection",
]
