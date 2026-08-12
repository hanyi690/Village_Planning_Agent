"""
Session bundle orchestration - session-level VillageBundle build + cache.

Thin wrapper over DataCatalog.load_village_bundle_async(). A VillageBundle is
session-scoped: it carries the session's original input documents, spatial
data and full L1/L2/L3 reports. Built once at session start and refreshed
per layer completion.
"""

from __future__ import annotations

import asyncio
from typing import Any, Dict, Optional

from app.modules.schema.types.canonical import VillageBundle
from app.utils.logger import get_logger

logger = get_logger(__name__)

# In-process cache: session_id -> VillageBundle
_bundle_cache: Dict[str, VillageBundle] = {}
_bundle_cache_versions: Dict[str, Optional[int]] = {}
_cache_lock = asyncio.Lock()


async def _resolve_village_name(session_id: str) -> str:
    """Resolve village name from the planning session record."""
    from app.database.operations import get_planning_session_async

    session = await get_planning_session_async(session_id)
    if not session:
        return ""
    return session.get("village_name") or session.get("project_name") or ""


async def build_session_bundle(
    session_id: str,
    village_name: Optional[str] = None,
    refresh: bool = False,
) -> VillageBundle:
    """Build (and cache) the session-level VillageBundle for a session.

    Args:
        session_id: Planning session identifier.
        village_name: Optional village name override. If omitted, resolved
            from the planning session record.
        refresh: Force a rebuild even when a cached bundle exists.

    Returns:
        Session-scoped ``VillageBundle`` (input docs + spatial + reports).
    """
    if not refresh:
        cached = get_cached_bundle(session_id)
        if cached is not None:
            return cached

    async with _cache_lock:
        if not refresh:
            cached = get_cached_bundle(session_id)
            if cached is not None:
                return cached

        if not village_name:
            village_name = await _resolve_village_name(session_id)

        if not village_name:
            logger.warning(
                "[SessionBundle] No village name for session %s; returning empty bundle",
                session_id,
            )
            bundle = VillageBundle(village_name="")
        else:
            from app.data.catalog import DataCatalog

            bundle = await DataCatalog().load_village_bundle_async(
                village_name,
                session_id=session_id,
            )

        _bundle_cache[session_id] = bundle
        _bundle_cache_versions[session_id] = None
        return bundle


async def restore_session_bundle(
    session_id: str,
    version: Optional[int] = None,
) -> Optional[VillageBundle]:
    """Restore an explicit persisted bundle version into the local cache."""
    cached = get_cached_bundle(session_id)
    if cached is not None and (
        version is None or _bundle_cache_versions.get(session_id) == version
    ):
        return cached

    from app.infrastructure.storage.bundle_store import BundleStore

    bundle = await BundleStore.get_instance().load_bundle(session_id, version=version)
    if bundle is not None:
        _bundle_cache[session_id] = bundle
        _bundle_cache_versions[session_id] = version
        logger.info(
            "[SessionBundle] Restored persisted snapshot for %s version=%s",
            session_id,
            version if version is not None else "latest",
        )
    return bundle


def get_cached_bundle(session_id: str) -> Optional[VillageBundle]:
    """Return the cached session bundle, or None."""
    return _bundle_cache.get(session_id)


async def snapshot_session_bundle(
    session_id: str,
    trigger_reason: Optional[str] = None,
    version: Optional[int] = None,
) -> Optional[VillageBundle]:
    """Build (refresh) + persist a versioned bundle snapshot.

    Combines ``build_session_bundle(refresh=True)`` with ``BundleStore.save``
    so the freshly completed layer's reports are captured. This is the graph
    hook called from ``layer_completion_check`` at each layer boundary.

    Args:
        session_id: Session identifier.
        trigger_reason: Snapshot reason ("layer1" | "layer2" | "layer3" |
            "final" | "revision" | "manual").
        version: Explicit snapshot version; auto-increments when omitted.

    Returns:
        The built bundle, or None if the build/save failed (callers treat a
        failed snapshot as non-fatal).
    """
    if not session_id:
        return None

    from app.infrastructure.storage.bundle_store import BundleStore

    try:
        bundle = await build_session_bundle(session_id, refresh=True)
    except Exception as e:
        logger.error("[SessionBundle] Snapshot build failed for %s: %s", session_id, e)
        return None

    try:
        stored_version = await BundleStore.get_instance().save(
            session_id, bundle, version=version, trigger_reason=trigger_reason,
        )
        _bundle_cache_versions[session_id] = stored_version
    except Exception as e:
        logger.error("[SessionBundle] Snapshot save failed for %s: %s", session_id, e)
        return bundle

    logger.info(
        "[SessionBundle] Snapshot saved for session %s (trigger=%s)",
        session_id, trigger_reason,
    )
    return bundle


def invalidate_session_bundle(session_id: str) -> None:
    """Drop the cached bundle so the next build is a fresh snapshot."""
    if session_id in _bundle_cache:
        del _bundle_cache[session_id]
    _bundle_cache_versions.pop(session_id, None)


__all__ = [
    "build_session_bundle",
    "get_cached_bundle",
    "restore_session_bundle",
    "snapshot_session_bundle",
    "invalidate_session_bundle",
    "_resolve_village_name",
]
