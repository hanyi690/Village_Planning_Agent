"""Encoding systems — classification schemas, code sets, and YAML dictionaries."""

from .classification import *  # noqa: F401,F403
from .code_sets import *  # noqa: F401,F403
from .dicts import *  # noqa: F401,F403

# NOTE: vocabulary.py was deleted in v4.7 — its functionality moved to code_sets.py.
#   PlanningZone enum → str, validated via PLANNING_ZONE_NAMES from code_sets.py
#   LanduseClass enum → str, validated via GHYTMC_TO_ZONE_TYPE keys
# v5.2: normalize_landuse(), get_planning_zone_from_landuse() and all cross-system
#   mappings moved to app.modules.schema.advisory_crosswalks.
