"""bundle_overview / spatial_context / spatial_features — session data access.

Semantic-first: these tools return statistics, label distributions and
compact structured payloads — never raw coordinate dumps. The optional
``include_geometry`` flag on spatial_features is the deliberate escape hatch
for EXECUTE / rendering flows that need actual geometry.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Annotated

from langchain_core.tools import tool
from langgraph.prebuilt import InjectedState

from .shared import (
    budget_check,
    group_stats,
    resolve_bundle,
    session_kg,
    simplify_geometry,
    tool_reply,
)


async def bundle_overview_impl(session_id: str) -> Dict[str, Any]:
    """Session-level overview: village, admin, spatial group inventory, docs."""
    bundle = await resolve_bundle(session_id)
    md = bundle.metadata

    overview: Dict[str, Any] = {
        "village_name": bundle.village_name,
        "planning_period": md.planning_period,
        "admin": {
            "province": md.province,
            "city": md.city,
            "county": md.county,
            "township": md.township,
        },
        "crs": md.crs,
        "bbox": md.bbox_wgs84.as_tuple if md.bbox_wgs84 else None,
        "parcel_count": bundle.parcel_count,
        "total_area_ha": round(bundle.total_area_ha, 2) if bundle.total_area_ha else 0.0,
        "spatial_groups": group_stats(bundle),
        "rasters": list(bundle.rasters.all_rasters.keys()),
        "tables": list(bundle.tables.all_tables.keys()),
        "documents": [
            {
                "source": ref.get("source"),
                "name": ref.get("name"),
                "record_id": ref.get("record_id"),
                "locator": ref.get("locator"),
                "content_digest": ref.get("content_digest"),
                "char_count": ref.get("char_count", 0),
            }
            for ref in bundle.documents.document_refs
        ],
        "report_manifest": [
            {
                "layer": ref.get("layer"),
                "dimension_key": ref.get("dimension_key"),
                "report_id": ref.get("report_id"),
                "version": ref.get("version"),
                "summary_available": bool(ref.get("summary")),
            }
            for ref in (bundle.documents.report_refs or [])
        ],
    }
    return budget_check(overview)


@tool
async def bundle_overview(
    session_id: str = "",
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """返回当前会话的空间数据与文本概览。

    包括村庄/行政区/规划期元数据、地块数、空间图层组清单（count/标签分布，
    不含原始坐标）、上传文档清单、L1/L2/L3 报告维度清单。用于了解会话里
    有哪些空间数据、输入文档和报告引用可供后续查询。
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(await bundle_overview_impl(session_id))


async def spatial_context_impl(session_id: str) -> Dict[str, Any]:
    """Spatial cognition: bundle statistics + KG three-layer semantic summary."""
    bundle = await resolve_bundle(session_id)

    payload: Dict[str, Any] = {
        "village_name": bundle.village_name,
        "parcel_count": bundle.parcel_count,
        "total_area_ha": round(bundle.total_area_ha, 2) if bundle.total_area_ha else 0.0,
        "spatial_groups": group_stats(bundle),
    }

    kg = session_kg(session_id)
    if kg is not None:
        try:
            from app.infrastructure.kg.queries.cognition import get_village_cognition

            result = get_village_cognition(kg, bundle.village_name, mode="full")
            payload["kg_cognition"] = {
                "semantic": result.semantic,
                "structured": result.structured,
            }
        except Exception as e:
            payload["kg_cognition_error"] = str(e)
    return budget_check(payload)


@tool
async def spatial_context(
    session_id: str = "",
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """返回会话的空间语义认知摘要。

    结合空间图层统计与知识图谱三层认知（村域概况/地块卡片/约束覆盖），
    全部为语义化摘要与统计，不含原始坐标。供维度分析与空间问答使用。
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(await spatial_context_impl(session_id))


async def spatial_features_impl(
    session_id: str,
    group: str = "",
    include_geometry: bool = False,
    max_features: int = 50,
    simplify: float = 0.0,
) -> Dict[str, Any]:
    """Feature-level access with optional simplified geometry (escape hatch)."""
    bundle = await resolve_bundle(session_id)
    groups = {
        "points": bundle.points,
        "lines": bundle.lines,
        "polygons": bundle.polygons,
    }
    targets = {group: groups[group]} if group in groups else groups

    out: Dict[str, Any] = {}
    for gname, g in targets.items():
        for key in g.keys():
            feats = g.get(key) or []
            if not feats:
                continue
            selected = feats[: max(1, max_features)]
            entries = []
            for f in selected:
                entry: Dict[str, Any] = {
                    "bsm": getattr(f, "bsm", ""),
                    "layer_type": getattr(f, "layer_type", ""),
                    "dlbm": getattr(f, "dlbm", ""),
                    "zone_type": getattr(f, "zone_type", ""),
                }
                if include_geometry:
                    entry["geometry"] = simplify_geometry(getattr(f, "geometry", None), simplify)
                entries.append(entry)
            out.setdefault(gname, {})[key] = {
                "count": len(feats),
                "shown": len(entries),
                "features": entries,
            }
    return budget_check(out)


@tool
async def spatial_features(
    session_id: str = "",
    group: str = "",
    include_geometry: bool = False,
    max_features: int = 50,
    simplify: float = 0.0,
    state: Annotated[Optional[Dict[str, Any]], InjectedState()] = None,
) -> str:
    """返回空间要素清单（默认不含坐标，仅 BSM/图层/地类）。

    按图层组（points/lines/polygons）列出要素元数据。仅当
    ``include_geometry=true`` 时返回几何，可用 ``simplify``（0..1）抽样精简
    以控制体积，供落图/EXECUTE 使用。
    """
    if not session_id and state:
        session_id = state.get("session_id", "")
    return tool_reply(
        await spatial_features_impl(
            session_id,
            group=group,
            include_geometry=include_geometry,
            max_features=max_features,
            simplify=simplify,
        )
    )


__all__ = [
    "bundle_overview",
    "bundle_overview_impl",
    "spatial_context",
    "spatial_context_impl",
    "spatial_features",
    "spatial_features_impl",
]
