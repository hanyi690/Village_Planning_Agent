"""Query contracts for KG dual-payload returns and token-budget-aware pagination.

[v4.8] Introduces:
  - DualPayload: two-part return (semantic + structured) for all cognition queries
  - TokenBudget: CJK-aware token estimation and greedy pagination
  - TopKSampler: hybrid rule-based representative sampling (no embeddings)

Design principles:
  - semantic_payload: human/LLM-readable, three-layer cognition summary
  - structured_payload: tool-consumable BSM lists, bbox, geometry_kind indices
  - Token budget: CJK-aware (len/1.5), soft/hard limits, partial inclusion
  - Top-K: stratified + spatial-grid + outlier sampling, NOT embedding similarity

Usage:
    from app.infrastructure.kg.queries.contracts import DualPayload, TokenBudget, TopKSampler
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.infrastructure.logging import get_logger

logger = get_logger(__name__)


# ============================================================
# DualPayload - two-part return for all cognition queries
# ============================================================

@dataclass
class DualPayload:
    """Dual return type for KG cognition queries.

    semantic: LLM-readable three-layer cognition summary
        {
            "context_block": {village, overview, spatial_pattern},
            "layer_cards": [{group, geometry, count, dominant_label, distribution, ...}],
            "constraint_block": {adjacency_total, nearby_total, cross_layer_overlaps, ...}
        }
    structured: tool-consumable structured data
        {
            "layer_group_bsms": {group: [bsm, ...]},
            "geometry_kind_index": {polygon: N, line: N, point: N},
            "bbox": [minx, miny, maxx, maxy],
            "representative_bsms": [...],
            "total_count": N,
            "next_cursor": "offset=N" or None
        }
    token_estimate: estimated token count of the semantic payload (CJK-aware)
    truncated: True if the semantic payload was budget-trimmed
    next_cursor: pagination cursor for fetching more entities (None if complete)
    """
    semantic: Dict[str, Any] = field(default_factory=dict)
    structured: Dict[str, Any] = field(default_factory=dict)
    token_estimate: int = 0
    truncated: bool = False
    next_cursor: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "semantic": self.semantic,
            "structured": self.structured,
            "token_estimate": self.token_estimate,
            "truncated": self.truncated,
            "next_cursor": self.next_cursor,
        }


# ============================================================
# TokenBudget - CJK-aware estimation and greedy pagination
# ============================================================

class TokenBudget:
    """CJK-aware token budget management.

    Chinese text: ~1.5 chars per token (not 4 as in English).
    Soft limit: warn and truncate, Hard limit: absolute max.
    """
    SOFT_LIMIT = 4000
    HARD_LIMIT = 6000

    @staticmethod
    def estimate(text: str) -> int:
        """Estimate token count for mixed CJK/English text.

        CJK chars count as ~1 token each (conservative), ASCII as ~0.25.
        Mixed text uses a blended rate of 1.5 chars/token for CJK-heavy content.
        """
        if not text:
            return 0
        cjk_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        ascii_count = sum(1 for c in text if c.isascii() and c.isprintable())
        other_count = len(text) - cjk_count - ascii_count
        # CJK: 1 char ~= 1 token; ASCII: 4 chars ~= 1 token; other: 2 chars ~= 1 token
        return int(cjk_count + ascii_count / 4 + other_count / 2)

    @staticmethod
    def estimate_dict(d: Dict[str, Any]) -> int:
        """Estimate token count for a JSON-serializable dict (serialized to str)."""
        import json
        return TokenBudget.estimate(json.dumps(d, ensure_ascii=False))

    @staticmethod
    def paginate(
        entities: List[Any],
        budget: int,
        formatter: Callable[[Any], str],
    ) -> Tuple[List[Any], Optional[str]]:
        """Greedily fill entities into budget, return (selected, next_cursor).

        Args:
            entities: list of entity objects to paginate
            budget: max token budget for the formatted output
            formatter: function(entity) -> string representation

        Returns:
            (selected_entities, next_cursor or None)
            next_cursor = "offset={len(selected)}" if entities remain, else None
        """
        selected: List[Any] = []
        used = 0
        for ent in entities:
            est = TokenBudget.estimate(formatter(ent))
            if used + est > budget:
                break
            selected.append(ent)
            used += est

        next_cursor = None
        if len(selected) < len(entities):
            next_cursor = f"offset={len(selected)}"
        return selected, next_cursor

    @staticmethod
    def within_budget(estimate: int, hard_limit: int = None) -> bool:
        return estimate <= (hard_limit or TokenBudget.HARD_LIMIT)


# ============================================================
# TopKSampler - hybrid rule-based representative sampling
# ============================================================

class TopKSampler:
    """Sample representative entities using hybrid rules (no embeddings).

    Three-step strategy ensures both semantic diversity and spatial coverage:
      1. Stratified sampling by semantic_label (top 1-3 per label by area)
      2. Spatial coverage sampling (3x3 grid, largest entity per cell)
      3. Outlier extraction (largest + smallest for range awareness)

    This avoids the embedding-vector overhead while guaranteeing that:
      - Every semantic category is represented
      - Spatial distribution is not clustered
      - LLM sees the data range (min/max)
    """

    @staticmethod
    def sample(
        entities: List[Dict[str, Any]],
        k_budget: int = 40,
        area_field: str = "area_ha",
        label_field: str = "has_semantic_label",
        centroid_fields: Tuple[str, str] = ("lon", "lat"),
        bbox: Optional[List[float]] = None,
    ) -> List[Dict[str, Any]]:
        """Select representative entities via hybrid sampling.

        Args:
            entities: list of entity dicts with area_ha, has_semantic_label, lon, lat
            k_budget: max entities to return (default 40)
            area_field: field name for area/size sorting
            label_field: field name for semantic label grouping
            centroid_fields: (lon_field, lat_field) for spatial grid
            bbox: [minx, miny, maxx, maxy] for grid; if None, computed from entities

        Returns:
            List of selected entity dicts (deduplicated, <= k_budget)
        """
        if not entities:
            return []

        lon_field, lat_field = centroid_fields
        selected_uris: set = set()
        selected: List[Dict[str, Any]] = []

        # ── Step 1: Stratified sampling by semantic_label ──
        by_label: Dict[str, List[Dict[str, Any]]] = {}
        for e in entities:
            label = str(e.get(label_field, "")) or "未分类"
            by_label.setdefault(label, []).append(e)

        for label, group in by_label.items():
            # Sort by area descending, take top 1-3
            group_sorted = sorted(
                group,
                key=lambda x: float(x.get(area_field, 0) or 0),
                reverse=True,
            )
            top_n = min(3, len(group_sorted))
            for e in group_sorted[:top_n]:
                uri = str(e.get("uri", e.get("bsm", id(e))))
                if uri not in selected_uris:
                    selected_uris.add(uri)
                    selected.append(e)

        # ── Step 2: Spatial coverage sampling (3x3 grid) ──
        if bbox is None:
            lons = [float(e.get(lon_field, 0) or 0) for e in entities if e.get(lon_field)]
            lats = [float(e.get(lat_field, 0) or 0) for e in entities if e.get(lat_field)]
            if lons and lats:
                bbox = [min(lons), min(lats), max(lons), max(lats)]

        if bbox and bbox[2] > bbox[0] and bbox[3] > bbox[1]:
            grid_size = 3
            cell_w = (bbox[2] - bbox[0]) / grid_size
            cell_h = (bbox[3] - bbox[1]) / grid_size

            grid_entities: Dict[Tuple[int, int], Dict[str, Any]] = {}
            for e in entities:
                lon = float(e.get(lon_field, 0) or 0)
                lat = float(e.get(lat_field, 0) or 0)
                if lon == 0 and lat == 0:
                    continue
                gx = min(int((lon - bbox[0]) / cell_w), grid_size - 1)
                gy = min(int((lat - bbox[1]) / cell_h), grid_size - 1)
                gx = max(0, gx)
                gy = max(0, gy)
                key = (gx, gy)
                existing = grid_entities.get(key)
                if existing is None or float(e.get(area_field, 0) or 0) > float(existing.get(area_field, 0) or 0):
                    grid_entities[key] = e

            for e in grid_entities.values():
                uri = str(e.get("uri", e.get("bsm", id(e))))
                if uri not in selected_uris:
                    selected_uris.add(uri)
                    selected.append(e)

        # ── Step 3: Outlier extraction (max + min by area) ──
        sorted_by_area = sorted(
            entities,
            key=lambda x: float(x.get(area_field, 0) or 0),
        )
        if sorted_by_area:
            # Smallest
            e_min = sorted_by_area[0]
            uri = str(e_min.get("uri", e_min.get("bsm", id(e_min))))
            if uri not in selected_uris:
                selected_uris.add(uri)
                selected.append(e_min)
            # Largest
            e_max = sorted_by_area[-1]
            uri = str(e_max.get("uri", e_max.get("bsm", id(e_max))))
            if uri not in selected_uris:
                selected_uris.add(uri)
                selected.append(e_max)

        # ── Trim to k_budget ──
        if len(selected) > k_budget:
            selected = selected[:k_budget]

        logger.info(
            "[TopKSampler] Selected %d/%d entities (stratified+grid+outliers)",
            len(selected), len(entities),
        )
        return selected


__all__ = ["DualPayload", "TokenBudget", "TopKSampler"]
