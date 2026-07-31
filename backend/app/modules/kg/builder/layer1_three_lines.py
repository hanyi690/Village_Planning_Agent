from typing import Iterable, List, Tuple

from app.modules.kg.ontology import EntityTypes, ThreeLineSubtypes
from app.modules.schema.provenance import ProvenanceAudit, ProvenanceSource


_SUBTYPE_TO_SOURCE: dict[str, Tuple[str, str]] = {
    ThreeLineSubtypes.ECOLOGICAL_REDLINE: (
        "ecological_protection.geojson",
        ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    ),
    ThreeLineSubtypes.FARMLAND_REDLINE: (
        "farmland_protection.geojson",
        ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    ),
    ThreeLineSubtypes.URBAN_DEV_BOUNDARY: (
        "gd_urban_dev_boundary",
        ProvenanceSource.DERIVED_UPPER_PLAN_OVERLAY,
    ),
    ThreeLineSubtypes.VILLAGE_CONSTRUCTION_BOUNDARY: (
        "village_construction_boundary",
        ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    ),
}

_MISSING_PROVENANCE: dict[str, ProvenanceSource] = {
    ThreeLineSubtypes.ECOLOGICAL_REDLINE: ProvenanceSource.MISSING_THREE_LINE,
    ThreeLineSubtypes.FARMLAND_REDLINE: ProvenanceSource.MISSING_THREE_LINE,
    ThreeLineSubtypes.URBAN_DEV_BOUNDARY: ProvenanceSource.MISSING_URBAN_DEV_BOUNDARY,
    ThreeLineSubtypes.VILLAGE_CONSTRUCTION_BOUNDARY: ProvenanceSource.MISSING_THREE_LINE,
}


def build_three_line_entities(
    three_lines: dict,
) -> Tuple[List[dict], ProvenanceAudit]:
    """Build THREE_LINE entity dicts from bundle three-line layers.

    Args:
        three_lines: ``{subtype: [feature_dict, ...]}``. Each feature_dict has
            at least ``bsm`` and ``geometry``.

    Returns:
        (entities, audit) — entities is a list of KG-ready dicts. Missing
        sources emit audit entries but do not raise.
    """
    audit = ProvenanceAudit()
    entities: List[dict] = []

    for subtype, (source_file, derived_prov) in _SUBTYPE_TO_SOURCE.items():
        features: Iterable[dict] = three_lines.get(subtype, []) or []
        if not features:
            audit.record(
                f"three_line.{subtype}",
                _MISSING_PROVENANCE[subtype],
                parcel_count=0,
                note=f"missing source: {source_file}",
            )
            continue
        for feat in features:
            entities.append(
                {
                    "entity_type": EntityTypes.ThreeLine,
                    "subtype": subtype,
                    "bsm": feat.get("bsm", ""),
                    "geometry": feat.get("geometry"),
                    "encoding_provenance": derived_prov.value,
                    "source_file": source_file,
                }
            )
    return entities, audit