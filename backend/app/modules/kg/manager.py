"""KGManager — process-level KG caching with three-layer separation.

Architecture:
  Layer 1 (immutable): parcels, adjacency, VNE, infrastructure, GIS constraints
      - Cached by village_name + landuse_hash
      - Survives across sessions (same GIS data → same result)
      - Dominated by _add_spatial_relations (O(n²), 2-5s)

  Layer 2 (per-intent): constraints from intent/reports, indicators, zones, regulations
      - Built fresh for each PARSE output
      - Depends on planning intent, NOT cacheable

  Layer 3 (per-allocate): designated_as relations, zone assignments
      - Modified during closed-loop iterations
      - Invalidated on zone reassignment

  Query cache: SPARQL results cached with version-based invalidation
      - Version bumped when KG triples are modified
      - All cached queries invalidated on version change

Design decisions:
  - PlanningKG (RDFLib Graph) cannot be Pydantic-serialized
    → KG instances managed here, state stores references only
  - Layer 1 cache uses SHA256 of parcel composite keys as hash
  - LRU eviction (maxsize=50) prevents unbounded memory growth
  - Thread-safe singleton via __new__ + Lock
"""

from __future__ import annotations

import hashlib
from collections import OrderedDict
from dataclasses import dataclass
from threading import Lock
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class CacheKey:
    """Composite cache key for Layer 1 static subgraph."""

    village_name: str
    landuse_hash: str  # SHA256 of BSM:DLBM:SHAPE_Area for all features

    def __str__(self) -> str:
        return f"{self.village_name}:{self.landuse_hash[:16]}"


def compute_layer1_cache_key(
    village_name: str,
    parcels: Optional[List[Any]],
) -> Optional[CacheKey]:
    """Compute cache key from typed parcel list.

    Uses hash of BSM+DLBM+area_sqm for all features.
    Accepts typed CurrentLandUseParcel list (preferred) or raw GeoJSON dict (legacy).
    """
    if not parcels:
        return None

    if isinstance(parcels, dict):
        # Legacy: raw GeoJSON FeatureCollection
        features = parcels.get("features", [])
        hash_parts = []
        for ft in sorted(features, key=lambda f: str(f.get("properties", {}).get("BSM", ""))):
            props = ft.get("properties", {})
            bsm = str(props.get("BSM", "")).strip()
            dlbm = str(props.get("DLBM", "")).strip()
            area = str(props.get("SHAPE_Area", 0) or 0)
            if bsm:
                hash_parts.append(f"{bsm}:{dlbm}:{area}")
    else:
        # Typed parcel list
        hash_parts = []
        for p in parcels:
            bsm = str(getattr(p, "bsm", "")).strip()
            dlbm = str(getattr(p, "dlbm", "")).strip()
            area = str(getattr(p, "area_sqm", 0) or 0)
            if bsm:
                hash_parts.append(f"{bsm}:{dlbm}:{area}")

    if not hash_parts:
        return None

    landuse_hash = hashlib.sha256("|".join(hash_parts).encode()).hexdigest()
    return CacheKey(village_name=village_name, landuse_hash=landuse_hash)


class _LRUCache:
    """Simple LRU cache with maxsize eviction."""

    def __init__(self, maxsize: int = 50):
        self._data: OrderedDict[str, Any] = OrderedDict()
        self._maxsize = maxsize

    def get(self, key: str) -> Optional[Any]:
        if key in self._data:
            self._data.move_to_end(key)
            return self._data[key]
        return None

    def put(self, key: str, value: Any) -> None:
        if key in self._data:
            self._data.move_to_end(key)
        self._data[key] = value
        while len(self._data) > self._maxsize:
            evicted_key, _ = self._data.popitem(last=False)
            logger.debug("[KGManager] LRU evicted: %s", evicted_key)

    def __contains__(self, key: str) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)


