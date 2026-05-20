"""Unified experiment cache manager."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class ExperimentCache:
    """File-based JSON cache for experiment results.

    Key format: ``{experiment_type}_{identifier}_run{N}``
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    # ---- key helpers ----

    @staticmethod
    def key_for(exp_type: str, identifier: str, run: int = 0) -> str:
        return f"{exp_type}_{identifier}_run{run}"

    def _path(self, key: str) -> Path:
        return self.cache_dir / f"{key}.json"

    # ---- load / save ----

    def load(self, key: str) -> Optional[Dict[str, Any]]:
        path = self._path(key)
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text("utf-8"))
            logger.info("[Cache] HIT: %s", key)
            return data
        except Exception as exc:
            logger.warning("[Cache] Load failed %s: %s", key, exc)
            return None

    def save(self, key: str, data: Dict[str, Any], metadata: Dict[str, Any] | None = None) -> Path:
        path = self._path(key)
        wrapped = {
            "_meta": {
                "cache_key": key,
                "cached_at": datetime.now().isoformat(),
                **(metadata or {}),
            },
            **data,
        }
        path.write_text(json.dumps(wrapped, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("[Cache] Saved: %s (%d bytes)", key, path.stat().st_size)
        return path

    # ---- convenience ----

    def load_reports(self, exp_type: str, identifier: str, run: int = 0) -> Optional[Dict[str, str]]:
        """Load cached reports dict, returning None on miss."""
        data = self.load(self.key_for(exp_type, identifier, run))
        if data is None:
            return None
        return data.get("reports")

    def save_reports(
        self,
        exp_type: str,
        identifier: str,
        reports: Dict[str, str],
        run: int = 0,
        **extra: Any,
    ) -> Path:
        """Save reports dict with optional extra fields."""
        return self.save(
            self.key_for(exp_type, identifier, run),
            {"reports": reports, **extra},
        )

    # ---- admin ----

    def invalidate(self, key: str) -> None:
        path = self._path(key)
        if path.exists():
            path.unlink()

    def clear_all(self) -> int:
        count = 0
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
            count += 1
        return count
