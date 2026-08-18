"""Deterministic demand derivation from typed planning intent."""

from __future__ import annotations

from typing import Iterable

from app.domain.demand.model import DemandItem, DemandPortfolio


def _targets(intent: object, field: str) -> Iterable[object]:
    value = intent.get(field) if isinstance(intent, dict) else getattr(intent, field, ())
    return tuple(value or ())


def derive_demand_portfolio(
    intent: object,
    *,
    claims: Iterable[object] = (),
) -> DemandPortfolio:
    """Derive what is required without reading or ranking any parcel."""

    claim_items = tuple(claims) or tuple(getattr(intent, "claims", ()) or ())
    claims_by_id = {
        str(getattr(claim, "claim_id", "")): claim
        for claim in claim_items
        if str(getattr(claim, "claim_id", ""))
    }
    demands: list[DemandItem] = []
    seen: set[str] = set()
    for field, kind in (
        ("site_area_targets", "site_area"),
        ("facilities", "facility"),
        ("road_targets", "road"),
        ("linear_targets", "linear"),
        ("development_axes", "axis"),
        ("zone_targets", "zone"),
        ("custom_zone_targets", "zone"),
    ):
        for target in _targets(intent, field):
            target_id = str(getattr(target, "target_id", "") or "").strip()
            if not target_id or target_id in seen:
                continue
            seen.add(target_id)
            output_kind = str(getattr(target, "expected_output_kind", "parcel") or "parcel")
            quantity = None
            quantity_unit = ""
            for name, unit in (("area_ha", "ha"), ("area_ratio", "ratio"), ("width_m", "m")):
                value = getattr(target, name, None)
                if value is not None:
                    quantity = float(value)
                    quantity_unit = unit
                    break
            evidence_refs = [
                str(value)
                for value in (
                    getattr(target, "source_report_key", ""),
                    getattr(target, "source_instruction_id", ""),
                )
                if str(value).strip()
            ]
            claim_refs = [str(value) for value in (getattr(target, "claim_refs", ()) or []) if str(value)]
            for claim_ref in claim_refs:
                claim = claims_by_id.get(claim_ref)
                if claim is None:
                    continue
                evidence_refs.extend(str(value) for value in (claim.evidence_refs or []) if str(value))
            claim_requirements = {
                "claim_refs": claim_refs,
                "location_hints": [
                    hint
                    for claim_ref in claim_refs
                    for hint in (getattr(claims_by_id.get(claim_ref), "location_hints", ()) or [])
                ],
            }
            demands.append(
                DemandItem(
                    demand_id=f"demand:{target_id}",
                    target_id=target_id,
                    kind=kind,
                    geometry_kind=output_kind,
                    quantity=quantity,
                    quantity_unit=quantity_unit,
                    phase="short",
                    claim_refs=list(dict.fromkeys(claim_refs)),
                    evidence_refs=evidence_refs,
                    spatial_requirements={
                        **dict(getattr(target, "semantic", None).model_dump() if getattr(target, "semantic", None) is not None else {}),
                        **claim_requirements,
                    },
                )
            )
    return DemandPortfolio(demands=demands)


__all__ = ["derive_demand_portfolio"]
