"""Land use classification dataclass and schema — driven by DictionaryCenter.

LandUseClass and ClassificationSchema remain as convenience wrappers.
Data loaded from all encoding systems: appendix5 → tugui → gbt21010.

All module-level data (_CLASSES, ZONE_TYPES, PLANNING_ZONES, SCHEMA) is
lazy-loaded via __getattr__ to avoid blocking app startup on YAML issues.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .dicts.loader import get_center


@dataclass
class LandUseClass:
    """Complete classification for one code from any encoding system."""

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
    seen: Set[str] = set()
    for name in ["appendix5", "tugui", "gbt21010"]:
        try:
            for c in center.encoding(name).to_land_use_classes():
                if c.code not in seen:
                    seen.add(c.code)
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


# 向后兼容: 模块级属性通过 __getattr__ 懒加载
# 新代码请使用 get_schema() / _get_classes()
def __getattr__(name: str):
    if name == "_CLASSES":
        return _get_classes()
    if name == "ZONE_TYPES":
        return _get_zone_types()
    if name == "PLANNING_ZONES":
        return _get_planning_zones()
    if name == "SCHEMA":
        return get_schema()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ============================================================
# EncodingRegistry — central encoding lookup (merged from encoding_registry.py)
# ============================================================


@dataclass
class EncodingRegistry:
    """Central encoding lookup, fully derived from DictionaryCenter.

    Usage:
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
        """Build the registry reusing pre-built module-level dicts from code_sets."""
        from .colors import PLANNING_ZONE_COLORS
        from .code_sets import (
            DLBM_TO_ZONE_TYPE,
            DLBM_TO_PLANNING_ZONE,
            DLBM_TO_PRIMARY_ZONE,
            DLBM_TO_DLMC,
        )

        dlbm_to_category_sets: Dict[str, tuple[str, ...]] = {}
        try:
            from .dicts.loader import get_center
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


_registry: Optional[EncodingRegistry] = None


def get_encoding_registry() -> EncodingRegistry:
    """Get the module-level EncodingRegistry singleton (lazy-loaded)."""
    global _registry
    if _registry is None:
        _registry = EncodingRegistry.from_center()
    return _registry
