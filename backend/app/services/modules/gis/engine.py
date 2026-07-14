"""Convenience runner — chains pipeline services for non-agent use cases.

Prefer tools/gis/ pipeline tools for Agent-driven workflows.
This module exists for test suites and direct API calls.
"""

from __future__ import annotations

import json
import time as _time
from typing import Any, Callable, Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


class SpatialLayoutEngine:
    """Thin runner that chains service modules. Not the primary orchestration path.

    For Agent workflows use tools/gis/ pipeline tools directly.
    """

    def __init__(self, session_id: str = "", progress_callback: Optional[Callable] = None):
        self._session_id = session_id
        self._progress_cb = progress_callback
        self.kg = None
        self._kg_constraints: List[Dict] = []

    @classmethod
    def from_kg_data(
        cls,
        reports: Dict[str, Dict[str, Any]],
        landuse_geojson: Dict[str, Any],
        gis_data: Optional[Dict] = None,
        session_id: str = "",
    ) -> "SpatialLayoutEngine":
        engine = cls(session_id=session_id)
        engine.build_kg_from_reports(reports, landuse_geojson, gis_data)
        return engine

    def build_kg_from_reports(
        self,
        reports: Dict[str, Dict[str, Any]],
        landuse_geojson: Optional[Dict] = None,
        gis_data: Optional[Dict] = None,
    ) -> None:
        from .kg import PlanningKG
        self.kg = PlanningKG(village_name="")
        self.kg.build_from_reports(reports=reports, landuse_geojson=landuse_geojson, gis_data=gis_data)
        self._kg_constraints = self.kg.get_constraints()
        self._emit_progress(self._session_id, "kg_built", {"triple_count": self.kg.get_triple_count(), "constraint_count": len(self._kg_constraints)})

    def detect_and_resolve_conflicts(self, summaries: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
        from .conflict.detector import ConflictDetector
        from .conflict.resolver import ConflictResolver
        detector = ConflictDetector()
        report = detector.detect_all(summaries)
        resolution = None
        if report.has_conflicts:
            resolver = ConflictResolver()
            resolution = resolver.resolve(report, summaries)
        self._emit_progress(self._session_id, "conflicts_done", {"conflict_count": report.total_count, "resolved": resolution is not None})
        return {"report": report, "resolution": resolution}

    def generate_layout(
        self,
        intent: Any = None,
        landuse_geojson: Optional[Dict] = None,
        boundary_geojson: Optional[Dict] = None,
        gis_data: Optional[Dict] = None,
    ) -> List[Dict[str, Any]]:
        from .layout.zone_generator import ZoneGenerator
        from .layout.facility_placer import FacilityPlacer
        from .layout.axis_builder import AxisBuilder
        from .layout.map_renderer import MapRenderer
        from .zone_schema import dlbm_to_planning_zone

        t0 = _time.time()
        all_layers: Dict[str, Any] = {}

        zg = ZoneGenerator()
        func_zones = zg.generate(intent, landuse_geojson, boundary_geojson, gis_data)
        if func_zones:
            all_layers["function_zone"] = func_zones

        plan_zones = self._generate_planning_zones(
            landuse_geojson or {},
            intent if hasattr(intent, "__dict__") else {},
        )
        if plan_zones:
            all_layers["planning_zone"] = plan_zones

        fp = FacilityPlacer()
        facilities = fp.place(
            facilities=getattr(intent, "facilities", []) if hasattr(intent, "facilities") else [],
            landuse_geojson=landuse_geojson,
            boundary_geojson=boundary_geojson,
        )
        if facilities and facilities.get("features"):
            all_layers["facility_point"] = facilities

        ab = AxisBuilder()
        axes = ab.build(intent, boundary_geojson, landuse_geojson)
        if axes and axes.get("features"):
            all_layers["development_axis"] = axes

        mr = MapRenderer()
        configs = mr.render(all_layers, boundary_geojson)

        self._emit_progress(self._session_id, "layout_done", {"layer_count": len(configs), "elapsed_s": round(_time.time() - t0, 2)})
        return configs

    def full_pipeline(
        self,
        reports: Dict[str, Dict[str, Any]],
        landuse_geojson: Optional[Dict] = None,
        boundary_geojson: Optional[Dict] = None,
        gis_data: Optional[Dict] = None,
        summaries: Optional[Dict] = None,
        max_validation_rounds: int = 3,
    ) -> List[Dict[str, Any]]:
        self.build_kg_from_reports(reports, landuse_geojson, gis_data)
        if summaries:
            self.detect_and_resolve_conflicts(summaries)
        intent = None
        if hasattr(self, "_intent"):
            intent = self._intent
        configs = self.generate_layout(intent, landuse_geojson, boundary_geojson, gis_data)
        return configs

    def _generate_planning_zones(self, landuse: Dict, intent: Dict) -> Optional[Dict]:
        from .zone_schema import dlbm_to_planning_zone, PLANNING_ZONE_COLORS
        features = landuse.get("features", [])
        if not features:
            return None
        out = []
        for f in features:
            dlbm = str(f.get("properties", {}).get("DLBM", ""))
            pz = dlbm_to_planning_zone(dlbm)
            color = PLANNING_ZONE_COLORS.get(pz, "#CCCCCC")
            out.append({
                "type": "Feature",
                "geometry": f["geometry"],
                "properties": {**f.get("properties", {}), "assigned_zone": pz, "color": color, "stroke": color},
            })
        return {"type": "FeatureCollection", "features": out}

    def _emit_progress(self, sid: str, stage: str, data: Optional[Dict] = None) -> None:
        if self._progress_cb:
            try:
                self._progress_cb({"session_id": sid, "stage": stage, "data": data or {}})
            except Exception:
                pass


__all__ = ["SpatialLayoutEngine"]