class KGManager:
    """Process-level KG instance manager with three-layer caching.

    Usage:
        manager = get_kg_manager()
        kg = manager.get_or_build_layer1(village_name, landuse_geojson, gis_data)
        manager.register_session(session_id, kg)

    Thread safety:
        Singleton creation is thread-safe via __new__ + Lock.
        Cache operations are NOT thread-safe (GIL-dependent in CPython).
        For multi-threaded environments, add per-cache locks.
    """

    _instance: Optional["KGManager"] = None
    _lock = Lock()

    def __new__(cls) -> "KGManager":
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._layer1_cache = _LRUCache(maxsize=50)
                instance._session_kgs: Dict[str, Any] = {}
                instance._query_cache: Dict[str, Tuple[int, Any]] = {}
                instance._session_versions: Dict[str, int] = {}
                instance._cache_enabled = True
                cls._instance = instance
            return cls._instance

    # ── Layer 1 cache ──────────────────────────────────────────────

    @property
    def cache_enabled(self) -> bool:
        """Whether Layer 1 caching is enabled (can disable for debugging)."""
        return self._cache_enabled

    @cache_enabled.setter
    def cache_enabled(self, value: bool) -> None:
        self._cache_enabled = value

    def get_or_build_layer1(
        self,
        village_name: str,
        bundle: Optional[Any] = None,
        context_blocks: Optional[List[Any]] = None,
        parcel_relations: Optional[Any] = None,
        landuse_geojson: Optional[Dict[str, Any]] = None,  # legacy fallback
        gis_data: Optional[Dict[str, Any]] = None,  # legacy fallback
    ) -> Tuple[Any, bool]:
        """Get Layer 1 KG from cache or build fresh.

        Prefer bundle + context_blocks (v4.4 path).
        Falls back to landuse_geojson + gis_data (legacy path).

        Returns:
            (PlanningKG, cache_hit) tuple.
        """
        from app.modules.kg.builder import PlanningKG

        # Use typed parcels for cache key when available
        parcels = bundle.polygons.landuse_current if bundle else landuse_geojson
        cache_key = compute_layer1_cache_key(village_name, parcels)
        key_str = str(cache_key) if cache_key else ""

        # Try cache
        if self._cache_enabled and key_str and key_str in self._layer1_cache:
            cached_kg = self._layer1_cache.get(key_str)
            if cached_kg is not None:
                kg = cached_kg.clone_static_layer()
                logger.info("[KGManager] Layer 1 cache HIT: %s", key_str)
                return kg, True

        # Build fresh
        kg = PlanningKG(village_name=village_name)
        if bundle is not None and context_blocks is not None:
            kg.build_from_blocks(
                blocks=context_blocks,
                bundle=bundle,
                parcel_relations=parcel_relations,
            )
        else:
            logger.warning("[KGManager] No bundle/context_blocks provided — skipping Layer 1 build")

        # Store in cache
        if self._cache_enabled and key_str:
            self._layer1_cache.put(key_str, kg.clone_static_layer())
            logger.info("[KGManager] Layer 1 cached: %s (%d triples)", key_str, kg.get_triple_count())

        return kg, False

    # ── Session management ─────────────────────────────────────────

    def register_session(self, session_id: str, kg: Any) -> None:
        """Register a KG instance for a session."""
        self._session_kgs[session_id] = kg
        self._session_versions.setdefault(session_id, 1)
        logger.debug("[KGManager] Session registered: %s", session_id)

    def get_session_kg(self, session_id: str) -> Optional[Any]:
        """Get the KG instance for a session."""
        return self._session_kgs.get(session_id)

    def get_any_kg(self) -> Optional[Any]:
        """Return the most recently registered session KG, or a cached Layer 1 KG.

        Used by PARSE agent tool execution when no specific session_id is known.
        Returns None if no KG is available.
        """
        if self._session_kgs:
            return list(self._session_kgs.values())[-1]
        if self._layer1_cache._data:
            return list(self._layer1_cache._data.values())[-1]
        return None

    def remove_session(self, session_id: str) -> None:
        """Remove a session and its associated data."""
        self._session_kgs.pop(session_id, None)
        self._session_versions.pop(session_id, None)
        # Clean query cache entries for this session
        prefix = f"{session_id}:"
        keys_to_remove = [k for k in self._query_cache if k.startswith(prefix)]
        for k in keys_to_remove:
            del self._query_cache[k]

    # ── Query cache ────────────────────────────────────────────────

    def query_with_cache(
        self,
        session_id: str,
        kg: Any,
        template_name: str,
        **params: Any,
    ) -> List[Dict[str, Any]]:
        """Query KG with session-scoped cache and version-based invalidation.

        Args:
            session_id: Session identifier.
            kg: PlanningKG instance.
            template_name: SPARQL template name.
            **params: Template substitution parameters.

        Returns:
            List of result dicts.
        """
        from app.modules.kg.query import query_kg

        params_key = str(hash(frozenset(params.items())))
        cache_key = f"{session_id}:{template_name}:{params_key}"
        current_version = self._session_versions.get(session_id, 1)

        cached = self._query_cache.get(cache_key)
        if cached is not None and cached[0] == current_version:
            logger.debug("[KGManager] Query cache HIT: %s", template_name)
            return cached[1]

        # Execute query
        result = query_kg(kg, template_name, **params)

        # Cache with current version
        self._query_cache[cache_key] = (current_version, result)
        logger.debug(
            "[KGManager] Query cached: %s (v=%d)", template_name, current_version
        )

        return result

    def bump_version(self, session_id: str) -> int:
        """Bump KG version for session — invalidates all cached queries.

        Call this when KG triples are modified during closed-loop iterations.
        """
        new_version = self._session_versions.get(session_id, 1) + 1
        self._session_versions[session_id] = new_version
        logger.info("[KGManager] Version bump: %s -> v%d", session_id, new_version)
        return new_version

    @property
    def version(self) -> int:
        """Get current version (for testing). Returns max version across sessions."""
        if not self._session_versions:
            return 0
        return max(self._session_versions.values())

    # ── Convenience: full build with cache ──────────────────────────

    def get_or_build_kg(
        self,
        village_name: str,
        bundle: Optional[Any] = None,
        context_blocks: Optional[List[Any]] = None,
        parcel_relations: Optional[Any] = None,
        intent: Any = None,
        reports: Optional[Dict[str, Dict[str, Any]]] = None,
        session_id: str = "",
        landuse_geojson: Optional[Dict[str, Any]] = None,
        gis_data: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """Build complete KG with Layer 1 caching."""
        kg, cache_hit = self.get_or_build_layer1(
            village_name=village_name,
            bundle=bundle,
            context_blocks=context_blocks,
            parcel_relations=parcel_relations,
            landuse_geojson=landuse_geojson,
            gis_data=gis_data,
        )
        if intent is not None and hasattr(kg, "_add_structured_intent"):
            kg._add_structured_intent(intent)
        elif reports is not None:
            logger.warning("[KGManager] reports path deprecated in v4.4 — use bundle + context_blocks")
        if session_id:
            self.register_session(session_id, kg)
        return kg

    # ── Stats ──────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "layer1_cache_size": len(self._layer1_cache),
            "session_count": len(self._session_kgs),
            "query_cache_size": len(self._query_cache),
            "cache_enabled": self._cache_enabled,
        }


# ── Singleton access ───────────────────────────────────────────────


def get_kg_manager() -> KGManager:
    """Get the singleton KGManager instance."""
    return KGManager()


__all__ = ["KGManager", "CacheKey", "compute_layer1_cache_key", "get_kg_manager"]
