"""Gazetteer-based place name resolution — Tianditu geocoding + VillageGroup matching.

Two-tier fallback:
  Tier 1: 天地图 geocode(place_name) → nearest VillageGroup by Haversine
  Tier 2: Fuzzy substring match against VillageGroup names (zero API cost)

Distance threshold: 5km — loose enough for rural village names with
approximate 天地图 results, tight enough to avoid cross-village false positives.

Usage:
    resolver = PlaceNameResolver(spatial_context.residential_clusters)
    result = resolver.resolve("园寨")  # → {village_name, parcel_ids, confidence, method}
"""

from __future__ import annotations

import math
from typing import List, Optional, Tuple

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

# (name, lon, lat, parcel_ids)
VillageAnchor = Tuple[str, float, float, List[str]]

GEOCODE_DISTANCE_THRESHOLD_M = 5000  # 5 km max for geocode→village match


class PlaceNameResolver:
    """Resolve Chinese place names to GIS VillageGroup anchors + parcel IDs."""

    def __init__(self, residential_clusters: list):
        self.anchors: List[VillageAnchor] = []
        for v in residential_clusters:
            center = getattr(v, "center", None) or (0, 0)
            if center[0] != 0 and center[1] != 0:
                name = getattr(v, "name", "")
                parcel_ids = list(getattr(v, "parcel_ids", [])[:20])
                self.anchors.append((name, center[0], center[1], parcel_ids))
        self._geocoder = None
        logger.info("[gazetteer] Initialized with %d VillageGroup anchors", len(self.anchors))

    @property
    def geocoder(self):
        """Lazy-init Tianditu geocoding client."""
        if self._geocoder is None:
            from app.data.ingestion.providers.tianditu import TiandituProvider
            self._geocoder = TiandituProvider()
        return self._geocoder

    # ── Public API ──────────────────────────────────────────────────

    def resolve(self, place_name: str) -> dict:
        """Resolve a single place name to VillageGroup + parcel IDs.

        Returns:
            {name, lon, lat, village_name, parcel_ids, confidence, method}
            method: "geocode" | "fuzzy" | "unresolved"
        """
        if not place_name or not place_name.strip():
            return self._unresolved(place_name, "empty name")

        if not self.anchors:
            return self._unresolved(place_name, "no anchors")

        # Tier 1: Tianditu geocode → nearest VillageGroup
        coords = self._geocode(place_name)
        if coords:
            nearest = self._find_nearest(coords[0], coords[1])
            if nearest:
                dist = self._distance(coords, (nearest[1], nearest[2]))
                if dist < GEOCODE_DISTANCE_THRESHOLD_M:
                    return {
                        "name": place_name,
                        "lon": coords[0],
                        "lat": coords[1],
                        "village_name": nearest[0],
                        "parcel_ids": nearest[3],
                        "confidence": round(max(0.5, 0.9 - dist / 50000), 2),
                        "method": "geocode",
                    }

        # Tier 2: fuzzy substring match (zero API)
        for name, lon, lat, parcels in self.anchors:
            if self._fuzzy_match(place_name, name):
                return {
                    "name": place_name,
                    "lon": lon,
                    "lat": lat,
                    "village_name": name,
                    "parcel_ids": parcels,
                    "confidence": 0.5,
                    "method": "fuzzy",
                }

        return self._unresolved(place_name, "no match")

    def resolve_batch(self, place_names: List[str]) -> List[dict]:
        """Resolve multiple names. Geocodes one-by-one (Tianditu rate-limited)."""
        return [self.resolve(name) for name in place_names if name]

    # ── Internal helpers ────────────────────────────────────────────

    def _geocode(self, name: str) -> Optional[Tuple[float, float]]:
        """Call Tianditu geocode API. Returns (lon, lat) or None."""
        try:
            # Province prefix improves match quality in rural areas
            result = self.geocoder.geocode(f"广东省梅州市{name}")
            if result.success and result.data:
                lon = result.data.get("lon", 0)
                lat = result.data.get("lat", 0)
                if lon and lat:
                    return (float(lon), float(lat))
        except Exception as e:
            logger.debug("[gazetteer] geocode failed for '%s': %s", name, e)
        return None

    def _find_nearest(self, lon: float, lat: float) -> Optional[VillageAnchor]:
        """Find the closest VillageGroup anchor by Haversine distance."""
        best, best_dist = None, float("inf")
        for anchor in self.anchors:
            d = self._distance((lon, lat), (anchor[1], anchor[2]))
            if d < best_dist:
                best, best_dist = anchor, d
        return best

    @staticmethod
    def _distance(p1: Tuple[float, float], p2: Tuple[float, float]) -> float:
        """Haversine distance in meters."""
        R = 6371000
        lat1, lon1 = math.radians(p1[1]), math.radians(p1[0])
        lat2, lon2 = math.radians(p2[1]), math.radians(p2[0])
        dlat, dlon = lat2 - lat1, lon2 - lon1
        a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    @staticmethod
    def _fuzzy_match(place: str, village: str) -> bool:
        """Check if place name loosely matches a VillageGroup name."""
        if place in village or village in place:
            return True
        if min(len(place), len(village)) <= 3:
            return True
        # Check common prefix/suffix
        for i in range(1, min(len(place), len(village))):
            if place[:i] == village[:i] or place[-i:] == village[-i:]:
                return True
        return False

    def _unresolved(self, name: str, reason: str) -> dict:
        logger.debug("[gazetteer] unresolved '%s': %s", name, reason)
        return {
            "name": name,
            "lon": 0,
            "lat": 0,
            "village_name": "",
            "parcel_ids": [],
            "confidence": 0.1,
            "method": "unresolved",
            "error": reason,
        }
