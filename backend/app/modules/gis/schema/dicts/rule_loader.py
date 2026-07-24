"""Planning rule loader — YAML-driven rule integration for KG and PARSE.

Replaces hardcoded patterns in kg/builder.py with structured rules loaded
from the dicts/rules/ YAML files. Uses DictionaryCenter as the loading
infrastructure, but provides typed accessors specific to planning rules.

Available rule sets:
  - planning_targets.yaml  — 7 indicators (I01-I07, mandatory/expected)
  - land_use_structure.yaml — 19 categories (3 major groups)
  - planning_zone_rules.yaml — 4 zones + 16 decision rules + zone mapping
  - three_line_types.yaml — 3 control lines + construction zone

Usage:
    from app.modules.gis.schema.dicts.rule_loader import get_rule_loader

    loader = get_rule_loader()
    indicators = loader.planning_targets()
    categories = loader.land_use_categories()
    rules = loader.zone_decision_rules()
    mapping = loader.planning_zone_to_primary_zone()
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from app.utils.logger import get_logger

logger = get_logger(__name__)

_RULES_DIR = Path(__file__).parent / "rules"


# ── Typed rule data classes ─────────────────────────────────────────


@dataclass
class PlanningIndicator:
    """Single planning target indicator (from planning_targets.yaml)."""

    code: str = ""           # I01-I07
    name: str = ""           # e.g. "耕地保有量"
    unit: str = ""           # e.g. "公顷"
    attribute: str = ""      # "约束性" or "预期性"
    field: str = ""          # e.g. "farmland_area_ha"
    description: str = ""

    @property
    def is_mandatory(self) -> bool:
        return self.attribute == "约束性"


@dataclass
class LandUseCategory:
    """Single land use category (from land_use_structure.yaml)."""

    code: str = ""           # e.g. "1100"
    name: str = ""           # e.g. "耕地"
    parent: str = ""         # e.g. "农业用地" or "建设用地.村庄建设用地"
    ghytbm: str = ""         # planning use code

    @property
    def major_group(self) -> str:
        """Extract top-level group: 农业用地/建设用地/生态用地."""
        return self.parent.split(".")[0] if self.parent else ""


@dataclass
class ZoneDecisionRule:
    """Single zone decision rule (from planning_zone_rules.yaml)."""

    priority: int = 0
    condition: str = ""
    result: str = ""
    description: str = ""
    params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ZoneDefinition:
    """Planning zone definition (from planning_zone_rules.yaml)."""

    code: str = ""           # 510/520/530/540
    name: str = ""
    color: str = ""


@dataclass
class ThreeLineDefinition:
    """Three-line control layer (from three_line_types.yaml)."""

    key: str = ""
    label: str = ""
    color: str = ""
    line_style: str = ""
    fill_opacity: str = "0.0"
    stroke_width: str = "2.0"
    gdb_key: str = ""


# ── Rule loader ─────────────────────────────────────────────────────


class PlanningRuleLoader:
    """Loads planning rules from YAML, replacing hardcoded patterns.

    Provides typed accessors for each rule set. Rules are loaded lazily
    and cached for the lifetime of the loader instance.
    """

    def __init__(self, rules_dir: Optional[Path] = None):
        self._rules_dir = rules_dir or _RULES_DIR
        self._cache: Dict[str, Any] = {}

    def _load_yaml(self, name: str) -> Dict[str, Any]:
        """Load a YAML file from rules/ directory."""
        if name not in self._cache:
            filepath = self._rules_dir / f"{name}.yaml"
            if not filepath.exists():
                logger.warning("[RuleLoader] %s not found at %s", name, filepath)
                return {}
            with open(filepath, "r", encoding="utf-8") as f:
                self._cache[name] = yaml.safe_load(f) or {}
        return self._cache[name]

    # ── Planning targets (附表1) ────────────────────────────────

    def planning_targets(self) -> List[PlanningIndicator]:
        """Load 7 standard indicators from planning_targets.yaml."""
        data = self._load_yaml("planning_targets")
        indicators = []
        for item in data.get("indicators", []):
            indicators.append(PlanningIndicator(
                code=item.get("code", ""),
                name=item.get("name", ""),
                unit=item.get("unit", ""),
                attribute=item.get("attribute", ""),
                field=item.get("field", ""),
                description=item.get("description", ""),
            ))
        return indicators

    def mandatory_indicators(self) -> List[PlanningIndicator]:
        """Return only mandatory (约束性) indicators."""
        return [ind for ind in self.planning_targets() if ind.is_mandatory]

    def expected_indicators(self) -> List[PlanningIndicator]:
        """Return only expected (预期性) indicators."""
        return [ind for ind in self.planning_targets() if not ind.is_mandatory]

    def indicator_by_field(self, field_name: str) -> Optional[PlanningIndicator]:
        """Look up indicator by its state field name."""
        for ind in self.planning_targets():
            if ind.field == field_name:
                return ind
        return None

    # ── Land use structure (附表2) ──────────────────────────────

    def land_use_categories(self) -> List[LandUseCategory]:
        """Load 19 land use categories from land_use_structure.yaml."""
        data = self._load_yaml("land_use_structure")
        categories = []
        for item in data.get("categories", []):
            categories.append(LandUseCategory(
                code=item.get("code", ""),
                name=item.get("name", ""),
                parent=item.get("parent", ""),
                ghytbm=item.get("ghytbm", ""),
            ))
        return categories

    def categories_by_group(self, group: str) -> List[LandUseCategory]:
        """Filter categories by major group (农业用地/建设用地/生态用地)."""
        return [c for c in self.land_use_categories() if c.major_group == group]

    def category_by_code(self, code: str) -> Optional[LandUseCategory]:
        """Look up category by GHYTBM code."""
        for cat in self.land_use_categories():
            if cat.code == code or cat.ghytbm == code:
                return cat
        return None

    def category_by_name(self, name: str) -> Optional[LandUseCategory]:
        """Look up category by Chinese name."""
        for cat in self.land_use_categories():
            if cat.name == name:
                return cat
        return None

    # ── Zone decision rules ────────────────────────────────────

    def zone_definitions(self) -> List[ZoneDefinition]:
        """Load 4 planning zone definitions from planning_zone_rules.yaml."""
        data = self._load_yaml("planning_zone_rules")
        zones = []
        for item in data.get("zones", []):
            zones.append(ZoneDefinition(
                code=item.get("code", ""),
                name=item.get("name", ""),
                color=item.get("color", ""),
            ))
        return zones

    def zone_decision_rules(self) -> List[ZoneDecisionRule]:
        """Load decision rules from planning_zone_rules.yaml."""
        data = self._load_yaml("planning_zone_rules")
        rules = []
        for item in data.get("decision_rules", []):
            rules.append(ZoneDecisionRule(
                priority=item.get("priority", 0),
                condition=item.get("condition", ""),
                result=item.get("result", ""),
                description=item.get("description", ""),
                params=item.get("params", {}),
            ))
        return sorted(rules, key=lambda r: r.priority)

    def planning_zone_to_primary_zone(self) -> Dict[str, str]:
        """Load zone -> primary zone mapping from planning_zone_rules.yaml."""
        data = self._load_yaml("planning_zone_rules")
        return dict(data.get("planning_zone_to_primary_zone", {}))

    # ── Three line types ───────────────────────────────────────

    def three_line_types(self) -> List[ThreeLineDefinition]:
        """Load 3 control line definitions from three_line_types.yaml."""
        data = self._load_yaml("three_line_types")
        lines = []
        for item in data.get("layers", []):
            lines.append(ThreeLineDefinition(
                key=item.get("key", ""),
                label=item.get("label", ""),
                color=item.get("color", ""),
                line_style=item.get("line_style", ""),
                fill_opacity=item.get("fill_opacity", "0.0"),
                stroke_width=item.get("stroke_width", "2.0"),
                gdb_key=item.get("gdb_key", ""),
            ))
        return lines

    def construction_zone(self) -> Dict[str, Any]:
        """Load construction zone definition from three_line_types.yaml."""
        data = self._load_yaml("three_line_types")
        return data.get("construction_zone", {})

    def annotation_categories(self) -> List[Dict[str, str]]:
        """Load annotation categories from three_line_types.yaml."""
        data = self._load_yaml("three_line_types")
        return data.get("annotation_categories", [])

    # ── Prompt formatting helpers (cached — YAML rules never change) ─

    @lru_cache(maxsize=1)
    def format_targets_for_prompt(self) -> str:
        """Format planning targets as a markdown table for LLM prompt."""
        indicators = self.planning_targets()
        if not indicators:
            return ""
        lines = ["## 规划目标指标（附表1）", ""]
        lines.append("| 编码 | 指标名称 | 单位 | 属性 | 字段 |")
        lines.append("|------|---------|------|------|------|")
        for ind in indicators:
            lines.append(
                f"| {ind.code} | {ind.name} | {ind.unit} | {ind.attribute} | {ind.field} |"
            )
        lines.append("")
        return "\n".join(lines)

    @lru_cache(maxsize=1)
    def format_categories_for_prompt(self) -> str:
        """Format land use categories as a markdown table for LLM prompt."""
        categories = self.land_use_categories()
        if not categories:
            return ""
        lines = ["## 土地利用结构（附表2）", ""]
        lines.append("| 编码 | 名称 | 大类 | GHYTBM |")
        lines.append("|------|------|------|--------|")
        for cat in categories:
            lines.append(
                f"| {cat.code} | {cat.name} | {cat.major_group} | {cat.ghytbm} |"
            )
        lines.append("")
        return "\n".join(lines)

    @lru_cache(maxsize=1)
    def format_control_rules_for_prompt(self) -> str:
        """Format 6 standard control rule categories for LLM prompt."""
        lines = ["## 管制规则（附录3 — 6大类）", ""]
        rule_categories = [
            ("生态保护", "生态保护红线范围+禁止建设活动+保护生态用地名录"),
            ("耕地和永久基本农田保护", "基本农田面积+集中分布区+占用审批程序+设施农用地管理规定"),
            ("历史文化传承与保护", "文物保护单位名录+历史文化保护线范围+修缮审批要求"),
            ("建设空间管制", "经营性建设用地密度/高度/容积率/绿地率 + 农村住房面积/层数/高度/风貌 + 基础设施退线距离"),
            ("村庄安全和防灾减灾", "避开自然灾害区+消防通道要求+应急庇护场所"),
            ("其他管制规则", "各村实际情况制定"),
        ]
        for i, (name, desc) in enumerate(rule_categories, 1):
            lines.append(f"{i}. **{name}**: {desc}")
        lines.append("")
        return "\n".join(lines)

    @lru_cache(maxsize=1)
    def format_zone_mapping_for_prompt(self) -> str:
        """Format planning zone -> primary zone mapping for LLM prompt."""
        mapping = self.planning_zone_to_primary_zone()
        if not mapping:
            return ""
        lines = ["## 规划分区→三区映射", ""]
        for zone, primary in mapping.items():
            lines.append(f"- {zone} → {primary}")
        lines.append("")
        return "\n".join(lines)

    @lru_cache(maxsize=1)
    def format_mandatory_indicators_for_prompt(self) -> str:
        """Format 7 mandatory indicators as a MUST-FILL checklist for LLM.

        Requires the LLM to fill every indicator field in the output.
        """
        indicators = self.planning_targets()
        if not indicators:
            return ""
        lines = ["## 必填指标清单（附表1 — 必须逐项填写）", ""]
        for ind in indicators:
            attr = "约束性" if ind.is_mandatory else "预期性"
            lines.append(f"- {ind.code} {ind.name}（{attr}）→ 字段 `{ind.field}`（单位: {ind.unit}）")
        lines.append("")
        return "\n".join(lines)

    @lru_cache(maxsize=1)
    def format_valid_land_uses_for_prompt(self) -> str:
        """Format 19 valid land-use names as an enum constraint for LLM.

        The LLM must ONLY use these land_use names in zone_targets.
        """
        categories = self.land_use_categories()
        if not categories:
            return ""
        lines = ["## 合法用地名称（附表2 — zone_targets.land_use 仅限以下19类）", ""]
        for cat in categories:
            lines.append(f"- {cat.name}（GHYTBM={cat.ghytbm}）")
        lines.append("")
        return "\n".join(lines)

    @lru_cache(maxsize=1)
    def format_vne_mapping_for_prompt(self) -> str:
        """Format GHYTBM → VNE mapping as a derivation rule for LLM.

        The LLM must auto-compute vne_code from the GHYTBM code.
        """
        try:
            from app.modules.gis.schema.code_sets import GHYTBM_TO_VNE, VNE_CODE_TO_NAME
        except Exception:
            return ""
        if not GHYTBM_TO_VNE:
            return ""
        lines = ["## GHYTBM → VNE 推导规则（自动计算 vne_code）", ""]
        for ghytbm, vne in GHYTBM_TO_VNE.items():
            vne_name = VNE_CODE_TO_NAME.get(vne, "")
            lines.append(f"- {ghytbm} → {vne}（{vne_name}）")
        lines.append("")
        return "\n".join(lines)


# ── Singleton ───────────────────────────────────────────────────────

_loader: Optional[PlanningRuleLoader] = None


def get_rule_loader() -> PlanningRuleLoader:
    """Get the singleton PlanningRuleLoader instance."""
    global _loader
    if _loader is None:
        _loader = PlanningRuleLoader()
    return _loader


__all__ = [
    "PlanningIndicator",
    "LandUseCategory",
    "ZoneDecisionRule",
    "ZoneDefinition",
    "ThreeLineDefinition",
    "PlanningRuleLoader",
    "get_rule_loader",
]
