"""Deterministic regulation extractor — regex-based pattern matching.

Extracts spatial constraints from Chinese village planning regulation text
using pre-compiled regex patterns. Covers ~70% of common patterns.
Falls back to LLM only for unmatched lines.

Token savings: 4K-5K per call (70% deterministic + 30% LLM fallback).

Patterns are ported from EXTRACT_REGULATIONS_PROMPT in parse_prompts.py.
"""

from __future__ import annotations

import re
from typing import List, Dict, Optional

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Regex patterns for regulation extraction ─────────────────────────

# Each pattern: (regex, group_names, constraint_type)
# group_names maps regex groups to SpatialConstraint field names
REGULATION_PATTERNS: List[Dict] = [
    # ── Area constraints (land_use + operator + value) ──
    {
        "name": "area_min",
        "pattern": re.compile(
            r"(?P<land_use>耕地|基本农田|生态|林地|建设用地|住宅用地|宅基地)"
            r"\s*(?P<op_word>保有量|不低于|不少于|≥|不得低于|保持在)"
            r"\s*(?P<value>[\d.]+)\s*(?P<unit>公顷|ha|亩|万㎡|m²)?"
        ),
        "mapping": {
            "land_use": "land_use",
            "value": "target_area_ha",
            "operator": lambda m: ">=",
            "type": lambda m: "area_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "area_max",
        "pattern": re.compile(
            r"(?P<land_use>建设用地|村庄建设|住宅用地|产业用地)"
            r"\s*(?P<op_word>不超过|≤|上限|控制在|规模|不得突破)"
            r"\s*(?P<value>[\d.]+)\s*(?P<unit>公顷|ha|亩|万㎡)?"
        ),
        "mapping": {
            "land_use": "land_use",
            "value": "target_area_ha",
            "operator": lambda m: "<=",
            "type": lambda m: "area_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "area_equal",
        "pattern": re.compile(
            r"(?P<land_use>规划.*?用地|新增.*?用地)"
            r"\s*(?P<op_word>为|=|约|达到)\s*(?P<value>[\d.]+)\s*(?P<unit>公顷|ha|亩)?"
        ),
        "mapping": {
            "land_use": "land_use",
            "value": "target_area_ha",
            "operator": lambda m: "==",
            "type": lambda m: "area_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    # ── Spatial constraints ──
    {
        "name": "no_overlap_farmland",
        "pattern": re.compile(
            r"(?P<forbidden>禁止|不得|严禁)\s*(?P<subject>.{0,10}?)"
            r"\s*((在|占用|建设|开发)\s*)?(?P<object>耕地|基本农田|农田|生态红?线?保护)"
        ),
        "mapping": {
            "subject": "spatial_rule.subject",
            "object": "spatial_rule.object",
            "operation": lambda m: "no_overlap",
            "type": lambda m: "spatial_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "no_overlap_construction",
        "pattern": re.compile(
            r"(?P<forbidden>禁止|不得|严禁|不能)"
            r"\s*\S*\s*(?P<subject>建设|建筑|开发)"
        ),
        "mapping": {
            "subject": "construction",
            "object": "",
            "operation": lambda m: "no_overlap",
            "type": lambda m: "spatial_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "buffer_exclusion",
        "pattern": re.compile(
            r"(?P<subject>\S+)\s*(与|和|距离|距)\s*(?P<object>\S+)"
            r"\s*(?P<op_word>不低于|≥|不小于|大于|超过|间距?不少于)"
            r"\s*(?P<distance>[\d.]+)\s*米"
        ),
        "mapping": {
            "subject": "spatial_rule.subject",
            "object": "spatial_rule.object",
            "distance": "spatial_rule.distance_m",
            "operation": lambda m: "buffer_exclusion",
            "type": lambda m: "spatial_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "contained_by",
        "pattern": re.compile(
            r"(?P<subject>\S+)\s*(须在|必须在|位于|应在)"
            r"\s*(?P<object>\S+)\s*(内|边界内|范围内|内部)"
        ),
        "mapping": {
            "subject": "spatial_rule.subject",
            "object": "spatial_rule.object",
            "operation": lambda m: "contained_by",
            "type": lambda m: "spatial_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    # ── Building constraints ──
    {
        "name": "building_height",
        "pattern": re.compile(
            r"建筑(?:物)?高度\s*(?P<op_word>不超过|≤|限高|不大于|不得高于|控制在)"
            r"\s*(?P<value>[\d.]+)\s*米"
        ),
        "mapping": {
            "value": "max_height_m",
            "type": lambda m: "building_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "building_floors",
        "pattern": re.compile(
            r"(?P<op_word>不超过|≤|限|不大于)\s*(?P<value>[\d.]+)\s*层"
        ),
        "mapping": {
            "value": "max_floors",
            "type": lambda m: "building_constraint",
            "priority": lambda m: "recommended",
        },
    },
    {
        "name": "building_far",
        "pattern": re.compile(
            r"容积率\s*(?P<op_word>不超过|≤|不大于)\s*(?P<value>[\d.]+)"
        ),
        "mapping": {
            "value": "target_area_ha",  # FAR stored as ratio
            "type": lambda m: "building_constraint",
            "priority": lambda m: "mandatory",
        },
    },
    {
        "name": "building_density",
        "pattern": re.compile(
            r"建筑密度\s*(?P<op_word>不超过|≤|不大于|控制在)\s*(?P<value>[\d.]+)\s*%?"
        ),
        "mapping": {
            "value": "max_height_m",  # Density stored temporarily
            "type": lambda m: "building_constraint",
            "priority": lambda m: "recommended",
        },
    },
    # ── Population constraint ──
    {
        "name": "population_target",
        "pattern": re.compile(
            r"规划(?:期末)?(?:总)?人口\s*(?P<op_word>约|达到|为|控制在)"
            r"\s*(?P<value>[\d.]+)\s*人?"
        ),
        "mapping": {
            "value": "target_area_ha",  # Reuse field for population
            "type": lambda m: "area_constraint",
            "priority": lambda m: "mandatory",
        },
    },
]


# ── Main extraction function ─────────────────────────────────────────

def extract_regulations_regex(text: str) -> tuple[List[Dict], List[str]]:
    """Extract spatial constraints using regex patterns.

    Args:
        text: Regulation/protection section text

    Returns:
        (matched_constraints, unmatched_lines) tuple.
        matched_constraints: list of constraint dicts ready for SpatialConstraint
        unmatched_lines: lines that didn't match any pattern → route to LLM
    """
    matched: List[Dict] = []
    lines = text.split("\n")
    unmatched: List[str] = []

    for line in lines:
        line = line.strip()
        if not line or len(line) < 8:
            continue

        constraint = _match_line(line)
        if constraint:
            constraint["source_text"] = line[:200]
            # Extract article reference: 第X条, (X), X., etc.
            import re as _re
            article = _re.search(r"第\s*(\d+)\s*条", line)
            if article:
                constraint["article_ref"] = f"第{article.group(1)}条"
            matched.append(constraint)
        else:
            # Only keep substantive unmatched lines for LLM fallback
            if len(line) > 15 and any(kw in line for kw in
                ["建设", "保护", "禁止", "规模", "面积", "用地", "限", "控制",
                 "规划", "人口", "边界", "红线", "管制", "分区"]):
                unmatched.append(line)

    logger.info(
        "[regulation_extractor] Regex matched %d, unmatched %d (→ LLM)",
        len(matched), len(unmatched),
    )
    return matched, unmatched


def _match_line(line: str) -> Optional[Dict]:
    """Try all regex patterns against a single line. Return first match."""
    for pattern_def in REGULATION_PATTERNS:
        m = pattern_def["pattern"].search(line)
        if not m:
            continue

        constraint: Dict = {}
        mapping = pattern_def["mapping"]

        # Extract named groups
        for group_name, value in m.groupdict().items():
            if group_name in mapping:
                key = mapping[group_name]
                # Handle nested keys like "spatial_rule.subject"
                if "." in str(key):
                    parts = str(key).split(".")
                    current = constraint
                    for part in parts[:-1]:
                        if part not in current:
                            current[part] = {}
                        current = current[part]
                    current[parts[-1]] = value
                else:
                    constraint[str(key)] = value

        # Apply callable mappings (direction, type, priority)
        for key, value in mapping.items():
            if callable(value):
                constraint[str(key)] = value(m)

        # Standardize: ensure type field exists
        if "type" not in constraint:
            constraint["type"] = "spatial_constraint"

        # Standardize: ensure priority field exists
        if "priority" not in constraint:
            constraint["priority"] = "mandatory"

        return constraint

    return None
