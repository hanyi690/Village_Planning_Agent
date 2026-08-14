"""自然村名注册表：从 data/gis/{village_key}/villages.yaml 动态加载自然村闭集。

路径解析与 DataCatalog._load_village_yaml_meta 一致（相对 cwd 的 data/gis）。
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)

_CACHE: Dict[str, Tuple[str, ...]] = {}
_CACHE_LOCK = threading.Lock()

_VILLAGE_SUFFIXES = ("村委会", "村")


def _data_gis_root() -> Path:
    """Find the repository data directory without requiring a specific cwd."""
    cwd_root = Path("data/gis")
    if cwd_root.exists():
        return cwd_root.resolve()
    # village_name_registry.py lives under backend/app/modules/kg; the
    # checked-in data directory is at the repository root.
    repo_root = Path(__file__).resolve().parents[4]
    return (repo_root / "data" / "gis").resolve()


def find_village_yaml(village_key: str) -> Optional[Path]:
    """Resolve an explicit key or configured village name to its YAML.

    The caller may provide either a directory key (for example ``jintian``)
    or the administrative name stored in YAML (for example ``金田村委会``).
    We never fall back to another village when the requested one is absent.
    """
    requested = str(village_key or "").strip()
    if not requested:
        return None
    root = _data_gis_root()
    direct = root / requested / "villages.yaml"
    if direct.exists():
        return direct
    normalized = resolve_village_key(requested)
    if normalized and normalized != requested:
        direct = root / normalized / "villages.yaml"
        if direct.exists():
            return direct
    if not root.exists():
        return None
    for candidate in root.glob("*/villages.yaml"):
        try:
            data = yaml.safe_load(candidate.read_text(encoding="utf-8")) or {}
            village = data.get("village") or {}
            configured = str(village.get("name") or "").strip() if isinstance(village, dict) else ""
            if configured and (configured == requested or resolve_village_key(configured) == normalized):
                return candidate
        except Exception:
            continue
    return None


def load_village_names(village_key: str) -> Tuple[str, ...]:
    village_key = str(village_key).strip()
    if not village_key:
        return ()

    with _CACHE_LOCK:
        cached = _CACHE.get(village_key)
        if cached is not None:
            return cached

    cfg_path = find_village_yaml(village_key)
    if cfg_path is None:
        logger.warning("[VillageNameRegistry] villages.yaml not found: %s", cfg_path)
        with _CACHE_LOCK:
            _CACHE[village_key] = ()
        return ()

    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except Exception as exc:
        logger.error("[VillageNameRegistry] failed to parse %s: %s", cfg_path, exc)
        with _CACHE_LOCK:
            _CACHE[village_key] = ()
        return ()

    names = data.get("natural_villages")
    if not isinstance(names, list):
        logger.warning(
            "[VillageNameRegistry] natural_villages not a list in %s (got %r)",
            cfg_path,
            type(names).__name__,
        )
        names = []

    result = tuple(str(n).strip() for n in names if str(n).strip())

    with _CACHE_LOCK:
        _CACHE[village_key] = result

    logger.info(
        "[VillageNameRegistry] loaded %d natural villages for '%s' from %s",
        len(result),
        village_key,
        cfg_path,
    )
    return result


def load_all_village_names() -> Tuple[str, ...]:
    """Load the union of configured natural-village names without a fixed key."""
    root = _data_gis_root()
    names: list[str] = []
    if not root.exists():
        return ()
    for cfg_path in sorted(root.glob("*/villages.yaml")):
        loaded = load_village_names(cfg_path.parent.name)
        for name in loaded:
            if name not in names:
                names.append(name)
    return tuple(names)


def resolve_village_key(village_name: str) -> str:
    name = str(village_name).strip()
    for suffix in _VILLAGE_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            name = name[: -len(suffix)]
            break
    return name


def clear_cache() -> None:
    with _CACHE_LOCK:
        _CACHE.clear()


__all__ = [
    "clear_cache", "find_village_yaml", "load_all_village_names",
    "load_village_names", "resolve_village_key",
]
