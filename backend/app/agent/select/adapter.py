"""Adapters bridging GroundingResult candidates to CandidateParcel objects."""

from __future__ import annotations

from app.modules.schema import DLBM_TO_DLMC
from app.modules.schema.contracts.grounding_contracts import CandidateSite, GroundingResult
from app.modules.spatial_ops.selection import CandidateParcel


def candidate_site_to_parcels(site: CandidateSite, parcel_by_bsm: dict[str, object]) -> list[CandidateParcel]:
    parcels = []
    for bsm in site.source_parcels:
        parcel = parcel_by_bsm.get(str(bsm))
        if parcel is None:
            continue
        parcels.append(
            CandidateParcel(
                bsm=str(bsm),
                geometry=getattr(parcel, "geometry", {}),
                dlbm=getattr(parcel, "dlbm", ""),
                dlmc=DLBM_TO_DLMC.get(getattr(parcel, "dlbm", ""), ""),
                area_ha=(getattr(parcel, "area_sqm", 0.0) or 0.0) / 10000.0,
                target_ref=(getattr(site, "target_ref", None) or ""),
            )
        )
    return parcels


def filter_parcels_for_target(parcels: list[CandidateParcel], target_ref: str) -> list[CandidateParcel]:
    """Keep parcels tagged for ``target_ref`` plus any untargeted parcels.

    Untargeted parcels (``target_ref == ""``) remain eligible for every project
    so placement still works when grounding has not yet tagged a candidate.
    """
    return [
        p for p in parcels
        if p.target_ref == target_ref or p.target_ref == ""
    ]


def grounding_to_candidate_parcels(result: GroundingResult, bundle) -> list[CandidateParcel]:
    parcel_by_bsm = {}
    for p in (bundle.polygons.get("landuse_current") or []):
        parcel_by_bsm[str(p.bsm)] = p
    parcels = []
    for site in result.candidates:
        parcels.extend(candidate_site_to_parcels(site, parcel_by_bsm))
    return parcels
