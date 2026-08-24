"""Dimension-specific semantic contracts shared by L1 and L3 prompts.

The model is not asked to turn every dimension into a facility or parcel.  A
dimension contract declares which observations are useful at L1 and which
planning families may be proposed at L3.  The deterministic compilers still
validate the returned objects; this module only supplies the semantic scope
that prevents one generic prompt from flattening unrelated dimensions.
"""

from __future__ import annotations

from typing import Any


_DEFAULT = {
    "l1_observation_kinds": [
        "place", "current_asset", "demand", "metric", "constraint",
        "relation", "risk", "opportunity", "document_observation",
    ],
    "l1_required_evidence": ["source_segment_ids", "source_quote"],
    "l3_claim_families": ["evidence_statement", "objective", "constraint", "action"],
    "l3_grounding_requirements": ["place_binding", "candidate_geometry"],
    "spatial_authority": "L1 facts and explicit GIS evidence only; no name-only location inference",
}


_CONTRACTS: dict[str, dict[str, Any]] = {
    "location": {
        "l1_observation_kinds": ["place", "relation", "current_asset", "metric", "document_observation"],
        "l3_claim_families": ["evidence_statement", "constraint", "objective", "axis", "road"],
        "l3_grounding_requirements": ["place_binding", "network_snapshot"],
        "focus": "行政区、自然村、道路、水系和对外联系的身份、别名、方向和关系；不把地点名本身变成规划项目。",
    },
    "socio_economic": {
        "l1_observation_kinds": ["metric", "current_asset", "demand", "place", "constraint", "opportunity", "document_observation"],
        "l3_claim_families": ["indicator", "objective", "project_package", "facility", "site_area", "action"],
        "l3_grounding_requirements": ["place_binding", "demand_points", "candidate_geometry"],
        "focus": "人口、户数、产业、就业和服务需求；没有空间证据时只产指标或需求，不生成点位。",
    },
    "villager_wishes": {
        "l1_observation_kinds": ["demand", "place", "constraint", "opportunity", "document_observation"],
        "l3_claim_families": ["objective", "project_package", "facility", "road", "site_area", "action"],
        "l3_grounding_requirements": ["place_binding", "demand_points", "candidate_geometry"],
        "focus": "村民诉求、受益对象、紧迫性和位置线索；诉求不是现状资产，位置不明确则保留为需求或待核验。",
    },
    "superior_planning": {
        "l1_observation_kinds": ["metric", "constraint", "place", "relation", "document_observation"],
        "l3_claim_families": ["indicator", "constraint", "objective", "action"],
        "l3_grounding_requirements": ["place_binding", "topology"],
        "focus": "法定指标、政策约束、期限和适用范围；不得把政策条文直接当作地块或几何。",
    },
    "natural_environment": {
        "l1_observation_kinds": ["place", "current_asset", "constraint", "risk", "metric", "relation", "document_observation"],
        "l3_claim_families": ["constraint", "protection", "restoration", "zone", "site_area", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "topology", "parcel_membership"],
        "focus": "地形、水系、灾害、生态敏感性和保护边界；保护/避让优先，不能把风险描述默认为建设候选。",
    },
    "land_use": {
        "l1_observation_kinds": ["current_asset", "metric", "constraint", "place", "relation", "document_observation"],
        "l3_claim_families": ["indicator", "constraint", "zone", "site_area", "protection", "restoration"],
        "l3_grounding_requirements": ["parcel_membership", "candidate_geometry", "topology"],
        "focus": "现状地类、面积、权属/适宜性和管控边界；现状地类不等于规划地类，整块与部分占用必须分开。",
    },
    "traffic": {
        "l1_observation_kinds": ["current_asset", "place", "relation", "metric", "constraint", "risk", "document_observation"],
        "l3_claim_families": ["road", "axis", "constraint", "objective", "action"],
        "l3_grounding_requirements": ["network_snapshot", "place_binding", "candidate_geometry", "parcel_membership"],
        "focus": "现状道路、等级、宽度、通行问题、端点和网络关系；道路规划必须提供 typed endpoint/alignment 线索，不能复制现状线。",
    },
    "public_services": {
        "l1_observation_kinds": ["current_asset", "demand", "metric", "place", "relation", "constraint", "document_observation"],
        "l3_claim_families": ["facility", "site_area", "objective", "action"],
        "l3_grounding_requirements": ["demand_points", "candidate_geometry", "network_snapshot", "parcel_membership"],
        "focus": "设施类型、现状能力、服务半径、服务对象和缺口；coverage 需要明确 demand points，人口总数不能直接充当空间需求点。",
    },
    "infrastructure": {
        "l1_observation_kinds": ["current_asset", "demand", "place", "relation", "metric", "constraint", "risk", "document_observation"],
        "l3_claim_families": ["road", "facility", "site_area", "constraint", "action"],
        "l3_grounding_requirements": ["network_snapshot", "place_binding", "candidate_geometry", "parcel_membership"],
        "focus": "给排水、电力、通信和设施网络的现状、缺口、端点与服务关系；线性工程必须保持线性资产类型。",
    },
    "ecological_green": {
        "l1_observation_kinds": ["current_asset", "place", "relation", "metric", "constraint", "risk", "document_observation"],
        "l3_claim_families": ["protection", "restoration", "zone", "site_area", "constraint", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "topology", "parcel_membership"],
        "focus": "生态斑块、廊道、绿地和保护约束；functional overlay、protection 和 restoration 必须区分。",
    },
    "architecture": {
        "l1_observation_kinds": ["current_asset", "place", "relation", "metric", "constraint", "risk", "document_observation"],
        "l3_claim_families": ["site_area", "protection", "restoration", "action", "constraint"],
        "l3_grounding_requirements": ["candidate_geometry", "parcel_membership", "place_binding"],
        "focus": "建筑质量、风貌、界面和改造对象；建筑描述不能直接生成建设地块。",
    },
    "historical_culture": {
        "l1_observation_kinds": ["current_asset", "place", "relation", "constraint", "metric", "document_observation"],
        "l3_claim_families": ["protection", "restoration", "zone", "site_area", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "topology", "parcel_membership", "place_binding"],
        "focus": "文保单位、传统建筑、历史路径及保护级别；保护对象身份和范围要有来源，不因文化描述泛化成整村禁建。",
    },
    "industry": {
        "l3_claim_families": ["objective", "project_package", "facility", "site_area", "zone", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "parcel_membership", "demand_points", "place_binding"],
        "focus": "产业项目、服务节点和用地需求；只有 L1/L2 证据支持的产业类型、规模和位置才能进入空间 claim。",
    },
    "spatial_structure": {
        "l3_claim_families": ["objective", "axis", "zone", "protection", "restoration", "site_area"],
        "l3_grounding_requirements": ["topology", "candidate_geometry", "parcel_membership", "place_binding"],
        "focus": "节点、轴线、功能结构和保护关系；功能 overlay 不等于地类分配，拓扑关系必须显式声明。",
    },
    "land_use_planning": {
        "l3_claim_families": ["objective", "zone", "site_area", "protection", "restoration", "constraint"],
        "l3_grounding_requirements": ["parcel_membership", "candidate_geometry", "topology"],
        "focus": "地类分配、功能叠加、保护/修复和面积约束；整块/部分占用和切割后的剩余地块必须由 GROUND 保留。",
    },
    "settlement_planning": {
        "l3_claim_families": ["objective", "site_area", "facility", "protection", "restoration", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "parcel_membership", "place_binding", "network_snapshot"],
        "focus": "居民点整治、公共节点和空间联系；不从自然村名单直接推导设施或搬迁地块。",
    },
    "traffic_planning": {
        "l3_claim_families": ["road", "axis", "objective", "constraint", "action"],
        "l3_grounding_requirements": ["network_snapshot", "place_binding", "candidate_geometry", "parcel_membership"],
        "focus": "道路/线性工程的中心线语义、端点、对齐关系和新增占地要求；道路不重复生成 site_area。",
    },
    "public_service": {
        "l3_claim_families": ["facility", "site_area", "objective", "project_package", "action"],
        "l3_grounding_requirements": ["demand_points", "candidate_geometry", "network_snapshot", "parcel_membership"],
        "focus": "设施类型、容量、服务半径与需求点的覆盖关系；缺 demand points 时保持 diagnostic-only。",
    },
    "infrastructure_planning": {
        "l3_claim_families": ["road", "facility", "site_area", "objective", "constraint", "action"],
        "l3_grounding_requirements": ["network_snapshot", "place_binding", "candidate_geometry", "parcel_membership"],
        "focus": "给排水、电力、通信和基础设施网络；线性资产必须声明端点/网络引用，面状设施必须声明用地需求。",
    },
    "ecological": {
        "l3_claim_families": ["protection", "restoration", "zone", "site_area", "objective", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "topology", "parcel_membership"],
        "focus": "生态保护、修复、廊道和功能叠加；不把生态叙述自动转成 parcel assignment。",
    },
    "disaster_prevention": {
        "l3_claim_families": ["protection", "restoration", "road", "facility", "constraint", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "topology", "network_snapshot", "place_binding"],
        "focus": "灾害避让、应急通道和安全设施；风险点是约束/证据，不能未经核验成为建设点。",
    },
    "heritage": {
        "l3_claim_families": ["protection", "restoration", "zone", "site_area", "constraint", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "topology", "parcel_membership", "place_binding"],
        "focus": "文保对象、保护范围和修缮项目；保护边界与项目 footprint 需分别表达。",
    },
    "landscape": {
        "l3_claim_families": ["site_area", "facility", "protection", "restoration", "zone", "action"],
        "l3_grounding_requirements": ["candidate_geometry", "parcel_membership", "place_binding"],
        "focus": "风貌整治、公共空间和界面控制；描述性风貌要求没有地块证据时只保留为 overlay 或 action。",
    },
    "project_bank": {
        "l3_claim_families": ["project_package", "facility", "road", "axis", "site_area", "zone", "protection", "restoration", "action"],
        "l3_grounding_requirements": ["place_binding", "candidate_geometry", "demand_points", "parcel_membership", "network_snapshot", "topology"],
        "focus": "跨维度项目包的去重、目标身份、来源、阶段和执行所需输入；不得为了填满项目库复制同一目标或补造空间位置。",
    },
}


