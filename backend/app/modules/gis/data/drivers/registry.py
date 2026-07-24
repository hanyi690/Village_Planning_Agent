"""Driver registry — decorator-based auto-discovery.

Usage:
    @DriverRegistry.register("file_vector")
    class FileVectorDriver(DataSourceDriver): ...

    driver_cls = DriverRegistry.get("file_vector")
    driver = driver_cls(config)
"""

from __future__ import annotations

from typing import Dict, Type, Optional

from .base import DataSourceDriver


class DriverRegistry:
    """Central registry for data source drivers.

    New drivers are auto-discovered via the @register decorator.
    No manual registration required after import.
    """

    _drivers: Dict[str, Type[DataSourceDriver]] = {}

    @classmethod
    def register(cls, name: str):
        """Decorator: register a driver class by name.

        Args:
            name: Unique driver identifier.

        Example:
            @DriverRegistry.register("file_vector")
            class FileVectorDriver(DataSourceDriver):
                ...
        """

        def decorator(driver_cls: Type[DataSourceDriver]) -> Type[DataSourceDriver]:
            cls._drivers[name] = driver_cls
            return driver_cls

        return decorator

    @classmethod
    def get(cls, name: str) -> Type[DataSourceDriver]:
        """Get a driver class by name.

        Raises:
            KeyError: If driver name is not registered.
        """
        if name not in cls._drivers:
            raise KeyError(
                f"Unknown driver: {name}. "
                f"Registered: {list(cls._drivers.keys())}"
            )
        return cls._drivers[name]

    @classmethod
    def list_drivers(cls) -> Dict[str, Type[DataSourceDriver]]:
        """Return a copy of all registered drivers."""
        return dict(cls._drivers)

    @classmethod
    def has_driver(cls, name: str) -> bool:
        """Check if a driver is registered."""
        return name in cls._drivers


__all__ = ["DriverRegistry"]
