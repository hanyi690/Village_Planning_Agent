"""从 Agent B 的 facts.json 生成 truth_table.json 初版（开发者 review 前置）。

执行: python scripts/kg_validation/generate_truth_table.py
"""
from __future__ import annotations

import json
from pathlib import Path

_FACTS_PATH = Path(__file__).parent.parent.parent / "output" / "kg_validation" / "subagent_B_docs" / "facts.json"
_TRUTH_PATH = Path(__file__).parent.parent.parent / "output" / "kg_validation" / "alignment" / "truth_table.json"
_SCENARIO_RULES_PATH = Path(__file__).parent.parent.parent / "output" / "kg_validation" / "alignment" / "scenario_rules.json"

# ── 场景分类规则 ─────────────────────────────────────────────────────────────
SCENARIO_RULES = {
    "count": {
        "description": "数量（地块/设施/控制点）",
        "tolerance": "±0 或 ±5% (纯计数用±0，面积计数用±5%)",
        "pass_condition": "实际值 vs 期望值误差 ≤ tolerance",
        "numeric": True,
    },
    "area_ha": {
        "description": "面积（ha）",
        "tolerance": "±5%",
        "pass_condition": "abs(actual - expected) / expected ≤ 0.05",
        "numeric": True,
    },
    "percentage": {
        "description": "比例/百分比",
        "tolerance": "±2pp",
        "pass_condition": "abs(actual_pct - expected_pct) ≤ 2",
        "numeric": True,
    },
    "name_set": {
        "description": "名称集合（自然村/设施/项目）",
        "tolerance": "Jaccard ≥ 0.7 (期望集合 vs Agent A 集合)",
        "pass_condition": "len(intersection) / len(union) ≥ 0.7",
        "numeric": False,
    },
    "topology": {
        "description": "拓扑关系（相邻/包含/经过）",
        "tolerance": "严格匹配",
        "pass_condition": "sfTouches / sfWithin / sfIntersects / nearby / connected_via_road 命中其一",
        "numeric": False,
    },
    "direction": {
        "description": "方向（北/南/东/西/中/东北/西北/东南/西南）",
        "tolerance": "严格（8方位之一）",
        "pass_condition": "方向词精确匹配",
        "numeric": False,
    },
    "distance_km": {
        "description": "距离（km）",
        "tolerance": "±10%",
        "pass_condition": "abs(actual - expected) / expected ≤ 0.10",
        "numeric": True,
    },
    "distance_m": {
        "description": "距离（m）",
        "tolerance": "±10%",
        "pass_condition": "abs(actual - expected) / expected ≤ 0.10",
        "numeric": True,
    },
    "exists": {
        "description": "实体存在性",
        "tolerance": "严格（名称在 KG 输出中出现）",
        "pass_condition": "期望实体名称 ∈ Agent A 输出集合",
        "numeric": False,
    },
    "text_description": {
        "description": "文本描述（语义相似）",
        "tolerance": "关键词重合 ≥ 0.6 或 语义相似 ≥ 0.6",
        "pass_condition": "Agent A 描述包含 truth 中 ≥ 60% 关键词",
        "numeric": False,
    },
    "ratio": {
        "description": "比例系数（如林地占90%）",
        "tolerance": "±2pp",
        "pass_condition": "abs(actual_ratio - expected_ratio) ≤ 0.02",
        "numeric": True,
    },
    "planning_project": {
        "description": "规划项目（子集关系）",
        "tolerance": "truth ⊇ agent_A (Agent A 项目是 truth 子集)",
        "pass_condition": "Agent A 返回的项目集合 ⊆ truth 项目集合",
        "numeric": False,
    },
    "aggregate_area_ha": {
        "description": "聚合面积（多地块合计）",
        "tolerance": "±5%",
        "pass_condition": "abs(sum(actual) - expected) / expected ≤ 0.05",
        "numeric": True,
    },
}


def _infer_scenario(fact: dict) -> str:
    """根据 fact 内容推断场景类型。"""
    claim = fact.get("claim", "")
    unit = fact.get("unit", "")
    entities = fact.get("entities", [])
    fact_id = fact.get("fact_id", "")

    if any(kw in claim for kw in ["处", "个", "座", "间"]) and unit in ("", "处", "个", "座"):
        return "count"
    if unit in ("公顷", "ha", "km²", "m²"):
        if "比例" in claim or "%" in claim or "占比" in claim:
            return "percentage"
        return "area_ha"
    if unit == "公里":
        return "distance_km"
    if unit in ("米", "m"):
        return "distance_m"
    if any(t in claim for t in ["北侧", "南侧", "东侧", "西侧", "贯穿", "位于"]):
        if any(d in claim for d in ["北", "南", "东", "西"]):
            return "direction"
    if isinstance(entities, list) and len(entities) > 2 and not unit:
        return "name_set"
    if fact_id.startswith("F49"):
        return "planning_project"
    if "比例" in claim or "占比" in claim or "%" in claim:
        return "ratio"
    if "项目" in claim or "产业" in claim:
        return "planning_project"
    return "text_description"


