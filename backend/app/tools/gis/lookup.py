"""Code lookup tools for LLM (v4.0 - Wave A.1).

Same-system code<->name lookup only. Cross-system mapping tools
(``map_code``) were removed: the advisory crosswalk must not be exposed to
the LLM. Names/codes are resolved within each encoding system.

1. `decode_code` (mode 1): Auto-detect encoding system from code, return name + system description.
   - Input: any code string (e.g., "0101", "V11", "01")
   - Output: {code, detected_system, system_description, name}
   - Forward direction, deterministic 1:1, no code->code chains.

2. `lookup_land_use_code` (mode 2): Forward name -> codes.
   - Input: Chinese land-use name (e.g., "宅基地")
   - Output: {ghytbm, ghflbm, dlbm_aliases, candidates}
   - CODE-ONLY return within each same-system encoding; no cross-system
     derived fields (zone_type / vne_code / planning_zone) and no names.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from langchain_core.tools import tool
from pydantic import BaseModel

from app.utils.logger import get_logger
from app.tools.helpers import make_result

logger = get_logger(__name__)


# ============================================================
# Tool 1: decode_code - auto-detect encoding system + name lookup
# ============================================================

# System priority order for ambiguous codes (lower index = higher priority).
# In practice, code spaces are disjoint, so ambiguity is rare.
_SYSTEM_PRIORITY = (
    "gbt21010",          # DLBM (4-digit 01XX-12XX)
    "appendix5",         # GHYTBM (4-digit 11XX/12XX/13XX/15XX/21XX/22XX/23XX/31XX/32XX)
    "tugui",             # 土规 (4-digit 01XX-20XX, overlaps with gbt21010 - gbt21010 wins)
    "ghflbm",            # 规划分区大类 (4-digit 11XX/12XX/13XX/15XX/21XX/22XX/31XX)
    "vne_code",          # V/N/E (alphanumeric: V, V1, V11, N1, N2, E1, E11, E9)
    "ydyhfldm",          # 用地用海分类 (4-digit, overlaps - gbt21010 wins)
    "zone_type_appendix5",  # Chinese name as code
    "zone_type_gbt50137",   # Letter codes R/A/B/M/W/S/U/G/D
    "zone_type_town",       # Chinese name as code
    "zone_type_village",    # Chinese name as code
    "planning_zone",        # Chinese name as code (6 zones)
    "primary_zone",         # Chinese name as code (3 zones)
    "three_categories",     # Chinese name as code (3 categories)
    "space_control",        # 2-digit 01-06
)

_SYSTEM_DESCRIPTIONS: Dict[str, str] = {
    "gbt21010": "GB/T 21010-2017 土地利用现状分类（三调国标，4位数字）",
    "appendix5": "广东省村庄规划用地分类附录5（GHYTBM，4位数字）",
    "tugui": "广东省县级土地利用总体规划数据库标准（土规，4位数字）",
    "ghflbm": "广东省土规数据库标准 规划分类编码（GHFLBM，4位数字）",
    "vne_code": "住建部《村庄规划用地分类指南》V/N/E分类（字母+数字）",
    "ydyhfldm": "自然资发〔2023〕234号 用地用海分类（4位数字）",
    "zone_type_appendix5": "广东省附录5 5-tier 功能类（中文名）",
    "zone_type_gbt50137": "GB 50137-2011 城市用地分类（R/A/B/M/W/S/U/G/D 字母码）",
    "zone_type_town": "GB 50188-2007 镇规划 8大类（中文名）",
    "zone_type_village": "村土地利用规划编制技术导则 3-tier（中文名）",
    "planning_zone": "TD/T 1027-2010 附录B 规划分区（6 zones，中文名）",
    "primary_zone": "三区三线 三大类空间（生态/农业/城镇空间，中文名）",
    "three_categories": "《土地管理法》三大类（农用地/建设用地/未利用地，中文名）",
    "space_control": "建设用地管制区编码（01-06）",
}

# Map system keys (in _SYSTEM_PRIORITY) to lookup_code_name code_type values
# (which are the keys in app.utils.code_lookup.NAME_BY_CODE).
_NAME_LOOKUP_TYPE: Dict[str, str] = {    "gbt21010": "dlbm",
    "appendix5": "ghytbm",
    "tugui": "dlbm",  # tugui uses similar code space
    "ghflbm": "ghflbm",
    "vne_code": "vne_code",
    "ydyhfldm": "dlbm",  # similar code space
    "zone_type_appendix5": "zone_type_appendix5",
    "zone_type_gbt50137": "zone_type_gbt50137",
    "zone_type_town": "zone_type_town",
    "zone_type_village": "zone_type_village",
    "planning_zone": "planning_zone",
    "primary_zone": "primary_zone",
    "three_categories": "three_categories",
    "space_control": "space_control",
}


@tool
def decode_code(code: str) -> Dict[str, Any]:
    """Auto-detect encoding system for a code and return Chinese name + system info.

    Iterates 14 encoding systems in priority order. First match wins.
    Code spaces are mostly disjoint, so ambiguity is rare in practice.

    Args:
        code: Any code string (e.g., "0101", "V11", "01", "居住用地", "R").

    Returns:
        Dict with:
          - code: the input code
          - detected_system: system key (e.g., "gbt21010") or "unknown"
          - system_description: human-readable standard reference
          - name: Chinese name (or "" if not found)

    Example:
        decode_code("0101") -> {"code": "0101", "detected_system": "gbt21010",
                                 "system_description": "GB/T 21010-2017...",
                                 "name": "水田"}
        decode_code("V11") -> {"code": "V11", "detected_system": "vne_code", ...}
        decode_code("R") -> {"code": "R", "detected_system": "zone_type_gbt50137", ...}
    """
    try:
        from app.utils.code_lookup import NAME_BY_CODE

        if not code:
            return {
                "code": code,
                "detected_system": "unknown",
                "system_description": "",
                "name": "",
            }

        code_str = str(code).strip()
        for sys_key in _SYSTEM_PRIORITY:
            # Translate system key to NAME_BY_CODE key (e.g., "gbt21010" -> "dlbm")
            name_key = _NAME_LOOKUP_TYPE.get(sys_key, sys_key)
            table = NAME_BY_CODE.get(name_key, {})
            if code_str in table:
                return {
                    "code": code_str,
                    "detected_system": sys_key,
                    "system_description": _SYSTEM_DESCRIPTIONS.get(sys_key, ""),
                    "name": table[code_str],
                }

        return {
            "code": code_str,
            "detected_system": "unknown",
            "system_description": "",
            "name": "",
        }
    except Exception as e:
        logger.warning("[decode_code] Failed: %s", e)
        return {"code": code, "detected_system": "unknown", "system_description": "", "name": "", "error": str(e)}


# ============================================================
# Tool 2: lookup_land_use_code (same-system code-only output)
# ============================================================

class GHYTBMMatch(BaseModel):
    """A single GHYTBM (planning use code) match entry.

    v4.0: ghytmc and cross-system zone_type/vne_code removed. Names and
    cross-system derivations are not exposed; use decode_code for names.
    """
    ghytbm: str = ""


class DLBMMatch(BaseModel):
    """A single DLBM (current land-use code) match entry.

    v4.0: dlmc and cross-system zone_type removed.
    """
    dlbm: str = ""


class GHFLBMMatch(BaseModel):
    """A single GHFLBM (planning classification) match entry.

    v4.0: ghytmc removed. Use decode_code(ghytbm) to get the name.
    """
    ghflbm: str = ""
    ghytbm: str = ""


class LandUseCodeLookup(BaseModel):
    """Typed result for lookup_land_use_code.

    v4.0: same-system codes only. No cross-system derived fields
    (zone_type / vne_code) and no names (use decode_code for names).
    """
    ghytbm: str = ""
    ghflbm: str = ""
    dlbm_aliases: List[str] = []
    candidates_ghytbm: List[GHYTBMMatch] = []
    candidates_dlbm: List[DLBMMatch] = []


@tool
def lookup_land_use_code(land_use_name: str) -> Dict[str, Any]:
    """Look up standard land-use CODES for a given land-use name.

    v4.0: SAME-SYSTEM CODE-ONLY RETURN. No ghytmc/dlmc name fields, no
    cross-system derived fields (zone_type / vne_code). To resolve a code
    to its Chinese name, call decode_code(code) separately.

    Queries DictionaryCenter YAML dictionaries (appendix5, gbt21010).
    Does NOT auto-convert between encoding systems - only returns lookup
    results and candidate suggestions within each same-system encoding.

    Args:
        land_use_name: Chinese land-use name (e.g., "经营性建设用地", "宅基地")

    Returns:
        Dict with matching same-system codes (no names, no cross-system
        derivations): ghytbm, ghflbm, dlbm_aliases, candidates_ghytbm,
        candidates_dlbm.
    """
    try:
        from app.data.encodings.code_sets import (
            GHYTBM_TO_GHYTMC,
            GHFLBM_TO_GHYTBMS,
            DLBM_TO_DLMC,
        )

        # Search in GHYTBM names (planning use codes) - typed matches
        ghytbm_matches: List[GHYTBMMatch] = []
        for code, name in GHYTBM_TO_GHYTMC.items():
            if land_use_name in name or name in land_use_name:
                ghytbm_matches.append(GHYTBMMatch(ghytbm=code))

        # Search in DLBM names (current land-use codes) - typed matches
        dlbm_matches: List[DLBMMatch] = []
        for code, name in DLBM_TO_DLMC.items():
            if land_use_name in name or name in land_use_name:
                dlbm_matches.append(DLBMMatch(dlbm=code))

        # Search in GHFLBM (planning classification) - typed matches
        ghflbm_matches: List[GHFLBMMatch] = []
        for code, ghytbms in GHFLBM_TO_GHYTBMS.items():
            for ghytbm in ghytbms:
                name = GHYTBM_TO_GHYTMC.get(ghytbm, "")
                if land_use_name in name or name in land_use_name:
                    ghflbm_matches.append(GHFLBMMatch(ghflbm=code, ghytbm=ghytbm))
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
        lookup = LandUseCodeLookup(
            ghytbm=primary.ghytbm,
            ghflbm=ghflbm_matches[0].ghflbm if ghflbm_matches else "",
            dlbm_aliases=[m.dlbm for m in dlbm_matches],
            candidates_ghytbm=ghytbm_matches[:5],
            candidates_dlbm=dlbm_matches[:5],
        )

        return make_result(success=True, data=lookup.model_dump())
    except Exception as e:
        logger.warning("[lookup_land_use_code] Failed: %s", e)
        return make_result(success=False, error=str(e))


__all__ = ["decode_code", "lookup_land_use_code"]