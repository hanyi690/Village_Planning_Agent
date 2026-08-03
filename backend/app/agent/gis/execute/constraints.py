"""Constraint provenance — tag each MIP constraint with its source and dedupe."""
from __future__ import annotations
from typing import Any, Dict, List


def merge_sourced_constraints(
    kg_constraints: List[Dict[str, Any]],
    parse_constraints: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    merged: List[Dict[str, Any]] = []
    seen = set()
    for c in kg_constraints:
        key = ("kg:layer2", c.get("id", ""), c.get("operator", c.get("op", "")), str(c.get("value", "")))
        if key in seen:
            continue
        seen.add(key)
        merged.append({**c, "source_type": "kg:layer2"})
    for c in parse_constraints:
        key = ("parse", c.get("type", ""), str(c.get("value", "")), str(c.get("source_text", ""))[:40])
        if key in seen:
            continue
        seen.add(key)
        merged.append({**c, "source_type": "parse"})
    return merged
