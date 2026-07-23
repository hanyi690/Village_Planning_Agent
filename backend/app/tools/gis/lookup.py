"""Tool: lookup_land_use_code — land-use name → GHYTBM standard codes.

Split from parse_tools.py during Phase C refactor.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from pydantic import BaseModel

from app.utils.logger import get_logger
from app.tools.helpers import make_result

logger = get_logger(__name__)




class GHYTBMMatch(BaseModel):
    """A single GHYTBM (planning use code) match entry."""

    ghytbm: str = ""
    ghytmc: str = ""
    zone_type: str = ""
    vne_code: str = ""


class DLBMMatch(BaseModel):
    """A single DLBM (current land-use code) match entry."""

    dlbm: str = ""
    dlmc: str = ""
    zone_type: str = ""


class GHFLBMMatch(BaseModel):
    """A single GHFLBM (planning classification) match entry."""

    ghflbm: str = ""
    ghytbm: str = ""
    ghytmc: str = ""


class LandUseCodeLookup(BaseModel):
    """Typed result for lookup_land_use_code - replaces raw dict.

    Encodes the name -> multi-system-code lookup result as typed models
    so the tool's output structure is guaranteed consistent and validated.
    Serialized via model_dump() into make_result()'s data field.
    """

    ghytbm: str = ""
    ghytmc: str = ""
    ghflbm: str = ""
    vne_code: str = ""
    dlbm_aliases: List[str] = []
    zone_type: str = ""
    candidates_ghytbm: List[GHYTBMMatch] = []
    candidates_dlbm: List[DLBMMatch] = []


@tool
def lookup_land_use_code(land_use_name: str) -> Dict[str, Any]:
    """Look up standard land-use codes for a given land-use name.

    Queries DictionaryCenter YAML dictionaries (dlbm.yaml, ghtybm.yaml).
    Does NOT auto-convert between encoding systems — only returns lookup results
    and candidate suggestions for human confirmation.

    Args:
        land_use_name: Chinese land-use name (e.g., "经营性建设用地", "宅基地")

    Returns:
        Dict with matching codes: ghytbm, ghflbm, vne_code, dlbm_aliases, candidates.
    """
    try:
        from app.modules.gis.schema import (
            GHYTBM_TO_GHYTMC,
            GHYTBM_TO_ZONE_TYPE,
            GHYTBM_TO_VNE,
            GHFLBM_TO_GHYTBMS,
            DLBM_TO_DLMC,
            DLBM_TO_ZONE_TYPE,
        )

        # Search in GHYTBM names (planning use codes) - typed matches
        ghytbm_matches: List[GHYTBMMatch] = []
        for code, name in GHYTBM_TO_GHYTMC.items():
            if land_use_name in name or name in land_use_name:
                ghytbm_matches.append(GHYTBMMatch(
                    ghytbm=code,
                    ghytmc=name,
                    zone_type=GHYTBM_TO_ZONE_TYPE.get(code, ""),
                    vne_code=GHYTBM_TO_VNE.get(code, ""),
                ))

        # Search in DLBM names (current land-use codes) - typed matches
        dlbm_matches: List[DLBMMatch] = []
        for code, name in DLBM_TO_DLMC.items():
            if land_use_name in name or name in land_use_name:
                dlbm_matches.append(DLBMMatch(
                    dlbm=code,
                    dlmc=name,
                    zone_type=DLBM_TO_ZONE_TYPE.get(code, ""),
                ))

        # Search in GHFLBM (planning classification) - typed matches
        ghflbm_matches: List[GHFLBMMatch] = []
        for code, ghytbms in GHFLBM_TO_GHYTBMS.items():
            for ghytbm in ghytbms:
                name = GHYTBM_TO_GHYTMC.get(ghytbm, "")
                if land_use_name in name or name in land_use_name:
                    ghflbm_matches.append(GHFLBMMatch(
                        ghflbm=code,
                        ghytbm=ghytbm,
                        ghytmc=name,
                    ))
                    break

        if not ghytbm_matches and not dlbm_matches:
            lookup = LandUseCodeLookup(
                candidates_ghytbm=ghytbm_matches[:5],
                candidates_dlbm=dlbm_matches[:5],
            )
            return make_result(
                success=False,
                error=f"No code found for '{land_use_name}'",
                data=lookup.model_dump(),
            )

        # Primary match (first GHYTBM match is preferred)
        primary = ghytbm_matches[0] if ghytbm_matches else GHYTBMMatch()
        primary_dlbm = dlbm_matches[0] if dlbm_matches else DLBMMatch()

        lookup = LandUseCodeLookup(
            ghytbm=primary.ghytbm,
            ghytmc=primary.ghytmc,
            ghflbm=ghflbm_matches[0].ghflbm if ghflbm_matches else "",
            vne_code=primary.vne_code,
            dlbm_aliases=[m.dlbm for m in dlbm_matches],
            zone_type=primary.zone_type or primary_dlbm.zone_type,
            candidates_ghytbm=ghytbm_matches[:5],
            candidates_dlbm=dlbm_matches[:5],
        )

        return make_result(success=True, data=lookup.model_dump())
    except Exception as e:
        logger.warning("[lookup_land_use_code] Failed: %s", e)
        return make_result(success=False, error=str(e))


__all__ = ["lookup_land_use_code"]