def _build_truth_entry(fact: dict) -> dict:
    """从 fact 构建 truth_table 条目。"""
    fact_id = fact["fact_id"]
    claim = fact.get("claim", "")
    unit = fact.get("unit", "")
    num_val = fact.get("numeric_value")
    entities = fact.get("entities", [])
    direction = fact.get("direction")
    scenario = _infer_scenario(fact)

    entry = {
        "fact_id": fact_id,
        "scenario": scenario,
        "claim": claim,
        "expected": None,
        "tolerance": SCENARIO_RULES[scenario]["tolerance"],
        "pass_condition": SCENARIO_RULES[scenario]["pass_condition"],
        "agent_B_fact": {
            "claim": claim,
            "numeric_value": num_val,
            "unit": unit,
            "entities": entities,
            "direction": direction,
            "evidence_quote": fact.get("evidence_quote", ""),
            "source_file": fact.get("source_file", ""),
            "confidence": fact.get("confidence", "medium"),
        },
        "kg_query_hint": _suggest_kg_query(fact_id, scenario, entities, num_val, claim),
        "notes": "",
    }

    if scenario == "count" and num_val is not None:
        entry["expected"] = num_val
    elif scenario in ("area_ha", "distance_km", "distance_m", "percentage", "ratio"):
        entry["expected"] = num_val
    elif scenario == "name_set":
        entry["expected"] = entities if isinstance(entities, list) else []
    elif scenario == "direction":
        entry["expected"] = direction
    elif scenario == "topology":
        entry["expected"] = fact.get("relation_type", "")
    elif scenario == "exists":
        entry["expected"] = entities[0] if entities else claim.split("在")[0] if "在" in claim else claim
    elif scenario == "planning_project":
        entry["expected"] = entities if isinstance(entities, list) else []
    elif scenario == "text_description":
        entry["expected"] = claim
    else:
        entry["expected"] = num_val or claim

    return entry


def _suggest_kg_query(fact_id: str, scenario: str, entities: list, num_val, claim: str) -> str:
    """为每项生成 KG 查询提示（供 Agent A 参考，不强制）。"""
    hints = {
        "F01": "SUM(SELECT ?area_ha WHERE { ?p a pln:Parcel ; pln:area_ha ?area_ha . })",
        "F02": "dlbm IN 0101,0102,0103,0201,0301,... SUM area_ha",
        "F03": "dlbm IN 0701,0702,1202 SUM area_ha",
        "F04": "dlbm IN 0301,0302,0307,1101... + WaterBody SUM area_ha",
        "F05": "dlbm = 0101 SUM area_ha",
        "F06": "dlbm IN 0301,0302,0303,0304,0305,0306,0307 SUM area_ha",
        "F07": "dlbm IN 11xx (WaterBody) SUM area_ha",
        "F09": "get_village_anchors() + annotation names",
        "F10": "get_entity_relations(village_uri) -> rdf:type = AdministrativeVillage",
        "F11": "get_parcels_by_dlbm(0702) + bbox clustering",
        "F13": "get_road_network() -> road_level=乡道, orientation=E-W",
        "F17": "get_facility_locations() near yuanzhai anchor",
        "F21": "annotation labels = 祠堂",
        "F23": "WaterBody entity + bbox lon range (SW→NE)",
        "F24": "WaterBody sfWithin/nearby Facility(type=水电站)",
        "F25": "ControlLine count by hazard_type",
        "F26": "annotation name contains 古檀",
        "F28": "annotation name contains 古驿道",
        "F29": "annotation name contains 茶亭",
        "F30": "annotation name contains 古檀林",
        "F31": "AdministrativeVillage attrs: 户籍人口/常住人口",
        "F33": "ZoneTarget land_use description",
        "F35": "ZoneTarget cluster count",
        "F40-F43": "ZoneTarget/PlannedZone by spatial_hint",
        "F49-F58": "PlannedState version=近期/远期 parcels + facilities",
        "F59": "ControlLine(type=坑塘调蓄) count",
        "F60": "PlannedFacility type=微型消防站 location",
    }
    return hints.get(fact_id, f"scenario={scenario}, entities={entities}")


def main():
    # facts.json at: output/kg_validation/subagent_B_docs/facts.json
    # script at: backend/scripts/kg_validation/generate_truth_table.py
    # project root = parents[3]
    PROJECT_ROOT = Path(__file__).resolve().parents[3]
    facts_path = PROJECT_ROOT / "output" / "kg_validation" / "subagent_B_docs" / "facts.json"
    truth_path = PROJECT_ROOT / "output" / "kg_validation" / "alignment" / "truth_table.json"
    rules_path = PROJECT_ROOT / "output" / "kg_validation" / "alignment" / "scenario_rules.json"

    with open(facts_path, "r", encoding="utf-8") as f:
        facts = json.load(f)

    truth_table = {}
    for fact in facts:
        entry = _build_truth_entry(fact)
        truth_table[entry["fact_id"]] = entry

    # 写 truth_table.json
    with open(truth_path, "w", encoding="utf-8") as f:
        json.dump(truth_table, f, ensure_ascii=False, indent=2)
    print(f"[generate_truth_table] truth_table.json -> {truth_path}")
    print(f"  共 {len(truth_table)} 项事实")

    # 写 scenario_rules.json
    with open(rules_path, "w", encoding="utf-8") as f:
        json.dump(SCENARIO_RULES, f, ensure_ascii=False, indent=2)
    print(f"[generate_truth_table] scenario_rules.json -> {rules_path}")

    # 打印场景分布统计
    scenario_counts = {}
    for entry in truth_table.values():
        s = entry["scenario"]
        scenario_counts[s] = scenario_counts.get(s, 0) + 1
    print("\n场景分布:")
    for s, c in sorted(scenario_counts.items(), key=lambda x: -x[1]):
        print(f"  {s}: {c}")


if __name__ == "__main__":
    main()
