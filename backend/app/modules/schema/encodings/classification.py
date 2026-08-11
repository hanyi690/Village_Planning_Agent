"""Land use classification dataclass and schema — driven by DictionaryCenter.

LandUseClass and ClassificationSchema remain as convenience wrappers.
Data loaded from all encoding systems: appendix5 → tugui → gbt21010.

Module-level data is lazy-loaded via _get_classes() / get_schema() to avoid
blocking app startup on YAML issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .dicts.loader import get_center


@dataclass
class LandUseClass:
    """Complete classification for one code from any encoding system."""

    system: str
    code: str
    name: str
    zone_type: str = ""
    planning_zone: str = ""
    primary_zone: str = ""
    category_sets: tuple[str, ...] = ()
    gb_ref: str = ""
    description: str = ""


def _load_all_classes() -> List[LandUseClass]:
    """Load LandUseClass from all encoding systems."""
    center = get_center()
    classes: List[LandUseClass] = []
    seen: Set[tuple[str, str]] = set()
    for name in ["appendix5", "tugui", "gbt21010"]:
        try:
            for c in center.encoding(name).to_land_use_classes():
                key = (name, c.code)
                if key not in seen:
                    c.system = name
                    seen.add(key)
                    classes.append(c)
        except Exception:
            pass
    return classes


# Lazy caches (populated on first access via __getattr__)
_CLASSES_CACHE: Optional[List[LandUseClass]] = None
_ZONE_TYPES_CACHE: Optional[List[str]] = None
_PLANNING_ZONES_CACHE: Optional[List[str]] = None
_SCHEMA: Optional[ClassificationSchema] = None


def _get_classes() -> List[LandUseClass]:
    global _CLASSES_CACHE
    if _CLASSES_CACHE is None:
        _CLASSES_CACHE = _load_all_classes()
    return _CLASSES_CACHE


def _get_zone_types() -> List[str]:
    global _ZONE_TYPES_CACHE
    if _ZONE_TYPES_CACHE is None:
        _ZONE_TYPES_CACHE = sorted(set(c.zone_type for c in _get_classes()))
    return _ZONE_TYPES_CACHE


def _get_planning_zones() -> List[str]:
    global _PLANNING_ZONES_CACHE
    if _PLANNING_ZONES_CACHE is None:
        _PLANNING_ZONES_CACHE = sorted(set(c.planning_zone for c in _get_classes()))
    return _PLANNING_ZONES_CACHE


PRIMARY_ZONES: List[str] = ["生态空间", "农业空间", "建设空间"]


@dataclass
class ClassificationSchema:
    """Immutable snapshot of complete classification, with export methods."""

    classes: List[LandUseClass] = field(default_factory=_get_classes)

    def to_dlbm_zone_type(self) -> Dict[str, str]:
        return {
            c.code: c.zone_type
            for c in self.classes
            if c.system == "gbt21010" and c.zone_type
        }

    def to_dlbm_planning_zone(self) -> Dict[str, str]:
        return {
            c.code: c.planning_zone
            for c in self.classes
            if c.system == "gbt21010" and c.planning_zone
        }

    def to_dlbm_primary_zone(self) -> Dict[str, str]:
        return {
            c.code: c.primary_zone
            for c in self.classes
            if c.system == "gbt21010" and c.primary_zone
        }

    def to_zone_type_dlbms(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for c in self.classes:
            if c.system != "gbt21010" or not c.zone_type:
                continue
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
            key = (c.system, c.code, c.name)
            if key in seen:
                continue
            seen.add(key)
            rows.append(
                f"| {c.system} | {c.code} | {c.name} | {c.zone_type} | {c.planning_zone} | {c.primary_zone} | {c.gb_ref} |"
            )
        header = ("| 体系 | Code | 名称 | 功能分区(L1) | 规划分区(L2) | 三区(L3) | GB/T |\n"
                  "|------|------|------|-------------|-------------|---------|------|")
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
                if c.system == "gbt21010" and c.code == dlbm:
                    return c.planning_zone
        planning_count: Dict[str, int] = {}
        for c in self.classes:
            if c.system != "gbt21010":
                continue
            if c.zone_type == zone_type:
                planning_count[c.planning_zone] = planning_count.get(c.planning_zone, 0) + 1
        if planning_count:
            return max(planning_count, key=planning_count.get)
        return ""


_SCHEMA: Optional[ClassificationSchema] = None


def get_schema() -> ClassificationSchema:
    """获取 ClassificationSchema 单例 (懒加载).

    首次调用时从 DictionaryCenter 构建, 后续调用返回缓存实例.
    延迟加载避免模块导入时因 YAML 数据问题导致整个应用启动失败.
    """
    global _SCHEMA
    if _SCHEMA is None:
        _SCHEMA = ClassificationSchema()
    return _SCHEMA


# ============================================================
# EncodingRegistry - advisory-only cross-system suggestion interface.
# Wave A.1: moved to app.modules.schema.advisory_crosswalks.registry.
# The default chain / schema layer does NOT import advisory crosswalks.
# Advisory consumers import directly from
# app.modules.schema.advisory_crosswalks.registry.
# ============================================================
