"""Advisory encoding registry — explicit cross-system suggestion interface.

Wave A.1: this is an ADVISORY-ONLY suggestion engine. It maps current DLBM
codes to zone_type / planning_zone / primary_zone for reference and prompt
tables. It is NOT part of the default planning chain and is never used to
derive planning decisions from current land use.

Importers must be advisory tests, offline research scripts, or explicit
future suggestion interfaces. The LLM does not receive these tables.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Tuple

from app.modules.schema.advisory_crosswalks import (
    DLBM_TO_ZONE_TYPE,
    DLBM_TO_PLANNING_ZONE,
    DLBM_TO_PRIMARY_ZONE,
)
from app.modules.schema.encodings.code_sets import DLBM_TO_DLMC


@dataclass
class EncodingRegistry:
    """Central advisory encoding lookup, fully derived from crosswalk tables.

    Usage (offline / advisory only):
        reg = EncodingRegistry.from_center()
        zone = reg.dlbm_to_zone["0101"]  # "农业用地"
        planning = reg.dlbm_to_planning["0101"]  # "农田保护区"
    """

    dlbm_to_zone: Dict[str, str]
    dlbm_to_planning: Dict[str, str]
    dlbm_to_primary: Dict[str, str]
    dlbm_to_category_sets: Dict[str, tuple[str, ...]]
    dlbm_to_name: Dict[str, str]

    zone_types: List[str]
    planning_zones: List[str]
    primary_zones: List[str]

    zone_colors: Dict[str, str]
    ghflbm_to_vne: Dict[str, str]

    @classmethod
    def from_center(cls) -> "EncodingRegistry":
        """Build the registry reusing advisory crosswalk + same-system tables."""
        from app.modules.schema.encodings.colors import PLANNING_ZONE_COLORS
        from app.modules.schema.encodings.dicts.loader import get_center

        dlbm_to_category_sets: Dict[str, tuple[str, ...]] = {}
        try:
            center = get_center()
            for sys_name in ["appendix5", "tugui", "gbt21010"]:
                try:
                    dlbm = center.encoding(sys_name)
                    for entry in dlbm.raw.get("classes", []):
                        code = str(entry.get("code", ""))
                        cats = tuple(entry.get("categories", []))
                        if code and code not in dlbm_to_category_sets:
                            dlbm_to_category_sets[code] = cats
                except Exception:
                    pass
        except Exception:
            pass

        return cls(
            dlbm_to_zone=DLBM_TO_ZONE_TYPE,
            dlbm_to_planning=DLBM_TO_PLANNING_ZONE,
            dlbm_to_primary=DLBM_TO_PRIMARY_ZONE,
            dlbm_to_category_sets=dlbm_to_category_sets,
            dlbm_to_name=DLBM_TO_DLMC,
            zone_types=sorted(set(DLBM_TO_ZONE_TYPE.values())),
            planning_zones=sorted(set(DLBM_TO_PLANNING_ZONE.values())),
            primary_zones=sorted(set(DLBM_TO_PRIMARY_ZONE.values())),
            zone_colors=PLANNING_ZONE_COLORS or {},
            ghflbm_to_vne={},
        )

    def lookup_zone(self, dlbm: str) -> str:
        return self.dlbm_to_zone.get(dlbm, "一般农业区")

    def lookup_planning(self, dlbm: str) -> str:
        return self.dlbm_to_planning.get(dlbm, "一般农业区")

    def get_all_dlbm_codes(self) -> List[str]:
        return list(self.dlbm_to_zone.keys())

    def get_dlbms_by_zone(self, zone_type: str) -> List[str]:
        return [code for code, zt in self.dlbm_to_zone.items() if zt == zone_type]

    def get_dlbms_by_planning(self, planning_zone: str) -> List[str]:
        return [code for code, pz in self.dlbm_to_planning.items() if pz == planning_zone]

    def to_prompt_table(self) -> str:
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


_registry: EncodingRegistry | None = None


def get_encoding_registry() -> EncodingRegistry:
    """Advisory-only singleton. Not used by the default planning chain."""
    global _registry
    if _registry is None:
        _registry = EncodingRegistry.from_center()
    return _registry


__all__ = ["EncodingRegistry", "get_encoding_registry"]
