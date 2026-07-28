"""KG query subpackage - four-namespace query API (v4.8).

[v4.8] Queries organized into four namespaces by consumer:
  analysis_queries  - for analysis (report generation), coarse-grained, semantic-only
  parse_queries     - for PARSE (intent compilation), fine-grained, structured + L3 writes
  execute_queries   - for EXECUTE (execution), L4 read/write, constraint verification (RESERVED)
  shared_queries    - cross-stage utilities

Files:
  sparql.py     - SPARQL template registry (QUERY_TEMPLATES) + query_kg() + instance methods
  semantic.py   - LLM-friendly semantic queries (human-readable descriptions)
  cognition.py  - three-layer cognition summary (get_village_cognition)
  contracts.py  - DualPayload + TokenBudget + TopKSampler
"""
from .sparql import (
    QUERY_TEMPLATES, query_kg, TOOL_META,
    query, get_adjacency_map,
    get_parcel_count, get_triple_count, serialize, to_turtle, from_turtle,
    get_parcels_within_distance_of_entity, get_adjacent_parcels_with_length,
    get_connected_parcels, get_parcels_by_bsm_list, validate_intent,
    _is_in_protected_zone, get_constraint_coverage,
)
from .semantic import (
    get_entity_context, get_entity_relations,
    get_parcel_semantic_context, get_village_semantic_summary,
    get_entity_by_bsm, get_parcels_by_planning_zone,
    get_l4_derived_from_l1, get_village_constraint_coverage,
    get_entity_semantics,
    TOOL_META_SEMANTIC,
)
from .cognition import get_village_cognition, get_layer_group_semantics
from .contracts import DualPayload, TokenBudget, TopKSampler


# ============================================================
# v4.8 - Four-namespace query API
# ============================================================

# ── analysis_queries: for analysis (report generation) ──
# Coarse-grained, semantic-only (no BSM-level detail), read-only
analysis_queries = {
    "get_village_cognition": {
        "func": get_village_cognition,
        "description": "三层认知摘要（村概览/图层卡/约束简报），供 analysis 报告生成用",
        "returns": "DualPayload",
        "writes_kg": False,
    },
    "get_layer_group_semantics": {
        "func": get_layer_group_semantics,
        "description": "单个图层组详情（数量/主导标签/分布），供 analysis 按图层叙述",
        "returns": "DualPayload",
        "writes_kg": False,
    },
    "get_village_semantic_summary": {
        "func": get_village_semantic_summary,
        "description": "村庄语义摘要（实体计数/关系计数/规划分区分布）",
        "returns": "Dict",
        "writes_kg": False,
    },
    "get_village_constraint_coverage": {
        "func": get_village_constraint_coverage,
        "description": "约束覆盖摘要（哪些地块与保护红线重叠）",
        "returns": "List[Dict]",
        "writes_kg": False,
    },
}

# ── parse_queries: for PARSE (intent compilation) ──
# Fine-grained, structured (BSM-level), writes L3
parse_queries = {
    "get_parcel_detail": {
        "func": lambda kg, **kw: get_entity_context(kg, kw.get("entity_uri", "")),
        "description": "单地块详情（属性+关系+注解），供 PARSE 锚定用",
        "returns": "Dict",
        "writes_kg": False,
    },
    "get_parcel_neighbors": {
        "func": lambda kg, **kw: get_adjacent_parcels_with_length(kg, kw.get("bsm", "")),
        "description": "地块邻接关系（touches + shared_boundary_length）",
        "returns": "List[Dict]",
        "writes_kg": False,
    },
    "get_parcels_by_zone_type": {
        "func": lambda kg, **kw: query_kg(kg, "get_parcels_by_zone_type", **kw),
        "description": "按地类查询地块集合",
        "returns": "List[Dict]",
        "writes_kg": False,
    },
    "get_entity_semantics": {
        "func": get_entity_semantics,
        "description": "实体语义层（分类层级/法律约束/允许操作/编码桥接），供 PARSE 理解实体含义",
        "returns": "Dict",
        "writes_kg": False,
    },
    "get_entity_by_bsm": {
        "func": get_entity_by_bsm,
        "description": "按 BSM 跨层查找实体（L1/L3/L4）",
        "returns": "Dict",
        "writes_kg": False,
    },
    "build_intent_layer": {
        "func": lambda kg, **kw: kg.build_intent_layer(kw.get("intent")),
        "description": "写入 L3 意图虚拟实体（PARSE 产出 -> KG L3）",
        "returns": "None",
        "writes_kg": True,
    },
}

