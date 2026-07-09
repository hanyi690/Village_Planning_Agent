"""Jintian village demo GIS data loader.

SharedGISContext falls back to this service in development/testing when no user
uploaded boundary/land-use data exists. The merge branch referenced this class
through an invalid path; this file provides the actual implementation.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class JintianTestDataService:
    """Load bundled GeoJSON files from docs/gis/jintian_boundary."""

    DATA_TYPE_TO_FILE = {
        "boundary": "boundary.geojson",
        "road": "road_current.geojson",
        "road_planned": "road_planned.geojson",
        "landuse_current": "landuse_current.geojson",
        "landuse_planned": "landuse_planned.geojson",
        "farmland_protection": "farmland_protection.geojson",
        "ecological_protection": "ecological_protection.geojson",
        "historical_protection": "historical_protection.geojson",
        "construction_zone": "construction_zone.geojson",
        "geological_hazard_points": "geological_hazard_points.geojson",
        "project_polygons": "project_polygons.geojson",
        "project_lines": "project_lines.geojson",
        "project_points": "project_points.geojson",
        "annotation_current": "annotation_current.geojson",
        "annotation_planned": "annotation_planned.geojson",
    }

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        project_root = Path(__file__).resolve().parents[3]
        self.data_dir = data_dir or project_root / "docs" / "gis" / "jintian_boundary"

    def load_geojson(self, data_type: str) -> Optional[Dict[str, Any]]:
        filename = self.DATA_TYPE_TO_FILE.get(data_type, f"{data_type}.geojson")
        path = self.data_dir / filename
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[JintianTestDataService] failed to load %s: %s", path, exc)
            return None

    def load_all_data(self) -> Dict[str, Dict[str, Any]]:
        data: Dict[str, Dict[str, Any]] = {}
        if not self.data_dir.exists():
            logger.warning("[JintianTestDataService] data dir not found: %s", self.data_dir)
            return data
        for data_type in self.DATA_TYPE_TO_FILE:
            geojson = self.load_geojson(data_type)
            if geojson:
                data[data_type] = geojson
        return data
