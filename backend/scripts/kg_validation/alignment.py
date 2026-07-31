"""
alignment.py — 三层对齐检查器
  HIT      : KG答案与ground-truth一致（在容差内）
  MISS_A   : Agent A无法从KG获得答案（proxy/method描述），但文档中有
  KG_GAP   : KG答案与ground-truth不一致（超出容差）

容差规则 (scenario_rules.json):
  text_description : Jaccard(name_set) ≥ 0.7
  count            : ±0
  percentage       : ±2pp
  area_ha          : ±5%
  direction        : 严格字符串匹配
  distance_m       : ±10%
  planning_project : 数量±0 + 名称子串匹配
"""
from __future__ import annotations

import json
import math
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

TRUTH_TABLE = PROJECT_ROOT / "output/kg_validation/alignment/truth_table.json"
SCENARIO_RULES = PROJECT_ROOT / "output/kg_validation/alignment/scenario_rules.json"
AGENT_A_DIR = PROJECT_ROOT / "output/kg_validation/subagent_A_blind"
AGENT_B_DIR = PROJECT_ROOT / "output/kg_validation/subagent_B_docs"
OUTPUT_DIR = PROJECT_ROOT / "output/kg_validation/alignment"


@dataclass
class ScenarioRule:
    scenario: str
    tolerance: str
    threshold: Optional[float] = None
    compare_fn: str = "direct"


@dataclass
class FactEntry:
    fact_id: str
    question: str
    scenario: str
    expected_value: Any
    kg_query_hint: str
    tolerance: str
    agent_A_answer: Any = None
    agent_A_raw: Any = None
    agent_A_tools: List[str] = field(default_factory=list)
    agent_A_confidence: str = "unknown"
    agent_A_gap_note: str = ""
    agent_A_elapsed_ms: float = 0.0
    alignment: str = "PENDING"
    delta: Any = None
    delta_pct: float = 0.0
    notes: str = ""


