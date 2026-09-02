"""Configured source registry for the DATA layer.

This module is deliberately limited to source discovery and bounded reads.
Session products are built by :class:`DataAdmissionFacade`; this catalog does
not assemble a legacy session object, infer a village extent, or contact a
provider as a side effect of context bootstrap.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.data.ingestion.contracts import DataResult
from app.data.ingestion.sources import DataSourceDriver, DriverRegistry
from app.data.model.canonical import BBox
from app.infrastructure.logging import get_logger
from .config import CatalogConfig

logger = get_logger(__name__)
DEFAULT_CONFIG_PATH = Path(__file__).parent / "sources.yaml"


class DataCatalog:
    """Read-only registry of configured DATA source drivers.

    Admission, normalization, representation construction, and persistence
    live behind ``DataAdmissionFacade``.  The query API remains available for
    explicit route-level diagnostics and source inspection only.
    """

    def __init__(self, config_path: Optional[str] = None):
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._connections: Dict[str, Dict[str, Any]] = {}
        self._sources_cfg: Dict[str, Dict[str, Any]] = {}
        self._sources: Dict[str, DataSourceDriver] = {}
        self._load_config()
        self._init_connections()
        self._init_sources()

    def _load_config(self) -> None:
        if not self.config_path.exists():
            logger.warning("[DataCatalog] Config not found: %s", self.config_path)
            return
        with self.config_path.open("r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle) or {}
        catalog = CatalogConfig(**raw)
        self._connections = catalog.connections
        self._sources_cfg = catalog.sources
        logger.info(
            "[DataCatalog] Loaded %d sources, %d connections from %s",
            len(self._sources_cfg), len(self._connections), self.config_path,
        )

    def _init_connections(self) -> None:
        from app.data.ingestion.connections import ConnectionRegistry
        from app.data.ingestion.connections.amap import AmapConnection
        from app.data.ingestion.connections.gd_tianditu import GDTiandituConnection
        from app.data.ingestion.connections.tianditu import TiandituConnection

        classes = {
            "tianditu": TiandituConnection,
            "amap": AmapConnection,
            "gd_tianditu": GDTiandituConnection,
        }
        for name, cfg in self._connections.items():
            connection_cls = classes.get(cfg.type)
            if connection_cls is None:
                logger.warning("[DataCatalog] Unknown connection type '%s'", cfg.type)
                continue
            try:
                ConnectionRegistry.register(connection_cls())
            except Exception as exc:  # noqa: BLE001
                logger.error("[DataCatalog] Failed to init connection '%s': %s", name, exc)

    def _init_sources(self) -> None:
        from app.core.settings import PROJECT_ROOT

        for name, cfg in self._sources_cfg.items():
            if cfg.get("enabled", True) is False:
                continue
            driver_name = str(cfg.get("driver") or "")
            if not DriverRegistry.has_driver(driver_name):
                logger.warning(
                    "[DataCatalog] Driver '%s' is not registered for '%s'",
                    driver_name, name,
                )
                continue
            try:
                driver_cls = DriverRegistry.get(driver_name)
                self._sources[name] = driver_cls(
                    self._resolve_paths(cfg, PROJECT_ROOT)
                )
            except Exception as exc:  # noqa: BLE001
                logger.error("[DataCatalog] Failed to init source '%s': %s", name, exc)

    @staticmethod
    def _resolve_paths(cfg: Dict[str, Any], project_root: Path) -> Dict[str, Any]:
        resolved = dict(cfg)
        for key in ("path", "cache_dir", "local_path"):
            value = resolved.get(key)
            if value is not None:
                path = Path(str(value))
                if not path.is_absolute():
                    resolved[key] = str(project_root / path)
        return resolved

    def get_source(self, name: str) -> DataSourceDriver:
        if name not in self._sources:
            raise KeyError(f"Unknown source: {name}. Available: {list(self._sources)}")
        return self._sources[name]

    def list_sources(self) -> List[str]:
        return list(self._sources)

    def find_sources_by_layer_type(self, layer_type: str) -> List[DataSourceDriver]:
        matches: List[DataSourceDriver] = []
        for name, source in self._sources.items():
            cfg = self._sources_cfg.get(name, {})
            if cfg.get("layer_type") == layer_type:
                matches.append(source)
                continue
            if any(layer.get("layer_type") == layer_type for layer in cfg.get("layers", [])):
                matches.append(source)
        return matches

    def find_source_by_layer_type(self, layer_type: str) -> Optional[DataSourceDriver]:
        sources = self.find_sources_by_layer_type(layer_type)
        return sources[0] if sources else None

    def query_by_bbox(
        self,
        bbox: Optional[BBox],
        layer_types: List[str],
    ) -> Dict[str, DataResult]:
        """Explicitly query configured sources; no implicit fallback inference."""
        results: Dict[str, DataResult] = {}
        for layer_type in layer_types:
            sources = self.find_sources_by_layer_type(layer_type)
            if not sources:
                results[layer_type] = DataResult.fail(
                    error=f"No source configured for layer_type: {layer_type}"
                )
                continue
            last_error = ""
            for source in sources:
                try:
                    result = source.fetch(bbox=bbox, layer_type=layer_type)
                except Exception as exc:  # noqa: BLE001
                    last_error = str(exc)
                    continue
                if result.success:
                    results[layer_type] = result
                    break
                last_error = result.error or "unknown error"
            else:
                results[layer_type] = DataResult.fail(
                    error=f"All sources failed for {layer_type}: {last_error}"
                )
        return results


__all__ = ["DataCatalog"]