def get_dimension_semantic_contract(dimension_key: str, layer: int = 1) -> dict[str, Any]:
    """Return a copy so prompt construction cannot mutate the catalog."""

    contract = dict(_DEFAULT)
    contract.update(_CONTRACTS.get(str(dimension_key or "").strip(), {}))
    contract["dimension_key"] = str(dimension_key or "").strip()
    contract["layer"] = int(layer)
    if int(layer) == 3 and not contract.get("focus"):
        contract["focus"] = "规划目标必须回指 L1/L2 证据，空间落位交由 GROUND。"
    return {
        key: list(value) if isinstance(value, list) else value
        for key, value in contract.items()
    }


def render_dimension_semantic_contract(dimension_key: str, layer: int = 1) -> str:
    contract = get_dimension_semantic_contract(dimension_key, layer)
    return (
        f"【{dimension_key} L{layer} 维度语义契约】\n"
        f"关注：{contract.get('focus', '')}\n"
        f"允许的 L1 observation_kind：{', '.join(contract['l1_observation_kinds'])}\n"
        f"允许的 L3 claim family：{', '.join(contract['l3_claim_families'])}\n"
        f"GROUND 必要输入：{', '.join(contract['l3_grounding_requirements'])}\n"
        f"证据边界：{contract['spatial_authority']}"
    )


__all__ = ["get_dimension_semantic_contract", "render_dimension_semantic_contract"]
