from typing import Iterable, Optional

from app.modules.schema.advisory_crosswalks import DLBM_TO_GHYTBM, GHYTBM_TO_ZONE_TYPE
from app.modules.schema.advisory_crosswalks.legacy import require_legacy
from app.modules.schema.encodings import code_sets as cs
from app.modules.schema.provenance import ProvenanceSource


def derive_zone_types(
    parcels: Iterable[dict],
    *,
    dlbm_key: str = "dlbm",
    ghytbm_key: str = "ghytbm",
    current_landuse_key: str = "current_landuse_code",
    bsm_key: str = "bsm",
) -> dict[str, dict]:
    """Derive zone_type (5-tier) and zone_type_sub (8-class) for each parcel.

    Inputs are plain dicts (parcel-shaped). Priority:
    1. ``current_landuse_code`` (appendix5 广东实践)
    2. ``ghytbm`` (already known)
    3. ``dlbm`` (GB/T 21010) → DLBM_TO_GHYTBM lookup

    Returns ``{bsm: {ghytbm, ghytmc, zone_type, zone_type_sub, encoding_provenance}}``.
    When no encoding can be resolved the parcel gets ``encoding_provenance='missing:upper_plan_transmission'``
    and ``zone_type=None``.
    """
    require_legacy("derive_zone_types")
    out: dict[str, dict] = {}
    for p in parcels:
        bsm = p[bsm_key]
        ghytbm = _resolve_ghytbm(p, dlbm_key, ghytbm_key, current_landuse_key)
        if ghytbm:
            zone_type = GHYTBM_TO_ZONE_TYPE.get(ghytbm)
            ghytmc = cs.GHYTBM_TO_GHYTMC.get(ghytbm, ghytbm)
            prov = _provenance_for(p, ghytbm, dlbm_key, current_landuse_key)
        else:
            zone_type = None
            ghytmc = None
            prov = ProvenanceSource.MISSING_UPPER_PLAN.value
        out[bsm] = {
            "ghytbm": ghytbm,
            "ghytmc": ghytmc,
            "zone_type": zone_type,
            "zone_type_sub": ghytmc,
            "encoding_provenance": prov,
        }
    return out


def _resolve_ghytbm(p: dict, dlbm_key: str, ghytbm_key: str, current_landuse_key: str) -> Optional[str]:
    clu = p.get(current_landuse_key)
    if clu:
        return clu
    gh = p.get(ghytbm_key)
    if gh:
        return gh
    dlbm = p.get(dlbm_key)
    if dlbm and dlbm in DLBM_TO_GHYTBM:
        return DLBM_TO_GHYTBM[dlbm]
    return None


def _provenance_for(p: dict, ghytbm: str, dlbm_key: str, current_landuse_key: str) -> str:
    if p.get(current_landuse_key):
        return ProvenanceSource.PRACTICAL_APPENDIX5.value
    if p.get(ghytbm_key := "ghytbm"):
        return ProvenanceSource.PRACTICAL_APPENDIX5.value
    if p.get(dlbm_key) and ghytbm:
        return ProvenanceSource.DERIVED_DLBM_TO_GHYTBM.value
    return ProvenanceSource.DERIVED_DLBM_TO_ZONE_TYPE.value