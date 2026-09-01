"""Read dimension semantic and evidence boundaries from the YAML registry."""

from __future__ import annotations

from typing import Any


def _config(dimension_key: str, config: Any | None = None) -> Any:
    from app.config.loader import get_dimension_config

    if config is not None and getattr(config, "semantic", None) is not None:
        return config
    if config is not None and getattr(config, "evidence", None) is not None:
        evidence = getattr(config, "evidence")
        if getattr(evidence, "entity_scope", None):
            return config
    resolved = get_dimension_config(str(dimension_key or "").strip())
    if resolved is None:
        raise KeyError(f"unknown dimension: {dimension_key!r}")
    return resolved


def get_dimension_entity_scope(dimension_key: str, config: Any | None = None) -> list[str]:
    """Return the YAML-owned coarse entity families for retrieval."""

    resolved = _config(dimension_key, config)
    values = getattr(getattr(resolved, "evidence", None), "entity_scope", ()) or ()
    result = list(dict.fromkeys(str(value).strip() for value in values if str(value).strip()))
    if not result:
        raise ValueError(f"dimension {dimension_key!r} has no evidence.entity_scope")
    return result


def get_dimension_semantic_contract(
    dimension_key: str,
    layer: int = 1,
    config: Any | None = None,
) -> dict[str, Any]:
    """Return the YAML-owned semantic contract without a Python fallback."""

    resolved = _config(dimension_key, config)
    semantic = getattr(resolved, "semantic", None)
    if semantic is None:
        raise ValueError(f"dimension {dimension_key!r} has no semantic contract")
    values = semantic.model_dump() if hasattr(semantic, "model_dump") else dict(semantic)
    required = ("focus", "l1_fact_types", "l3_claim_families", "l3_grounding_requirements", "spatial_authority")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError(f"dimension {dimension_key!r} semantic contract missing: {', '.join(missing)}")
    result = {
        key: list(dict.fromkeys(value)) if isinstance(value, list) else value
        for key, value in values.items()
    }
    result["dimension_key"] = str(dimension_key or "").strip()
    result["layer"] = int(layer)
    return result


def render_dimension_semantic_contract(
    dimension_key: str,
    layer: int = 1,
    *,
    upstream_source_dimensions: list[str] | None = None,
    config: Any | None = None,
) -> str:
    contract = get_dimension_semantic_contract(dimension_key, layer, config)
    rendered = (
        f"【{dimension_key} L{layer} 维度语义契约】\n"
        f"关注：{contract['focus']}\n"
        f"允许的 L1 fact_type：{', '.join(contract['l1_fact_types'])}\n"
        f"允许的 L3 claim family：{', '.join(contract['l3_claim_families'])}\n"
        f"GROUND 必要输入：{', '.join(contract['l3_grounding_requirements'])}\n"
        f"证据边界：{contract['spatial_authority']}\n"
        f"源段范围：{', '.join(contract.get('source_section_hints', [])) or '未指定；保持证据缺口'}\n"
        "地点覆盖：只抽取本维度相关且在输入中明确出现的空间对象；每个事实使用"
        "扁平 place_names/location_role/location_relation 列保留名称、角色和关系。"
        "地点列没有坐标权威时由本地投影标记 needs_retrieval，"
        "由 EvidenceGraph 使用 Bundle/KG 候选补足，不能在 L1 猜坐标或边界。"
    )
    if upstream_source_dimensions:
        rendered += "\n上游 source_dimensions：" + ", ".join(
            str(value) for value in upstream_source_dimensions if str(value).strip()
        )
    return rendered


__all__ = [
    "get_dimension_entity_scope",
    "get_dimension_semantic_contract",
    "render_dimension_semantic_contract",
]
