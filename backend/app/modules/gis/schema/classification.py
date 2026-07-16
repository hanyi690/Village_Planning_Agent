"""Land use classification dataclass and schema — driven by DictionaryCenter.

LandUseClass and ClassificationSchema remain as convenience wrappers.
All data is loaded from dicts/dlbm.yaml via DictionaryCenter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from .dicts.loader import get_center


@dataclass
class LandUseClass:
    """Complete classification for one DLBM code."""

    code: str
    name: str
    zone_type: str
    planning_zone: str
    primary_zone: str
    category_sets: tuple[str, ...] = ()
    gb_ref: str = ""
    description: str = ""


_CLASSES: List[LandUseClass] = get_center().get("dlbm").to_land_use_classes()

ZONE_TYPES: List[str] = sorted(set(c.zone_type for c in _CLASSES))
PLANNING_ZONES: List[str] = sorted(set(c.planning_zone for c in _CLASSES))
PRIMARY_ZONES: List[str] = ["生态空间", "农业空间", "建设空间"]


@dataclass
class ClassificationSchema:
    """Immutable snapshot of complete classification, with export methods."""

    classes: List[LandUseClass] = field(default_factory=lambda: list(_CLASSES))

    def to_dlbm_zone_type(self) -> Dict[str, str]:
        return {c.code: c.zone_type for c in self.classes}

    def to_dlbm_planning_zone(self) -> Dict[str, str]:
        return {c.code: c.planning_zone for c in self.classes}

    def to_dlbm_primary_zone(self) -> Dict[str, str]:
        return {c.code: c.primary_zone for c in self.classes}

    def to_zone_type_dlbms(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for c in self.classes:
            result.setdefault(c.zone_type, []).append(c.code)
        return result

    def to_code_sets(self) -> Dict[str, Set[str]]:
        sets: Dict[str, Set[str]] = {}
        for c in self.classes:
            for tag in c.category_sets:
                sets.setdefault(tag, set()).add(c.code)
        return {
            "BASIC_FARMLAND": sets.get("BASIC_FARMLAND", set()),
            "GENERAL_AGRICULTURE": sets.get("GENERAL_AGRICULTURE", set()),
            "ECOLOGICAL": sets.get("ECOLOGICAL", set()),
            "FOREST": sets.get("FOREST", set()),
            "FORESTRY": sets.get("FORESTRY", set()),
            "GRASSLAND": sets.get("GRASSLAND", set()),
            "WATER": sets.get("WATER", set()),
            "CONSTRUCTION": sets.get("CONSTRUCTION", set()),
        }

    def to_prompt_table(self) -> str:
        seen = set()
        rows = []
        for c in self.classes:
            key = (c.code, c.name)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                f"| {c.code} | {c.name} | {c.zone_type} | {c.planning_zone} | {c.primary_zone} | {c.gb_ref} |"
            )
        header = ("| DLBM | 名称 | 功能分区(L1) | 规划分区(L2) | 三区(L3) | GB/T |\n"
                  "|------|------|-------------|-------------|---------|------|")
        return header + "\n" + "\n".join(sorted(rows))

    def to_planning_zone_zone_types(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        seen = set()
        for c in self.classes:
            if c.planning_zone not in result:
                result[c.planning_zone] = []
            if c.zone_type not in seen:
                result[c.planning_zone].append(c.zone_type)
                seen.add((c.planning_zone, c.zone_type))
        return {k: sorted(set(v)) for k, v in result.items()}

    def get_planning_zone_for_zone_type(self, zone_type: str, dlbm: str = "") -> str:
        if dlbm:
            for c in self.classes:
                if c.code == dlbm:
                    return c.planning_zone
        planning_count: Dict[str, int] = {}
        for c in self.classes:
            if c.zone_type == zone_type:
                planning_count[c.planning_zone] = planning_count.get(c.planning_zone, 0) + 1
        if planning_count:
            return max(planning_count, key=planning_count.get)
        return "一般农业区"


SCHEMA = ClassificationSchema()
