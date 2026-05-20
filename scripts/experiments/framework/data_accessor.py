"""Experiment data accessor — unified interface to ReportStore + file cache."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from .cache import ExperimentCache

logger = logging.getLogger(__name__)


class ExperimentDataAccessor:
    """Reads dimension reports from DB (ReportStore) or file cache.

    Provides a single entry point for both cascade and RAG experiments
    to retrieve layer reports, avoiding duplicated ReportStore calls.
    """

    def __init__(self, cache: ExperimentCache):
        self.cache = cache

    # ---- from database ----

    async def get_reports(
        self,
        session_id: str,
        layers: Optional[List[int]] = None,
        dimension_filter: Optional[List[str]] = None,
    ) -> Dict[str, str]:
        """Get reports from ReportStore, optionally cached to file.

        Returns {dimension_key: content_string}.
        """
        # Try file cache first
        cache_key = self.cache.key_for("reports", session_id)
        cached = self.cache.load(cache_key)
        if cached is not None:
            reports = cached.get("reports", {})
            if dimension_filter:
                reports = {k: v for k, v in reports.items() if k in dimension_filter}
            return reports

        # Read from DB
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        target_layers = layers or [1, 2, 3]
        reports: Dict[str, str] = {}

        for layer in target_layers:
            layer_reports = await store.get_layer_reports(session_id, layer)
            reports.update(layer_reports)

        if dimension_filter:
            reports = {k: v for k, v in reports.items() if k in dimension_filter}

        # Cache to file for future reads
        self.cache.save(cache_key, {"session_id": session_id, "reports": reports})

        logger.info("[DataAccessor] Retrieved %d reports for %s", len(reports), session_id)
        return reports

    async def get_reports_with_sources(
        self,
        session_id: str,
        layer: int,
    ) -> Dict[str, Any]:
        """Get reports with knowledge_sources metadata."""
        from app.services.report_store import ReportStore

        store = ReportStore.get_instance()
        return await store.get_layer_reports_with_sources(session_id, layer)

    # ---- from file ----

    def load_baseline_from_file(self, path: Path) -> Dict[str, str]:
        """Load baseline_reports.json (cascade experiment reuse)."""
        if not path.exists():
            logger.warning("[DataAccessor] Baseline file not found: %s", path)
            return {}
        data = json.loads(path.read_text("utf-8"))
        reports = data.get("reports", data)
        logger.info("[DataAccessor] Loaded baseline: %d dimensions", len(reports))
        return reports

    def load_layer_reports_from_file(self, path: Path) -> Dict[str, str]:
        """Load a single layer_reports.json file."""
        if not path.exists():
            return {}
        return json.loads(path.read_text("utf-8"))

    # ---- dimension layer inference ----

    @staticmethod
    def infer_layer(dim_key: str) -> int:
        """Infer which layer a dimension belongs to."""
        from app.config.loader import get_layer_dimensions

        for layer in [1, 2, 3]:
            if dim_key in get_layer_dimensions(layer):
                return layer
        return 1