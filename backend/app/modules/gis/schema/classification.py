"""Unified land use classification schema — single source of truth.

All DLBM classification data in one place. code_sets.py, encodings.py, prompts.py
derive their dicts/sets from this schema. To add or modify a DLBM classification,
edit only `_CLASSES` below.

Three-layer hierarchy (following GB/T 21010-2017 + 广东省村庄规划扩展):
  Layer 1: zone_type      — 8 functional zones (功能分区)
  Layer 2: planning_zone  — 6 planning zones (规划分区) → 3 primary zones (三区)
  Layer 3: primary_zone   — 生态空间 / 农业空间 / 建设空间

Design decisions (based on Exa/Context7 research):
  - ≤3 levels deep (Anthropic/Instructor best practice; 4 if counting DLBM→zone_type)
  - dataclass not Pydantic (static compile-time constants, no runtime validation needed)
  - Markdown table for LLM prompt (more compact than JSON; Washington Post validated)
  - Each entry references GB/T 21010 code via gb_ref field
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple


@dataclass
class LandUseClass:
    """Complete classification for one DLBM code. Modify here, propagate everywhere."""

    code: str              # DLBM/GHYTBM code: "1340"
    name: str              # Chinese name: "商品林"
    zone_type: str         # Layer 1 — functional zone: "农业用地"
    planning_zone: str     # Layer 2 — planning zone: "林业发展区"
    primary_zone: str      # Layer 3 — three-zone: "农业空间"
    category_sets: Tuple[str, ...] = ()  # ["GENERAL_AGRICULTURE", "FORESTRY"]
    gb_ref: str = ""       # GB/T 21010 reference code: "0301"
    description: str = ""  # Classification rationale


# ============================================================
# Complete classification data — grouped by zone_type for readability.
# Each entry covers one or more DLBM codes sharing the same classification.
# ============================================================

_CLASSES: List[LandUseClass] = [
    # ── 农业用地 → 农田保护区 (永久基本农田) ──
    LandUseClass("0101", "水田", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "0101", "永久基本农田"),
    LandUseClass("0102", "水浇地", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "0102", "永久基本农田"),
    LandUseClass("0103", "旱地", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "0103", "永久基本农田"),
    LandUseClass("0110", "水田(三级)", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "01", "耕地"),
    LandUseClass("0120", "旱地(三级)", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "01", "耕地"),
    LandUseClass("0130", "灌溉水田", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "01", "耕地"),
    LandUseClass("1100", "耕地(规划)", "农业用地", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "01", "规划耕地"),

    # ── 农业用地 → 一般农业区 (耕地 + 园地 + 商品林 + 设施农用地) ──
    LandUseClass("0100", "耕地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "01", "耕地"),
    LandUseClass("0200", "园地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "02", "园地"),
    LandUseClass("0201", "果园", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "0201", "园地"),
    LandUseClass("0202", "茶园", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "0202", "园地"),
    LandUseClass("0203", "橡胶园", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "0203", "园地"),
    LandUseClass("0204", "其他园地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "0204", "园地"),
    LandUseClass("0210", "园地(三级)", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "02", "园地"),
    LandUseClass("0220", "园地(三级)", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "02", "园地"),
    LandUseClass("1200", "其他土地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "12", "其他农用地"),
    LandUseClass("1201", "设施农用地(三级)", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "12", "设施农用地"),
    LandUseClass("1510", "设施农用地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "15", "设施农用地"),
    LandUseClass("2270", "水利设施用地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "22", "水利设施"),
    LandUseClass("3200", "自然保留地", "农业用地", "一般农业区", "农业空间",
                 ("GENERAL_AGRICULTURE",), "32", "自然保留地"),

    # ── 商品林 → 农业用地 (GB/T 21010 三大类: 林地归入农用地) ──
    LandUseClass("1340", "商品林", "农业用地", "林业发展区", "农业空间",
                 ("GENERAL_AGRICULTURE", "FORESTRY"), "0301",
                 "商品林(经济林)。GB/T 21010 三大类对照: 全部林地→农用地。"
                 "广东省村庄规划扩展: 归入'林业发展区'(农业空间下)。"
                 "区别于生态林(1350)"),

    # ── 生态绿地 → 生态保护区 (GB/T 21010 林地) ──
    LandUseClass("0300", "林地", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "03", "GB/T 21010 林地"),
    LandUseClass("0301", "乔木林地", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0301", "乔木林"),
    LandUseClass("0302", "竹林地", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0302", "竹林"),
    LandUseClass("0303", "红树林地", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0303", "红树林"),
    LandUseClass("0304", "森林沼泽", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0304", "森林沼泽"),
    LandUseClass("0305", "灌木林地", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0305", "灌木林"),
    LandUseClass("0306", "灌丛沼泽", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0306", "灌丛沼泽"),
    LandUseClass("0307", "其他林地", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "0307", "其他林地"),
    LandUseClass("0310", "有林地(三级)", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "03", "林地"),
    LandUseClass("0330", "其他林地(三级)", "生态绿地", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "FOREST"), "03", "林地"),

    # ── 生态林 → 生态绿地 (生态功能: 水源涵养、生物多样性) ──
    LandUseClass("1350", "生态林", "生态绿地", "林业发展区", "农业空间",
                 ("ECOLOGICAL", "FORESTRY"), "0301",
                 "生态林。广东省村庄规划扩展: 归入'林业发展区'(农业空间下)。"
                 "区别于商品林(1340)。生态功能: 水源涵养、生物多样性"),

    # ── 生态绿地 → 生态控制区 (草地: 非红线生态空间) ──
    LandUseClass("0400", "草地", "生态绿地", "生态控制区", "生态空间",
                 ("ECOLOGICAL", "GRASSLAND"), "04", "草地"),
    LandUseClass("0401", "天然牧草地", "生态绿地", "生态控制区", "生态空间",
                 ("ECOLOGICAL", "GRASSLAND"), "0401", "天然牧草"),
    LandUseClass("0402", "人工牧草地", "生态绿地", "生态控制区", "生态空间",
                 ("ECOLOGICAL", "GRASSLAND"), "0402", "人工牧草"),
    LandUseClass("0403", "其他草地", "生态绿地", "生态控制区", "生态空间",
                 ("ECOLOGICAL", "GRASSLAND"), "0403", "其他草地"),
    LandUseClass("0404", "沼泽草地", "生态绿地", "生态控制区", "生态空间",
                 ("ECOLOGICAL", "GRASSLAND"), "0404", "沼泽草地"),
    LandUseClass("1400", "草地(规划)", "生态绿地", "生态控制区", "生态空间",
                 ("ECOLOGICAL", "GRASSLAND"), "04", "规划草地"),

    # ── 水域 → 生态保护区 ──
    LandUseClass("1101", "河流水面", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1101", "河流"),
    LandUseClass("1102", "湖泊水面", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1102", "湖泊"),
    LandUseClass("1103", "水库水面", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1103", "水库"),
    LandUseClass("1104", "坑塘水面", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1104", "坑塘"),
    LandUseClass("1105", "沟渠", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1105", "沟渠"),
    LandUseClass("1106", "水工建筑用地", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1106", "水工建筑"),
    LandUseClass("1109", "冰川及永久积雪", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1109", "冰川"),
    LandUseClass("1110", "滩涂", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1110", "滩涂"),
    LandUseClass("1140", "沼泽地", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "1140", "沼泽"),
    LandUseClass("1180", "水田(水域)", "水域", "农田保护区", "农业空间",
                 ("BASIC_FARMLAND",), "11", "水域农田"),
    LandUseClass("3100", "水域(规划)", "水域", "生态保护区", "生态空间",
                 ("ECOLOGICAL", "WATER"), "31", "规划水域"),

    # ── 居住用地 → 村庄建设区 ──
    LandUseClass("0700", "城镇住宅用地", "居住用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0700", "城镇住宅"),
    LandUseClass("0701", "城镇住宅", "居住用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0701", "住宅"),
    LandUseClass("0702", "农村宅基地", "居住用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0702", "农村宅基地"),
    LandUseClass("2030", "农村宅基地(三级)", "居住用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "07", "农村宅基地"),
    LandUseClass("2121", "宅基地", "居住用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0702", "农村宅基地"),

    # ── 产业用地 → 村庄建设区 ──
    LandUseClass("0600", "工矿仓储用地", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "06", "工矿仓储"),
    LandUseClass("0601", "工业用地", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0601", "工业"),
    LandUseClass("0602", "采矿用地", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0602", "采矿"),
    LandUseClass("0603", "盐田", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0603", "盐田"),
    LandUseClass("0610", "工业(三级)", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "06", "工矿"),
    LandUseClass("0620", "采矿(三级)", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "06", "采矿"),
    LandUseClass("2100", "商服(三级)", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "21", "商服"),
    LandUseClass("2124", "经营性建设用地", "产业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0900", "经营性建设"),

    # ── 公共服务用地 → 村庄建设区 ──
    LandUseClass("0800", "公共管理与公共服务用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "08", "公服"),
    LandUseClass("0801", "机关团体用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0801", "机关团体"),
    LandUseClass("0802", "科研用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0802", "科研"),
    LandUseClass("0803", "文化用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0803", "文化"),
    LandUseClass("0806", "医疗卫生用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0806", "医疗"),
    LandUseClass("0810", "公园与绿地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0810", "公园绿地"),
    LandUseClass("0900", "特殊用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "09", "特殊用地"),
    LandUseClass("2122", "公共服务设施用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0800", "公服设施"),
    LandUseClass("2125", "景观与绿化用地", "公共服务用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1401", "景观绿化"),

    # ── 交通用地 → 村庄建设区 ──
    LandUseClass("1000", "交通运输用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "10", "交通"),
    LandUseClass("1001", "铁路用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1001", "铁路"),
    LandUseClass("1002", "轨道交通用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1002", "轨道"),
    LandUseClass("1003", "公路用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1003", "公路"),
    LandUseClass("1004", "机场用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1004", "机场"),
    LandUseClass("1005", "港口码头用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1005", "港口"),
    LandUseClass("1006", "农村道路", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1006", "农村道路"),
    LandUseClass("1040", "管道运输用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1040", "管道"),
    LandUseClass("2123", "基础设施用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "1300", "基础设施"),
    LandUseClass("2126", "村内交通用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "0601", "村内交通"),
    LandUseClass("2200", "对外交通用地", "交通用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "12", "对外交通"),

    # ── 商业用地 → 村庄建设区 ──
    LandUseClass("0500", "商服用地", "商业用地", "村庄建设区", "建设空间",
                 ("CONSTRUCTION",), "05", "商服"),
]

# ============================================================
# Zone type hierarchy metadata (derived from _CLASSES)
# ============================================================

ZONE_TYPES: List[str] = sorted(set(c.zone_type for c in _CLASSES))
PLANNING_ZONES: List[str] = sorted(set(c.planning_zone for c in _CLASSES))
PRIMARY_ZONES: List[str] = ["生态空间", "农业空间", "建设空间"]

PLANNING_ZONE_TO_PRIMARY_ZONE: Dict[str, str] = {
    "生态保护区": "生态空间",
    "生态控制区": "生态空间",
    "农田保护区": "农业空间",
    "一般农业区": "农业空间",
    "林业发展区": "农业空间",
    "村庄建设区": "建设空间",
}

# ============================================================
# Schema object — provides all export methods
# ============================================================


@dataclass
class ClassificationSchema:
    """Immutable snapshot of complete classification, with export methods."""

    classes: List[LandUseClass] = field(default_factory=lambda: list(_CLASSES))

    # ── Layer 1: DLBM → zone_type ──
    def to_dlbm_zone_type(self) -> Dict[str, str]:
        return {c.code: c.zone_type for c in self.classes}

    # ── Layer 2: DLBM → planning_zone ──
    def to_dlbm_planning_zone(self) -> Dict[str, str]:
        return {c.code: c.planning_zone for c in self.classes}

    # ── Layer 3: DLBM → primary_zone ──
    def to_dlbm_primary_zone(self) -> Dict[str, str]:
        return {c.code: c.primary_zone for c in self.classes}

    # ── Reverse: zone_type → DLBM codes ──
    def to_zone_type_dlbms(self) -> Dict[str, List[str]]:
        result: Dict[str, List[str]] = {}
        for c in self.classes:
            result.setdefault(c.zone_type, []).append(c.code)
        return result

    # ── Code sets (ECOLOGICAL_CODES etc.) ──
    def to_code_sets(self) -> Dict[str, Set[str]]:
        """Generate all code sets from category_sets tags."""
        sets: Dict[str, Set[str]] = {}
        for c in self.classes:
            for tag in c.category_sets:
                sets.setdefault(tag, set()).add(c.code)
        # Prefixed names matching code_sets.py conventions
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

    # ── LLM prompt: compact Markdown classification table ──
    def to_prompt_table(self) -> str:
        """Generate a compact reference table for LLM prompts.

        Format: | DLBM | 名称 | 功能分区 | 规划分区 | 三区 | GB/T |
        One row per planning_zone group for compactness.

        Follows Washington Post approach: structured taxonomy as prompt context.
        """
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

    # ── Planning zone → zone types mapping (for mapper.py) ──
    def to_planning_zone_zone_types(self) -> Dict[str, List[str]]:
        """Planning zone → list of zone types it contains."""
        result: Dict[str, List[str]] = {}
        seen = set()
        for c in self.classes:
            if c.planning_zone not in result:
                result[c.planning_zone] = []
            if c.zone_type not in seen:
                result[c.planning_zone].append(c.zone_type)
                seen.add((c.planning_zone, c.zone_type))
        # Deduplicate across
        return {k: sorted(set(v)) for k, v in result.items()}

    # ── Zone type → planning zone lookup ──
    def get_planning_zone_for_zone_type(self, zone_type: str, dlbm: str = "") -> str:
        """Get the correct planning zone for a zone_type, with DLBM-aware routing.

        This replaces map_zone_type_to_planning_zone() in planning_zone_mapper.py.
        """
        # If DLBM is provided, do precise lookup
        if dlbm:
            for c in self.classes:
                if c.code == dlbm:
                    return c.planning_zone
        # Fallback: use the most common planning zone for this zone_type
        planning_count: Dict[str, int] = {}
        for c in self.classes:
            if c.zone_type == zone_type:
                planning_count[c.planning_zone] = planning_count.get(c.planning_zone, 0) + 1
        if planning_count:
            return max(planning_count, key=planning_count.get)
        return "一般农业区"


# Module-level singleton
SCHEMA = ClassificationSchema()
