"""Advisory cross-system land-use mappings — isolated from schema code sets.

Cross-system mapping tables and lookup functions (DLBM→zone_type, DLBM→planning_zone,
GHYTBM→VNE, zone_type→planning_zone, planning_zone→primary_zone, …). Same-system
code→name sets stay in ``app.data.encodings.code_sets``.

The underlying YAML data lives in ``advisory_crosswalks/yaml/`` and is scanned by
``DictionaryCenter`` so ``get_center().get(...)`` / ``get_mapping(...)`` keep working.
"""

from .crosswalks import *  # noqa: F401,F403

__all__ = [
    # Dicts
    "DLBM_TO_ZONE_TYPE", "DLBM_TO_ZONE_TYPE_CURRENT",
    "DLBM_TO_PLANNING_ZONE", "DLBM_TO_PRIMARY_ZONE", "DLBM_TO_THREE_CATEGORIES",
    "ZONE_TYPE_TO_DLBMS", "ZONE_TYPE_TO_PLANNING_ZONE",
    "PLANNING_ZONE_TO_PRIMARY_ZONE", "PLANNING_ZONE_TO_CONTROL_CODE",
    "GHYTBM_TO_PLANNING_ZONE", "GHYTBM_TO_ZONE_TYPE", "GHYTBM_TO_VNE",
    "GHYTMC_TO_ZONE_TYPE", "GHYTMC_TO_PLANNING_ZONE",
    "VNE_TO_ZONE_TYPE", "ZONE_TYPE_TO_VNE",
    "DLBM_TO_GHYTBM", "DLBM_TO_GHYTBM_CONVERSIONS",
    "GHFLBM_TO_ZONE_TYPE", "GHFLBM_TO_TDYTFQDM", "GHFLBM_TO_TDYT_NAME",
    "SDDLBM_TO_YDYHFLDM",
    # Functions
    "get_zone_type_for_dlbm", "resolve_zone_type_for_dlbm", "get_dlbms_for_zone_type",
    "get_zone_type_for_planned_dlbm",
    "get_zone_type_for_ghytmc", "get_primary_zone",
    "dlbm_to_planning_zone", "get_primary_zone_for_planning_zone",
    "get_zone_type_for_ghflbm", "get_zone_type_for_ghytbm",
    "get_ghytmc_for_ghytbm",
    "get_zone_type_for_vne", "get_vne_for_zone_type",
    "convert_sddlbm_to_ydyhfldm", "get_vne_for_ghytbm",
    "get_tdytfqdm_for_ghflbm", "get_tdyt_name_for_ghflbm",
    "get_space_control_name", "get_space_control_code",
    "get_ghytbm_for_dlbm", "get_ghytbm_conversion_info",
    "normalize_landuse",
    "get_planning_zone_from_landuse",
]
