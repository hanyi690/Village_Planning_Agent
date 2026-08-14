"""Connection base class - credentials, rate limit, retries, session, health.

A Connection is the credential/endpoint layer, decoupled from read logic.
One Connection instance is shared by multiple DataSourceDriver instances
that target the same API. For example, a single TiandituConnection serves
the api_vector driver, the wmts_tile driver, and the Guangdong thematic
driver.

Design reference: QGIS QgsConnectionPool - connection reuse, rate limit,
health check, thread-safe. For HTTP APIs we use requests.Session plus a
shared RateLimiter rather than a C++ connection pool.

Connections read credentials from app.core.settings (env vars). The YAML
``connections:`` block in sources.yaml declares which connections exist;
the catalog instantiates the matching Connection subclass by ``type``.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Optional

from app.infrastructure.logging import get_logger

from .rate_limiter import RateLimiter

logger = get_logger(__name__)


class Connection(ABC):
    """External API connection - credentials, rate limit, retries, health.

    Subclasses (TiandituConnection, AmapConnection, ...) read credentials
    from settings and expose a shared rate limiter plus a requests.Session
    for HTTP connection reuse.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique connection identifier: 'tianditu' | 'amap' | 'gd_tianditu'."""
        ...

    @abstractmethod
    def is_configured(self) -> bool:
        """Whether credentials are present (no network call)."""
        ...

    @abstractmethod
    def get_session(self) -> Any:
        """Return a shared requests.Session (or equivalent client).

        Drivers use this for HTTP requests so connection pooling and
        rate limiting are centralized here.
        """
        ...

    @property
    def rate_limiter(self) -> Optional[RateLimiter]:
        """Shared rate limiter for this connection. None if unlimited."""
        return None

    @property
    def timeout(self) -> int:
        """Request timeout in seconds."""
        return 30

    @property
    def max_retries(self) -> int:
        """Max retry attempts on transient failure."""
        return 3

    def health_check(self) -> bool:
        """Lightweight reachability probe. Override per provider.

        Default returns is_configured() - subclasses should issue a
        cheap API call to verify.
        """
        return self.is_configured()


class ConnectionRegistry:
    """Registry of instantiated connections by name.

    Connections are created once (at Catalog init from YAML) and reused
    by all drivers. This mirrors QGIS stored connections.
    """

    _connections: dict[str, Connection] = {}

    @classmethod
    def register(cls, connection: Connection) -> None:
        """Register a connection instance. Last wins for duplicate names."""
        cls._connections[connection.name] = connection
        logger.info(
            "[ConnectionRegistry] Registered: %s (configured=%s)",
            connection.name,
            connection.is_configured(),
        )

    @classmethod
    def get(cls, name: str) -> Optional[Connection]:
        return cls._connections.get(name)

    @classmethod
    def require(cls, name: str) -> Connection:
        """Get a connection or raise.

        Raises:
            KeyError: if connection name is not registered.
        """
        conn = cls._connections.get(name)
        if conn is None:
            raise KeyError(
                f"Connection '{name}' not registered. "
                f"Available: {list(cls._connections.keys())}"
            )
        return conn

    @classmethod
    def list_connections(cls) -> dict[str, Connection]:
        return dict(cls._connections)

    @classmethod
    def clear(cls) -> None:
        """Clear all registered connections (for testing)."""
        cls._connections.clear()


__all__ = ["Connection", "ConnectionRegistry"]
