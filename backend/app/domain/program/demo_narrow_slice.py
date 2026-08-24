"""Explicit demo-only planning slice used to prove the spatial execution path.

The normal L3 provider remains the authority for user planning claims.  This
fixture is opt-in: it is activated only by a task marker carrying a real
source parcel BSM and a requested footprint.  It never supplies geometry;
GROUND must resolve the BSM from the current DataCatalog and still apply all
availability, constraint, and adjacency checks.
"""

from __future__ import annotations

import re
from typing import Any

from app.contracts.domain.planning_semantics import SiteAreaPlanningParameters
from app.contracts.program import PlanningClaim


_MARKER = "[SPATIAL_DEMO_NARROW_SLICE"
_MARKER_RE = re.compile(r"\[SPATIAL_DEMO_NARROW_SLICE([^\]]*)\]")
_PARAM_RE = re.compile(r"([a-z0-9_]+)\s*=\s*([^;\]\s]+)")


def _build_claim_from_values(values: dict[str, str], ordinal: int) -> PlanningClaim | None:
    bsm = str(values.get("source_parcel_bsm") or "").strip()
    site_type = str(values.get("site_type") or "防灾疏散场地").strip()
    try:
        footprint = float(values.get("footprint_area_m2") or 300)
    except (TypeError, ValueError):
        footprint = 300.0
    if not bsm.isdigit() or footprint <= 0:
        return None
    footprint_ha = footprint / 10000.0
    claim_suffix = f":{ordinal}" if ordinal else ""
    return PlanningClaim(
        claim_id=f"demo:narrow-slice:{bsm}:{int(footprint)}{claim_suffix}",
        dimension_key="implementation",
        statement=(
            f"在现状 GIS 地块 BSM={bsm} 内落地{site_type}，"
            f"规划占地约 {footprint:g} 平方米；保留地块未占用部分并记录邻接地块。"
        ),
        planning_role="spatial_intervention",
        project_package_ref=f"demo:jintian:{bsm}:{int(footprint)}",
        location_hints=[f"BSM={bsm}"],
        affected_parcel_refs=[bsm],
        suggested_category="site_area",
        suggested_output_kind="parcel",
        asset_kind="none",
        suggested_interventions=[site_type],
        quantity=footprint,
        quantity_unit="平方米",
        area_range_ha=(footprint_ha, footprint_ha),
        intervention_action="new",
        materialization_role="site_footprint",
        site_area_parameters=SiteAreaPlanningParameters(
            site_type=site_type,
            action="new",
            footprint_area_m2=footprint,
        ),
        constraint_refs=[
            "避让永久基本农田",
            "避让生态保护红线",
            "避让历史文化保护要素",
        ],
        objective_refs=["demo_narrow_slice_grounded_execution"],
        evidence_refs=[f"bundle:landuse_current:{bsm}"],
        source_refs=[f"bundle:landuse_current:{bsm}"],
        confidence=1.0,
    )


def build_demo_narrow_slice_claims(task_description: str) -> list[PlanningClaim]:
    """Build all explicitly typed demo claims in the task text.

    Repeated markers are useful for a real multi-target acceptance run: every
    claim still carries its own BSM and footprint, while GROUND remains the
    only producer of geometry.  A malformed marker is ignored rather than
    widened into an executable target.
    """
    text = str(task_description or "")
    claims: list[PlanningClaim] = []
    for ordinal, match in enumerate(_MARKER_RE.finditer(text)):
        values = {key: value for key, value in _PARAM_RE.findall(match.group(1))}
        claim = _build_claim_from_values(values, ordinal)
        if claim is not None:
            claims.append(claim)
    return claims


def build_demo_narrow_slice_claim(task_description: str) -> PlanningClaim | None:
    """Build the first explicitly typed demo claim for existing callers."""
    claims = build_demo_narrow_slice_claims(task_description)
    return claims[0] if claims else None


def task_description_from_state(state: dict[str, Any]) -> str:
    """Read task text from the state without making it a new authority."""
    direct = str(state.get("task_description") or "").strip()
    if direct:
        return direct
    input_texts = state.get("input_texts")
    if isinstance(input_texts, dict):
        value = str(input_texts.get("task_description") or "").strip()
        if value:
            return value
    config = state.get("config")
    if isinstance(config, dict):
        value = str(config.get("task_description") or "").strip()
        if value:
            return value
    return ""


__all__ = [
    "build_demo_narrow_slice_claim",
    "build_demo_narrow_slice_claims",
    "task_description_from_state",
]
