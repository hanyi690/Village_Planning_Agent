"""Intent cache with parse-factor-aware invalidation.

Cache key includes all factors that affect parse output:
  1. Input content (planning text / L3 reports)
  2. LLM model (LLM_MODEL setting)
  3. Parse version (manual bump when prompt/logic changes)

When any factor changes, cache auto-invalidates and re-runs LLM.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Optional

from app.core.settings import PROJECT_ROOT
from app.utils.logger import get_logger

logger = get_logger(__name__)

INTENT_CACHE_DIR = PROJECT_ROOT / "output" / "intent_cache"

# Manual version bump: increment when parse prompt/logic changes
PARSE_VERSION = "v2"  # v2: 商品林(1340)→农业用地, 生态林(1350)→生态绿地 per GB/T 21010


def _compute_cache_key(source: str, content: str) -> str:
    """Cache key includes all factors affecting parse output."""
    from app.core.settings import LLM_MODEL
    version_factor = f"{PARSE_VERSION}:{LLM_MODEL}"
    content_hash = hashlib.md5(content.encode()).hexdigest()[:12]
    version_hash = hashlib.md5(version_factor.encode()).hexdigest()[:8]
    return f"{source}_{version_hash}_{content_hash}"


def get_cached_intent(cache_key: str) -> Optional[Dict[str, Any]]:
    """Load cached intent if exists."""
    path = INTENT_CACHE_DIR / f"{cache_key}.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            logger.warning(f"[IntentCache] Corrupted cache {cache_key}: {e}")
            return None
    return None


def save_cached_intent(cache_key: str, intent: Dict[str, Any]) -> None:
    """Save intent to cache file."""
    INTENT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path = INTENT_CACHE_DIR / f"{cache_key}.json"
    path.write_text(
        json.dumps(intent, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    logger.info(f"[IntentCache] Saved: {cache_key}")


def list_cached_intents() -> Dict[str, Any]:
    """List all cached intents with metadata."""
    if not INTENT_CACHE_DIR.exists():
        return {}
    result = {}
    for path in INTENT_CACHE_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            zones = data.get("zones", [])
            result[path.stem] = {
                "zone_count": len(zones),
                "facility_count": len(data.get("facilities", [])),
                "source": data.get("metadata", {}).get("source", "unknown"),
                "size_bytes": path.stat().st_size,
            }
        except Exception:
            pass
    return result


def resolve_gen_intent_cached(
    village_name: str = "金田村委会",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Gen intent with caching (planning markdown → LLM → intent)."""
    from .data_loader import resolve_gen_intent
    from .planning_text_loader import PlanningTextLoader

    try:
        text = PlanningTextLoader.load_village_planning_markdown(village_name)
        cache_key = _compute_cache_key("gen", text[:5000])
    except FileNotFoundError:
        logger.info("[IntentCache] No planning markdown, skipping cache")
        return resolve_gen_intent(village_name, gis_data)

    cached = get_cached_intent(cache_key)
    if cached:
        logger.info(f"[IntentCache] gen cache hit: {cache_key}")
        return cached

    intent = resolve_gen_intent(village_name, gis_data)
    save_cached_intent(cache_key, intent)
    return intent


def resolve_plan_intent_cached(
    village_name: str = "金田村委会",
    gis_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Plan intent with caching (L3 reports → LLM → intent)."""
    from .data_loader import resolve_plan_intent, load_l3_reports

    reports = load_l3_reports()
    if not reports:
        logger.info("[IntentCache] No L3 reports, skipping cache")
        return resolve_plan_intent(village_name, gis_data)

    report_text = json.dumps(reports, ensure_ascii=False)[:5000]
    cache_key = _compute_cache_key("plan", report_text)

    cached = get_cached_intent(cache_key)
    if cached:
        logger.info(f"[IntentCache] plan cache hit: {cache_key}")
        return cached

    intent = resolve_plan_intent(village_name, gis_data)
    save_cached_intent(cache_key, intent)
    return intent


def resolve_intent_live(
    path_name: str,
    village_name: str,
    gis_data: Dict[str, Any],
    custom_text: str = "",
) -> Dict[str, Any]:
    """Real LLM intent resolution — bypasses cache entirely.

    Args:
        path_name: "gen" (markdown planning text) or "plan" (L3 reports)
        village_name: target village
        gis_data: GIS data for constraint injection
        custom_text: optional custom planning text override
    """
    from app.tools.gis.parse import parse_text_via_llm
    from .loader import load_planning_text, load_l3_reports

    if path_name == "gen":
        planning_text = custom_text or load_planning_text(village_name)
        return parse_text_via_llm(text=planning_text, village_name=village_name, gis_data=gis_data)
    else:
        reports = load_l3_reports()
        from app.tools.gis.parse import _parse_reports_to_intent
        result = _parse_reports_to_intent(reports=reports, village_name=village_name, gis_data=gis_data)
        data = result.get("data", {})
        return data.get("intent_json", data)