def load_json(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def parse_number(val: Any) -> Optional[float]:
    if val is None:
        return None
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        val = val.strip()
        m = re.search(r"[\d.]+", val)
        if m:
            return float(m.group())
    return None


def jaccard_name_sets(text_a: str, text_b: str) -> float:
    def tokens(t):
        return set(re.findall(r"[\u4e00-\u9fff]+", str(t)))  # 中文字词

    a, b = tokens(text_a), tokens(text_b)
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


def normalize_direction(text: str) -> str:
    return re.sub(r"[\s\-–—]", "", text.strip().upper())


def compare_text_description(agent_val: Any, expected: Any, threshold: float = 0.7) -> Tuple[str, float]:
    """Jaccard(name_set) ≥ 0.7 → HIT"""
    score = jaccard_name_sets(str(agent_val), str(expected))
    status = "HIT" if score >= threshold else "KG_GAP"
    return status, score


def compare_count(agent_val: Any, expected: Any, **kwargs) -> Tuple[str, Any]:
    """±0"""
    a = parse_number(agent_val)
    e = parse_number(expected)
    if a is None or e is None:
        return "KG_GAP", None
    delta = a - e
    status = "HIT" if delta == 0 else "KG_GAP"
    return status, delta


def compare_percentage(agent_val: Any, expected: Any, threshold: float = 2.0, **kwargs) -> Tuple[str, Any]:
    """±2pp"""
    a = parse_number(agent_val)
    e = parse_number(expected)
    if a is None or e is None:
        return "KG_GAP", None
    delta = a - e
    status = "HIT" if abs(delta) <= threshold else "KG_GAP"
    return status, delta


def compare_area_ha(agent_val: Any, expected: Any, threshold: float = 0.05, **kwargs) -> Tuple[str, Any]:
    """±5%"""
    a = parse_number(agent_val)
    e = parse_number(expected)
    if a is None or e is None or e == 0:
        return "KG_GAP", None
    delta_pct = (a - e) / e
    status = "HIT" if abs(delta_pct) <= threshold else "KG_GAP"
    return status, delta_pct


def compare_direction(agent_val: Any, expected: Any, **kwargs) -> Tuple[str, Any]:
    """严格字符串匹配"""
    a = normalize_direction(str(agent_val) if agent_val else "")
    e = normalize_direction(str(expected) if expected else "")
    status = "HIT" if a == e else "KG_GAP"
    return status, None


def compare_distance_m(agent_val: Any, expected: Any, threshold: float = 0.10, **kwargs) -> Tuple[str, Any]:
    """±10%"""
    a = parse_number(agent_val)
    e = parse_number(expected)
    if a is None or e is None or e == 0:
        return "KG_GAP", None
    delta_pct = (a - e) / e
    status = "HIT" if abs(delta_pct) <= threshold else "KG_GAP"
    return status, delta_pct


def compare_planning_project(agent_val: Any, expected: Any, **kwargs) -> Tuple[str, Any]:
    """数量±0 + 名称子串匹配"""
    def count_projects(val):
        if isinstance(val, list):
            return len(val)
        n = parse_number(val)
        return int(n) if n is not None else 0

    def names_contain(expected_str: str, agent_str: str) -> bool:
        key_words = [w for w in re.findall(r"[\u4e00-\u9fff]+", expected_str) if len(w) >= 2]
        return all(w in agent_str for w in key_words)

    a_count = count_projects(agent_val)
    e_count = count_projects(expected)
    delta = a_count - e_count
    name_ok = names_contain(str(expected), str(agent_val)) if expected else True
    if delta == 0 and name_ok:
        return "HIT", delta
    if a_count == 0 and e_count > 0:
        return "MISS_A", delta
    return "KG_GAP", delta


COMPARATORS = {
    "text_description": compare_text_description,
    "count": compare_count,
    "percentage": compare_percentage,
    "area_ha": compare_area_ha,
    "direction": compare_direction,
    "distance_m": compare_distance_m,
    "planning_project": compare_planning_project,
}


def is_proxy_answer(val: Any) -> bool:
    if val is None:
        return True
    s = str(val)
    proxy_markers = ["method", "proxy", "ERROR", "None", "kg_can_answer"]
    return any(m.lower() in s.lower() for m in proxy_markers)


def align_fact(fact: FactEntry, agent_a_answers: List[Dict]) -> FactEntry:
    a_entry = next((a for a in agent_a_answers if a["fact_id"] == fact.fact_id), None)

    if a_entry:
        fact.agent_A_answer = a_entry.get("agent_A_answer")
        fact.agent_A_raw = a_entry.get("raw_data")
        fact.agent_A_tools = a_entry.get("tools_used", [])
        fact.agent_A_confidence = a_entry.get("confidence", "unknown")
        fact.agent_A_gap_note = a_entry.get("gap_note", "")
        fact.agent_A_elapsed_ms = a_entry.get("elapsed_ms", 0.0)

    if fact.agent_A_answer is None or is_proxy_answer(fact.agent_A_answer):
        fact.alignment = "MISS_A"
        fact.notes = "Agent A 无法从 KG 获得答案（proxy/method/None）"
        return fact

    comparator = COMPARATORS.get(fact.scenario)
    if not comparator:
        fact.alignment = "KG_GAP"
        fact.notes = f"未知的 scenario: {fact.scenario}"
        return fact

    status, delta = comparator(fact.agent_A_answer, fact.expected_value)
    fact.alignment = status
    fact.delta = delta

    if status == "HIT":
        fact.notes = "一致"
    elif status == "MISS_A":
        fact.notes = f"Agent A 答案 proxy，但 KG 有数据: {fact.agent_A_answer}"
    else:
        fact.notes = f"KG答案与ground-truth不一致: {fact.agent_A_answer} vs {fact.expected_value}"

    return fact


def run_alignment() -> Dict[str, Any]:
    truth_table = load_json(TRUTH_TABLE)
    scenario_rules = load_json(SCENARIO_RULES)

    agent_a_answers = []
    answers_path = AGENT_A_DIR / "answers.json"
    if answers_path.exists():
        data = load_json(answers_path)
        agent_a_answers = data.get("results", [])

    raw_facts = truth_table.get("facts") or list(truth_table.values())
    valid_fields = {f.name for f in FactEntry.__dataclass_fields__.values()}
    patched = []
    for f in raw_facts:
        f["question"] = f.get("claim") or f.get("question", "")
        f["expected_value"] = f.get("expected") or f.get("expected_value")
        cleaned = {k: v for k, v in f.items() if k in valid_fields}
        patched.append(FactEntry(**cleaned))
    facts = patched

    for fact in facts:
        align_fact(fact, agent_a_answers)

    hit = sum(1 for f in facts if f.alignment == "HIT")
    miss_a = sum(1 for f in facts if f.alignment == "MISS_A")
    kg_gap = sum(1 for f in facts if f.alignment == "KG_GAP")
    total = len(facts)

    hit_pct = hit / total * 100 if total else 0
    miss_a_pct = miss_a / total * 100 if total else 0
    kg_gap_pct = kg_gap / total * 100 if total else 0

    report = {
        "summary": {
            "total": total,
            "HIT": hit,
            "MISS_A": miss_a,
            "KG_GAP": kg_gap,
            "HIT_pct": round(hit_pct, 1),
            "MISS_A_pct": round(miss_a_pct, 1),
            "KG_GAP_pct": round(kg_gap_pct, 1),
            "thresholds": {"HIT_pct_min": 60, "KG_GAP_pct_max": 30, "MISS_A_pct_max": 10},
            "pass": hit_pct >= 60 and kg_gap_pct <= 30 and miss_a_pct <= 10,
        },
        "scenario_breakdown": _scenario_breakdown(facts),
        "facts": [_fact_to_dict(f) for f in facts],
    }

    save_json(OUTPUT_DIR / "alignment_report.json", report)

    print("\n" + "=" * 60)
    print("  KG SPATIAL VALIDATION — ALIGNMENT REPORT")
    print("=" * 60)
    print(f"  总事实数     : {total}")
    print(f"  HIT         : {hit} ({hit_pct:.1f}%)  [阈值≥60%]  {'✓ PASS' if hit_pct>=60 else '✗ FAIL'}")
    print(f"  MISS_A      : {miss_a} ({miss_a_pct:.1f}%)  [阈值≤10%]  {'✓ PASS' if miss_a_pct<=10 else '✗ FAIL'}")
    print(f"  KG_GAP      : {kg_gap} ({kg_gap_pct:.1f}%)  [阈值≤30%]  {'✓ PASS' if kg_gap_pct<=30 else '✗ FAIL'}")
    print("=" * 60)
    print(f"  Overall: {'✓ PASS' if report['summary']['pass'] else '✗ FAIL'}")
    print(f"  Report: {OUTPUT_DIR / 'alignment_report.json'}")
    print()

    return report


def _scenario_breakdown(facts: List[FactEntry]) -> Dict[str, Dict[str, int]]:
    from collections import defaultdict
    breakdown = defaultdict(lambda: {"HIT": 0, "MISS_A": 0, "KG_GAP": 0})
    for f in facts:
        breakdown[f.scenario][f.alignment] += 1
    return dict(breakdown)


def _fact_to_dict(f: FactEntry) -> Dict[str, Any]:
    return {
        "fact_id": f.fact_id,
        "question": f.question,
        "scenario": f.scenario,
        "expected_value": f.expected_value,
        "kg_query_hint": f.kg_query_hint,
        "tolerance": f.tolerance,
        "agent_A_answer": f.agent_A_answer,
        "agent_A_raw": f.agent_A_raw,
        "agent_A_confidence": f.agent_A_confidence,
        "agent_A_gap_note": f.agent_A_gap_note,
        "agent_A_elapsed_ms": f.agent_A_elapsed_ms,
        "alignment": f.alignment,
        "delta": f.delta,
        "delta_pct": f.delta_pct,
        "notes": f.notes,
    }


if __name__ == "__main__":
    run_alignment()
