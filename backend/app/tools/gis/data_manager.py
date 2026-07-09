"""Lightweight GIS data cache used by SharedGISContext.

The merged branch referenced a GISDataManager module that was not present in
this package. This implementation keeps the API expected by gis_context.py and
stores GeoJSON objects in memory, with optional file persistence under
``data/gis_cache`` when writable. It is intentionally small and dependency-free.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class CachedGISData:
    """Cached GeoJSON payload with minimal metadata."""

    village_name: str
    data_type: str
    geojson: Dict[str, Any]
    source: str = "memory"


class GISDataManager:
    """Simple process-local/file-backed GIS data manager.

    Methods match the calls used by SharedGISContext:
    - get_geojson(village_name, data_type)
    - set_geojson(village_name, data_type, geojson, source="...")
    - get_all_user_data(village_name)
    """

    _cache: Dict[str, Dict[str, CachedGISData]] = {}
    _cache_dir = Path(__file__).resolve().parents[4] / "data" / "gis_cache"

    @classmethod
    def _safe_key(cls, value: str) -> str:
        return "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in value)

    @classmethod
    def _file_path(cls, village_name: str, data_type: str) -> Path:
        village_key = cls._safe_key(village_name or "default")
        type_key = cls._safe_key(data_type or "unknown")
        return cls._cache_dir / village_key / f"{type_key}.geojson"

    @classmethod
    def set_geojson(
        cls,
        village_name: str,
        data_type: str,
        geojson: Dict[str, Any],
        source: str = "memory",
        persist: bool = True,
    ) -> CachedGISData:
        cached = CachedGISData(village_name=village_name, data_type=data_type, geojson=geojson, source=source)
        cls._cache.setdefault(village_name, {})[data_type] = cached

        if persist:
            try:
                path = cls._file_path(village_name, data_type)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(geojson, ensure_ascii=False), encoding="utf-8")
            except Exception as exc:
                logger.debug("[GISDataManager] skip persistence: %s", exc)
        return cached

    @classmethod
    def get_geojson(cls, village_name: str, data_type: str) -> Optional[Dict[str, Any]]:
        cached = cls._cache.get(village_name, {}).get(data_type)
        if cached:
            return cached.geojson

        path = cls._file_path(village_name, data_type)
        if path.exists():
            try:
                geojson = json.loads(path.read_text(encoding="utf-8"))
                cls.set_geojson(village_name, data_type, geojson, source="file", persist=False)
                return geojson
            except Exception as exc:
                logger.warning("[GISDataManager] failed reading %s: %s", path, exc)
        return None

    @classmethod
    def get_all_user_data(cls, village_name: str) -> Dict[str, CachedGISData]:
        result: Dict[str, CachedGISData] = dict(cls._cache.get(village_name, {}))
        village_dir = cls._cache_dir / cls._safe_key(village_name or "default")
        if village_dir.exists():
            for path in village_dir.glob("*.geojson"):
                data_type = path.stem
                if data_type in result:
                    continue
                try:
                    geojson = json.loads(path.read_text(encoding="utf-8"))
                    result[data_type] = cls.set_geojson(village_name, data_type, geojson, source="file", persist=False)
                except Exception as exc:
                    logger.warning("[GISDataManager] failed loading %s: %s", path, exc)
        return result

    @classmethod
    def clear(cls, village_name: Optional[str] = None) -> None:
        if village_name is None:
            cls._cache.clear()
        else:
            cls._cache.pop(village_name, None)
