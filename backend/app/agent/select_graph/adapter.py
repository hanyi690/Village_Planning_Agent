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
            )
        )
    return parcels


def grounding_to_candidate_parcels(result: GroundingResult, bundle) -> list[CandidateParcel]:
    parcel_by_bsm = {}
    for p in (bundle.polygons.get("landuse_current") or []):
        parcel_by_bsm[str(p.bsm)] = p
    parcels = []
    for site in result.candidates:
        parcels.extend(candidate_site_to_parcels(site, parcel_by_bsm))
    return parcels
