"""Encoding Registry — auto-derived from zone_schema/schema.py _CLASSES.

All DLBM ↔ zone_type ↔ planning_zone mappings are derived lazily from
the single source of truth (_CLASSES list). No manual lookup tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)


@dataclass
class EncodingRegistry:
    """Central encoding lookup, fully derived from zone_schema._CLASSES.

    Usage:
        reg = EncodingRegistry.from_schema()
        zone = reg.dlbm_to_zone["0101"]  # "农业用地"
        planning = reg.dlbm_to_planning["0101"]  # "农田保护区"
    """

    dlbm_to_zone: Dict[str, str]       # DLBM code → functional zone name
    dlbm_to_planning: Dict[str, str]   # DLBM code → planning zone name
    dlbm_to_primary: Dict[str, str]    # DLBM code → primary zone (三区)
    dlbm_to_category_sets: Dict[str, tuple[str, ...]]  # DLBM → category tags
    dlbm_to_name: Dict[str, str]       # DLBM code → Chinese name

    zone_types: List[str]              # Unique functional zone names
    planning_zones: List[str]          # Unique planning zone names
    primary_zones: List[str]           # Unique primary zone names

    zone_colors: Dict[str, str]        # zone_type → hex color (from colors.py)

    # GHFLBM → VNE mapping (住房和城乡建设部用地分类)
    # populated from planned/landuse.geojson empirical data or manual config
    ghflbm_to_vne: Dict[str, str]

    @classmethod
    def from_schema(cls) -> "EncodingRegistry":
        """Build the registry from zone_schema._CLASSES."""
        from app.modules.gis.zone_schema.schema import _CLASSES
        from app.modules.gis.zone_schema.colors import PLANNING_ZONE_COLORS

        dlbm_to_zone: Dict[str, str] = {}
        dlbm_to_planning: Dict[str, str] = {}
        dlbm_to_primary: Dict[str, str] = {}
        dlbm_to_category_sets: Dict[str, tuple[str, ...]] = {}
        dlbm_to_name: Dict[str, str] = {}

        for entry in _CLASSES:
            dlbm_to_zone[entry.code] = entry.zone_type
            dlbm_to_planning[entry.code] = entry.planning_zone
            dlbm_to_primary[entry.code] = entry.primary_zone
            dlbm_to_category_sets[entry.code] = entry.category_sets
            dlbm_to_name[entry.code] = entry.name

        zone_types = sorted(set(dlbm_to_zone.values()))
        planning_zones = sorted(set(dlbm_to_planning.values()))
        primary_zones = sorted(set(dlbm_to_primary.values()))

        logger.info(
            "[EncodingRegistry] Built from %d classes: %d zone_types, %d planning_zones, %d primary_zones",
            len(_CLASSES), len(zone_types), len(planning_zones), len(primary_zones),
        )

        return cls(
            dlbm_to_zone=dlbm_to_zone,
            dlbm_to_planning=dlbm_to_planning,
            dlbm_to_primary=dlbm_to_primary,
            dlbm_to_category_sets=dlbm_to_category_sets,
            dlbm_to_name=dlbm_to_name,
            zone_types=zone_types,
            planning_zones=planning_zones,
            primary_zones=primary_zones,
            zone_colors=PLANNING_ZONE_COLORS or {},
            ghflbm_to_vne={},
        )

    def lookup_zone(self, dlbm: str) -> str:
        """Resolve DLBM → functional zone, with fallback."""
        return self.dlbm_to_zone.get(dlbm, "一般农业区")

    def lookup_planning(self, dlbm: str) -> str:
        """Resolve DLBM → planning zone, with fallback."""
        return self.dlbm_to_planning.get(dlbm, "一般农业区")

    def get_all_dlbm_codes(self) -> List[str]:
        """All known DLBM codes."""
        return list(self.dlbm_to_zone.keys())

    def get_dlbms_by_zone(self, zone_type: str) -> List[str]:
        """Get all DLBM codes that map to a given functional zone."""
        return [code for code, zt in self.dlbm_to_zone.items() if zt == zone_type]

    def get_dlbms_by_planning(self, planning_zone: str) -> List[str]:
        """Get all DLBM codes that map to a given planning zone."""
        return [code for code, pz in self.dlbm_to_planning.items() if pz == planning_zone]

    def to_prompt_table(self) -> str:
        """Generate a compact markdown table for LLM prompt injection.

        Columns: DLBM | Name | Functional Zone | Planning Zone | Primary Zone
        """
        lines = ["| DLBM | 名称 | 功能分区 | 规划分区 | 三区 |"]
        lines.append("|------|------|----------|----------|------|")
        for code in sorted(self.dlbm_to_zone.keys()):
            lines.append(
                f"| {code} | {self.dlbm_to_name.get(code, '')} "
                f"| {self.dlbm_to_zone.get(code, '')} "
                f"| {self.dlbm_to_planning.get(code, '')} "
                f"| {self.dlbm_to_primary.get(code, '')} |"
            )
        return "\n".join(lines)


# Module-level singleton — lazy loaded on first access
_registry: Optional[EncodingRegistry] = None


def get_encoding_registry() -> EncodingRegistry:
    """Get the module-level EncodingRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = EncodingRegistry.from_schema()
    return _registry


__all__ = ["EncodingRegistry", "get_encoding_registry"]
