from typing import Iterable, List, Tuple

from app.infrastructure.kg.builder.control_line_mapping import (
    ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC,
    THREE_LINE_BUNDLE_KEYS,
)
from app.infrastructure.kg.ontology import EntityTypes
from app.modules.schema.provenance import ProvenanceAudit, ProvenanceSource


_DERIVED_PROVENANCE = {
    "ecological_redline": ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    "farmland_redline": ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    "urban_dev_boundary": ProvenanceSource.DERIVED_UPPER_PLAN_OVERLAY,
    "village_construction_boundary": ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    "hazard_control_line": ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
    "flood_control_line": ProvenanceSource.DERIVED_THREE_LINE_OVERLAY,
}

_MISSING_PROVENANCE = {
    "ecological_redline": ProvenanceSource.MISSING_THREE_LINE,
    "farmland_redline": ProvenanceSource.MISSING_THREE_LINE,
    "urban_dev_boundary": ProvenanceSource.MISSING_URBAN_DEV_BOUNDARY,
    "village_construction_boundary": ProvenanceSource.MISSING_THREE_LINE,
}


def build_control_line_entities(
    control_lines: dict,
    *,
    audit_only_three_lines: bool = True,
) -> Tuple[List[dict], ProvenanceAudit]:
    """Build ControlLine entity dicts (handles all 6 subtypes: 三线 + 灾害 + 洪涝).

    Args:
        control_lines: ``{bundle_key: [feature_dict, ...]}``. bundle_key must be in
            ``ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC`` (otherwise ignored).
        audit_only_three_lines: when True (default), only the 4 三线 subtypes
            emit missing-source audit entries; 灾害/洪涝 still get KG entities
            but no audit. Pass False to audit all 6.

    Returns:
        (entities, audit) — entities have ``entity_type=EntityTypes.ControlLine``
        and ``subtype=<Pydantic class name>``. Missing three-line sources emit
        audit entries; missing 灾害/洪涝 sources emit audit only when
        ``audit_only_three_lines=False``.
    """
    audit = ProvenanceAudit()
    entities: List[dict] = []

    for bundle_key, pydantic_cls in ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC.items():
        features: Iterable[dict] = control_lines.get(bundle_key, []) or []
        is_three_line = bundle_key in THREE_LINE_BUNDLE_KEYS

        if not features:
            if is_three_line or not audit_only_three_lines:
                audit.record(
                    f"control_line.{bundle_key}",
                    _MISSING_PROVENANCE.get(
                        bundle_key, ProvenanceSource.MISSING_THREE_LINE
                    ),
                    parcel_count=0,
                    note=f"missing source for {pydantic_cls.__name__}",
                )
            continue

        for feat in features:
            entities.append(
                {
                    "entity_type": EntityTypes.ControlLine,
                    "subtype": pydantic_cls.__name__,
                    "bsm": feat.get("bsm", ""),
                    "geometry": feat.get("geometry"),
                    "encoding_provenance": _DERIVED_PROVENANCE[bundle_key].value,
                    "source_file": feat.get("source_file", bundle_key),
                }
            )
    return entities, audit