"""Session KG 预建服务 — 在 L1 分析前构建 session KG，注入基础空间认知。

设计动机（KG 应在 L1 就由预先建立）：
  - L1 各维度通过 ``retrieve_evidence``（EXPLORE 证据服务，替代已废弃的
    ``_optimize_semantics -> build_spatial_cognition``）注入 KG 证据与空间认知；
  - 若 session KG 在 L1 前未注册，``session_kg()`` 返回 None，L1 收不到
    正确认知；
  - 预建时顺带计算 ``compute_parcel_relations``（sfTouches / nearby / connected /
    parcel-road intersects / parcel-water touches），让 KG L2 真正具备拓扑关系，
    供 grounding 的 KG 拓扑优先查询消费。

幂等：session KG 已注册则直接返回，不重复构建。
非致命：任何失败仅告警，不阻断规划主流程。
"""

from __future__ import annotations

import asyncio
from threading import RLock
from typing import Any, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# The bundle/GIS preparation is async, but RDFLib graph construction is
# synchronous and mutates an in-memory store. Keep the final check-and-register
# section atomic across ASGI worker threads and TestClient lifecycle threads.
_SESSION_KG_BUILD_LOCK = RLock()
_SESSION_KG_ASYNC_LOCKS: Dict[tuple[int, str], asyncio.Lock] = {}
_SESSION_KG_ASYNC_LOCKS_GUARD = RLock()


def _session_kg_lock(session_id: str) -> asyncio.Lock:
    """Return the lock owned by the current event loop for one session.

    KG construction is synchronous at the RDF layer but begins with async
    bundle I/O.  The old RLock only protected the final registration, so two
    requests could build the same RDF graph concurrently before either one
    registered it.  The lock is intentionally per session: unrelated
    sessions may prepare their bundles concurrently, while one session has a
    single KG writer.
    """
    loop = asyncio.get_running_loop()
    key = (id(loop), session_id)
    with _SESSION_KG_ASYNC_LOCKS_GUARD:
        lock = _SESSION_KG_ASYNC_LOCKS.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _SESSION_KG_ASYNC_LOCKS[key] = lock
        return lock


async def ensure_session_kg(
    session_id: str,
    village_name: str = "",
    force: bool = False,
) -> Optional[Dict[str, Any]]:
    """幂等预建 session KG（L1 前调用）。

    Args:
        session_id: 会话 ID。
        village_name: 村庄名（为空时从 session 记录解析）。
        force: 强制重建（忽略已有 session KG）。

    Returns:
        snapshot dict（cache_hit / triple_count / version）或 None（失败）。
    """
    from app.modules.kg import get_kg_manager

    manager = get_kg_manager()
    async with _session_kg_lock(session_id):
        with _SESSION_KG_BUILD_LOCK:
            if not force and manager.get_session_kg(session_id) is not None:
                return {"cache_hit": True, "session_id": session_id}

        try:
            from app.services.session_bundle import build_session_bundle
            from app.modules.spatial_ops.geometry import compute_parcel_relations

            bundle = await build_session_bundle(session_id, village_name)
            if bundle is None or not getattr(bundle, "village_name", ""):
                logger.warning(
                    "[SessionKG] No bundle for session %s, skip pre-build", session_id
                )
                return None

            parcels = bundle.polygons.get("landuse_current") or []
            if not parcels:
                logger.error(
                    "[SessionKG] Bundle for session %s (village=%s) has NO landuse_current "
                    "parcels — refusing to register an empty KG. Uploaded GIS layers were "
                    "likely mis-typed or skipped at bundle build.",
                    session_id, getattr(bundle, "village_name", ""),
                )
                from app.services.session_bundle import invalidate_session_bundle

                invalidate_session_bundle(session_id)
                return None

            roads = bundle.lines.get("roads_current") or []
            water = bundle.polygons.get("water_bodies") or []
            relations = compute_parcel_relations(parcels, roads, water)
            logger.info(
                "[SessionKG] parcel relations for %s: %d touches, %d nearby, "
                "%d connected, %d road-intersects, %d water-touches",
                bundle.village_name,
                len(relations.touches), len(relations.nearby),
                len(relations.connected), len(relations.parcel_road_intersects),
                len(relations.parcel_water_touches),
            )

            from app.modules.kg import open_kg_session

            with _SESSION_KG_BUILD_LOCK:
                if not force and manager.get_session_kg(session_id) is not None:
                    return {"cache_hit": True, "session_id": session_id}
                snap = open_kg_session(
                    session_id=session_id,
                    village_name=bundle.village_name,
                    bundle=bundle,
                    parcel_relations=relations,
                )

            logger.info(
                "[SessionKG] Pre-built for session %s (village=%s): %d triples, "
                "cache_hit=%s, version=%d",
                session_id, bundle.village_name, snap.triple_count,
                snap.cache_hit, snap.version,
            )
            try:
                from app.services.step_report import save_step_report

                await save_step_report(
                    session_id, "KG_PREBUILD",
                    step_name="kg_prebuild",
                    outputs={
                        "triple_count": snap.triple_count,
                        "version": snap.version,
                        "cache_hit": snap.cache_hit,
                        "gazetteer_combo_entries": 0,
                    },
                    diagnostics={
                        "sfTouches": len(relations.touches),
                        "road_intersects": len(relations.parcel_road_intersects),
                        "water_touches": len(relations.parcel_water_touches),
                    },
                )
            except Exception as e:
                logger.debug("[SessionKG] step report failed: %s", e)
            return {
                "session_id": session_id,
                "cache_hit": snap.cache_hit,
                "triple_count": snap.triple_count,
                "version": snap.version,
            }
        except Exception as e:  # noqa: BLE001 — 非致命
            logger.warning("[SessionKG] Pre-build failed for %s: %s", session_id, e, exc_info=True)
            return None


__all__ = ["ensure_session_kg"]
