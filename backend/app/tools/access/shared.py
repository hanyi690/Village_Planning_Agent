"""Shared helpers for access tools — bundle resolution + token budgeting.

Access tools read session data through the snapshot-first path:
  1. in-memory cached session bundle (fastest)
  2. persisted versioned snapshot (BundleStore, deterministic/immutable)
  3. live build (DataCatalog, fallback)

All tool payloads are passed through ``budget_check`` before returning so the
LLM never receives an unbounded dump (just-in-time context engineering).
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from app.data.model.canonical import VillageBundle
from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


async def resolve_bundle(session_id: str) -> VillageBundle:
    """Return the session bundle via the snapshot-first read path."""
    if not session_id:
        return VillageBundle(village_name="")

    from app.application.sessions.session_bundle import build_session_bundle, get_cached_bundle

    cached = get_cached_bundle(session_id)
    if cached is not None:
        return cached

    try:
        from app.infrastructure.storage.bundle_store import BundleStore
        stored = await BundleStore.get_instance().load_bundle(session_id)
        if stored is not None:
            return stored
    except Exception as e:
        logger.warning("[Access] Snapshot load failed for %s: %s", session_id, e)

    try:
        return await build_session_bundle(session_id)
    except Exception as e:
        logger.error("[Access] Live bundle build failed for %s: %s", session_id, e)
        return VillageBundle(village_name="")


def session_kg(session_id: str):
    """Return the session KG, or None if no KG is registered for this session."""
    try:
        from app.infrastructure.kg.manager import KGManager

        manager = KGManager()
        return manager.get_session_kg(session_id)
    except Exception as e:
        logger.warning("[Access] KG access failed for %s: %s", session_id, e)
        return None


def budget_check(payload: Dict[str, Any], hard_limit: int = 6000) -> Dict[str, Any]:
    """Annotate a payload with its CJK-aware token estimate.

    Does not hard-truncate (tools already bound their own top_k / max_chars),
    but flags oversized payloads so callers/LLM know the view is partial.
    """
    from app.infrastructure.kg.queries.contracts import TokenBudget

    try:
        est = TokenBudget.estimate_dict(payload)
    except Exception:
        est = len(str(payload))
    payload["_token_estimate"] = est
    if est > hard_limit:
        payload["_truncated"] = True
    return payload


def tool_reply(data: Dict[str, Any]) -> str:
    """Serialize a tool payload into the standard make_result envelope."""
    from app.tools.helpers import make_result

    return json.dumps(make_result(True, data=data), ensure_ascii=False, default=str)


def _label_of(f: Any) -> str:
    """Best-effort label for a feature (dlbm, then zone_type, then layer_type)."""
    for attr in ("dlbm", "zone_type", "name", "layer_type"):
        v = getattr(f, attr, None)
        if v:
            return str(v)
    return "unknown"


def group_stats(bundle: VillageBundle) -> Dict[str, Any]:
    """Per-group feature inventory: {group: {key: {count, labels}}}."""

    def _entries(group) -> Dict[str, Any]:
        out = {}
        for key in group.keys():
            feats = group.get(key) or []
            labels: Dict[str, int] = {}
            for f in feats:
                lbl = _label_of(f)
                labels[lbl] = labels.get(lbl, 0) + 1
            out[key] = {
                "count": len(feats),
                "labels": dict(sorted(labels.items(), key=lambda x: -x[1])[:8]),
            }
        return out

    return {
        "points": _entries(bundle.points),
        "lines": _entries(bundle.lines),
        "polygons": _entries(bundle.polygons),
    }


def simplify_geometry(geom: Optional[Dict[str, Any]], factor: float) -> Optional[Dict[str, Any]]:
    """Downsample geometry coordinates by ``factor`` (0..1, 1 = keep all)."""
    if not geom or factor <= 0 or factor >= 1:
        return geom
    step = max(1, int(round(1.0 / max(factor, 0.01))))
    if step <= 1:
        return geom

    def _coords(c):
        if isinstance(c, (int, float)):
            return c
        if isinstance(c, list):
            # A list of numbers is a coordinate position; a list of lists is nested.
            if c and isinstance(c[0], (int, float)):
                return c
            return [_coords(sub) for sub in c[::step]]
        return c

    return {**geom, "coordinates": _coords(geom.get("coordinates"))}


__all__ = [
    "resolve_bundle",
    "session_kg",
    "budget_check",
    "tool_reply",
    "group_stats",
    "simplify_geometry",
]
