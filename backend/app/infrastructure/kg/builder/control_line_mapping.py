"""Bundle-key → ControlLine Pydantic class mapping.

Centralizes the correspondence between ingest bundle keys (used by jintian
data sources and other village bundles) and the existing Pydantic ControlLine
subclasses defined in ``app.data.model.spatial_types``.

Three-lines (法定约束底线):
  - ecological_redline             → EcologicalRedline
  - farmland_redline               → FarmlandProtection
  - urban_dev_boundary             → UrbanDevBoundary
  - village_construction_boundary  → VillageDevBoundary

Other control lines (currently 灾害/洪涝):
  - hazard_control_line  → HazardControlLine
  - flood_control_line   → FloodControlLine

CultivatedLandTarget is intentionally excluded — it represents a 耕地保有量
target, not a hard constraint boundary.
"""

from app.data.model.spatial_types import (
    EcologicalRedline,
    FarmlandProtection,
    FloodControlLine,
    HazardControlLine,
    UrbanDevBoundary,
    VillageDevBoundary,
)


THREE_LINE_BUNDLE_TO_PYDANTIC: dict[str, type] = {
    "ecological_redline": EcologicalRedline,
    "farmland_redline": FarmlandProtection,
    "urban_dev_boundary": UrbanDevBoundary,
    "village_construction_boundary": VillageDevBoundary,
}

OTHER_CONTROL_LINE_BUNDLE_TO_PYDANTIC: dict[str, type] = {
    "hazard_control_line": HazardControlLine,
    "flood_control_line": FloodControlLine,
}

ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC: dict[str, type] = {
    **THREE_LINE_BUNDLE_TO_PYDANTIC,
    **OTHER_CONTROL_LINE_BUNDLE_TO_PYDANTIC,
}

THREE_LINE_BUNDLE_KEYS: frozenset[str] = frozenset(THREE_LINE_BUNDLE_TO_PYDANTIC.keys())

ALL_CONTROL_LINE_BUNDLE_KEYS: frozenset[str] = frozenset(
    ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC.keys()
)