# ── execute_queries: for EXECUTE (execution) — RESERVED ──
# L4 read/write, constraint verification, conflict detection
# NOTE: These are registered for namespace completeness but NOT yet wired into
# the execute subgraph. Actual integration is a follow-up task.
execute_queries = {
    "get_candidate_parcels_for_layout": {
        "func": None,  # RESERVED - to be implemented
        "description": "[预留] 解析 L3 ZoneTarget 候选 vs L1 地块（重试循环用）",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "reserved",
    },
    "check_conflicts": {
        "func": lambda kg, **kw: kg.check_constraint_violations(),
        "description": "检查规划地块与约束面的冲突（validate 节点重试用）",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_constraint_coverage": {
        "func": lambda kg, **kw: get_constraint_coverage(kg),
        "description": "约束覆盖（替代废弃 get_protected_parcels_detail）",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "verify_constraints": {
        "func": None,  # RESERVED - wraps ConstraintIndex.parcel_in_constraint
        "description": "[预留] 单地块约束检查",
        "returns": "Dict",
        "writes_kg": False,
        "status": "reserved",
    },
    "get_l4_state": {
        "func": lambda kg, **kw: kg.get_plan_changes(kw.get("version", "current")),
        "description": "读取 L4 规划成果状态",
        "returns": "Dict",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_effective_land_use": {
        "func": lambda kg, **kw: kg.get_effective_land_use(kw.get("bsm", "")),
        "description": "L4->L1 回退读取有效地类",
        "returns": "str",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_effective_area_ha": {
        "func": lambda kg, **kw: kg.get_effective_area_ha(kw.get("bsm", "")),
        "description": "L4->L1 回退读取有效面积",
        "returns": "float",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_planned_parcels_in_zone": {
        "func": lambda kg, **kw: kg.get_planned_parcels_in_zone(kw.get("zone_type", "")),
        "description": "按分区查询规划地块",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_l4_derived_from_l1": {
        "func": get_l4_derived_from_l1,
        "description": "L4->L1 溯源审计",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "apply_planned_state": {
        "func": lambda kg, **kw: kg._apply_planned_state(kw.get("planned_state")),
        "description": "[预留] 持久化 L4 规划成果（当前未接入 execute）",
        "returns": "None",
        "writes_kg": True,
        "status": "exists_not_wired",
    },
    "compare_versions": {
        "func": lambda kg, **kw: kg.compare_versions(kw.get("v1", ""), kw.get("v2", "")),
        "description": "版本差异对比（重试循环审计）",
        "returns": "Dict",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "validate_intent": {
        "func": lambda kg, **kw: kg.validate_intent(kw.get("intent", {})),
        "description": "L3 vs L1 设施冲突检测",
        "returns": "Dict",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_facility_locations": {
        "func": lambda kg, **kw: query_kg(kg, "get_facility_locations", **kw),
        "description": "设施位置查询（当前 execute 唯一直接查询）",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "wired",
    },
    "get_road_network": {
        "func": lambda kg, **kw: query_kg(kg, "get_road_network", **kw),
        "description": "道路网络查询",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
    "get_village_anchors": {
        "func": lambda kg, **kw: query_kg(kg, "get_village_anchors", **kw),
        "description": "村庄锚点查询（设施/轴线放置用）",
        "returns": "List[Dict]",
        "writes_kg": False,
        "status": "exists_not_wired",
    },
}

# ── shared_queries: cross-stage utilities ──
shared_queries = {
    "get_entity_by_bsm": {
        "func": get_entity_by_bsm,
        "description": "按 BSM 跨层查找实体",
        "returns": "Dict",
        "writes_kg": False,
    },
    "count_by_zone_type": {
        "func": lambda kg, **kw: query_kg(kg, "count_by_zone_type", **kw),
        "description": "按地类统计",
        "returns": "List[Dict]",
        "writes_kg": False,
    },
    "count_by_vne": {
        "func": lambda kg, **kw: query_kg(kg, "count_by_vne", **kw),
        "description": "按 VNE 分类统计",
        "returns": "List[Dict]",
        "writes_kg": False,
    },
    "get_facility_locations": {
        "func": lambda kg, **kw: query_kg(kg, "get_facility_locations", **kw),
        "description": "设施位置（PARSE + EXECUTE 共用）",
        "returns": "List[Dict]",
        "writes_kg": False,
    },
}


__all__ = [
    # SPARQL templates + query_kg
    "QUERY_TEMPLATES", "query_kg", "TOOL_META",
    # Instance methods
    "query", "get_adjacency_map",
    "get_parcel_count", "get_triple_count", "serialize", "to_turtle", "from_turtle",
    "get_parcels_within_distance_of_entity", "get_adjacent_parcels_with_length",
    "get_connected_parcels", "get_parcels_by_bsm_list", "validate_intent",
    "get_constraint_coverage",
    # Semantic queries
    "get_entity_context", "get_entity_relations",
    "get_parcel_semantic_context", "get_village_semantic_summary",
    "get_entity_by_bsm", "get_parcels_by_planning_zone",
    "get_l4_derived_from_l1", "get_village_constraint_coverage",
    "get_entity_semantics",
    "TOOL_META_SEMANTIC",
    # v4.8 cognition + contracts
    "get_village_cognition", "get_layer_group_semantics",
    "DualPayload", "TokenBudget", "TopKSampler",
    # v4.8 four-namespace API
    "analysis_queries", "parse_queries", "execute_queries", "shared_queries",
]
