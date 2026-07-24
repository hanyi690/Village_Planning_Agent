"""GIS data catalog — unified entry point for all data sources.

Loads YAML configuration, initializes drivers via DriverRegistry,
and provides query methods for spatial data retrieval.

Usage:
    from app.modules.gis.data.catalog import DataCatalog

    catalog = DataCatalog()
    result = catalog.get_source("gd_three_zones").fetch(
        bbox=BBox(west=115.5, south=24.0, east=116.5, north=25.0),
        layer_type="farmland_protection"
    )
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from app.modules.gis.schema.canonical import BBox
from app.utils.logger import get_logger

from ..drivers.base import DataSourceDriver, DataSourceResult
from ..drivers.registry import DriverRegistry
from .config import CatalogConfig

logger = get_logger(__name__)

# Default config path relative to this module
DEFAULT_CONFIG_PATH = Path(__file__).parent / "sources.yaml"


class DataCatalog:
    """GIS data catalog — manages all configured data sources.

    Lifecycle:
        1. Load YAML configuration
        2. Instantiate drivers via DriverRegistry
        3. Query sources by name or layer_type
    """

    def __init__(self, config_path: Optional[str] = None):
        """Initialize catalog from YAML configuration.

        Args:
            config_path: Path to sources.yaml. Defaults to catalog/sources.yaml.
        """
        self.config_path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
        self._config: Dict[str, Any] = {}
        self._sources: Dict[str, DataSourceDriver] = {}
        self._load_config()
        self._init_sources()

    def _load_config(self) -> None:
        """Load and validate YAML configuration."""
        if not self.config_path.exists():
            logger.warning(
                "[DataCatalog] Config not found: %s. Using empty catalog.",
                self.config_path,
            )
            self._config = {"version": "1.0", "sources": {}}
            return

        with open(self.config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        # Validate with Pydantic
        try:
            catalog = CatalogConfig(**raw)
            self._config = catalog.sources
            logger.info(
                "[DataCatalog] Loaded %d sources from %s",
                len(self._config),
                self.config_path,
            )
        except Exception as e:
            logger.error("[DataCatalog] Config validation failed: %s", e)
            raise

    def _init_sources(self) -> None:
        """Initialize all data source drivers from config."""
        from app.core.settings import PROJECT_ROOT

        for name, cfg in self._config.items():
            driver_name = cfg.get("driver", "")
            if not DriverRegistry.has_driver(driver_name):
                logger.warning(
                    "[DataCatalog] Driver '%s' not registered for source '%s'. "
                    "Skipping.",
                    driver_name,
                    name,
                )
                continue

            try:
                driver_cls = DriverRegistry.get(driver_name)
                # Resolve relative paths against project root
                resolved_cfg = dict(cfg)
                for key in ("path", "cache_dir", "local_path"):
                    if key in resolved_cfg:
                        p = Path(resolved_cfg[key])
                        if not p.is_absolute():
                            resolved_cfg[key] = str(PROJECT_ROOT / p)
                self._sources[name] = driver_cls(resolved_cfg)
                logger.info(
                    "[DataCatalog] Initialized source: %s (driver=%s)",
                    name,
                    driver_name,
                )
            except Exception as e:
                logger.error(
                    "[DataCatalog] Failed to init source '%s': %s",
                    name,
                    e,
                )

    def get_source(self, name: str) -> DataSourceDriver:
        """Get a data source by name.

        Args:
            name: Source identifier from sources.yaml.

        Returns:
            DataSourceDriver instance.

        Raises:
            KeyError: If source name is not found.
        """
        if name not in self._sources:
            available = list(self._sources.keys())
            raise KeyError(
                f"Unknown source: {name}. Available: {available}"
            )
        return self._sources[name]

    def list_sources(self) -> List[str]:
        """Return all initialized source names."""
        return list(self._sources.keys())

    def query_by_bbox(
        self,
        bbox: BBox,
        layer_types: List[str],
    ) -> Dict[str, DataSourceResult]:
        """Query multiple layer types by bounding box.

        Args:
            bbox: Spatial bounding box.
            layer_types: List of semantic layer types to fetch.

        Returns:
            Dict mapping layer_type to DataSourceResult.
        """
        results: Dict[str, DataSourceResult] = {}
        for lt in layer_types:
            source = self._find_source_by_layer_type(lt)
            if source is None:
                results[lt] = DataSourceResult.fail(
                    error=f"No source configured for layer_type: {lt}"
                )
                continue
            try:
                results[lt] = source.fetch(bbox=bbox, layer_type=lt)
            except Exception as e:
                logger.error("[DataCatalog] Query failed for %s: %s", lt, e)
                results[lt] = DataSourceResult.fail(error=str(e))
        return results

    def _find_source_by_layer_type(
        self, layer_type: str
    ) -> Optional[DataSourceDriver]:
        """Find the first source that supports a given layer_type."""
        for name, source in self._sources.items():
            cfg = self._config.get(name, {})
            # Direct match
            if cfg.get("layer_type") == layer_type:
                return source
            # Check nested layers
            layers = cfg.get("layers", [])
            for layer in layers:
                if layer.get("layer_type") == layer_type:
                    return source
        return None

    def load_village_data(
        self,
        village_name: str,
        bbox: BBox,
        layer_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Load all relevant data for a village.

        This is the primary high-level entry point for pipeline scripts.

        Args:
            village_name: Village name for metadata.
            bbox: Village bounding box.
            layer_types: Specific layer types to load. If None, loads all
                configured sources that support bbox queries.

        Returns:
            Dict mapping gis_data keys to DataSourceResult data.
        """
        if layer_types is None:
            # Auto-discover all layer types from config
            layer_types = []
            for name, cfg in self._config.items():
                if cfg.get("layer_type"):
                    layer_types.append(cfg["layer_type"])
                for layer in cfg.get("layers", []):
                    lt = layer.get("layer_type")
                    if lt and lt not in layer_types:
                        layer_types.append(lt)

        results = self.query_by_bbox(bbox, layer_types)

        # Build gis_data-compatible dict
        gis_data: Dict[str, Any] = {}
        for lt, result in results.items():
            if result.success and result.data_type == "geojson":
                # Map layer_type to gis_data key
                key = f"{lt}_geojson"
                gis_data[key] = result.data
            elif not result.success:
                logger.warning(
                    "[DataCatalog] Failed to load %s: %s",
                    lt,
                    result.error,
                )

        gis_data["_metadata"] = {
            "village_name": village_name,
            "bbox": bbox.as_tuple,
            "sources_loaded": list(gis_data.keys()),
        }

        return gis_data


__all__ = ["DataCatalog"]
