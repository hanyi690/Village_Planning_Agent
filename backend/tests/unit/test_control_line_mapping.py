from app.modules.kg.builder.control_line_mapping import (
    ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC,
    OTHER_CONTROL_LINE_BUNDLE_TO_PYDANTIC,
    THREE_LINE_BUNDLE_TO_PYDANTIC,
    THREE_LINE_BUNDLE_KEYS,
)
from app.modules.kg.ontology import EntityTypes
from app.modules.schema.types.spatial_types import (
    EcologicalRedline,
    FarmlandProtection,
    FloodControlLine,
    HazardControlLine,
    UrbanDevBoundary,
    VillageDevBoundary,
)


def test_three_line_mapping_has_four_keys():
    assert len(THREE_LINE_BUNDLE_TO_PYDANTIC) == 4
    assert set(THREE_LINE_BUNDLE_TO_PYDANTIC.keys()) == {
        "ecological_redline",
        "farmland_redline",
        "urban_dev_boundary",
        "village_construction_boundary",
    }


def test_three_line_mapping_resolves_to_existing_pydantic_subclasses():
    assert THREE_LINE_BUNDLE_TO_PYDANTIC["ecological_redline"] is EcologicalRedline
    assert THREE_LINE_BUNDLE_TO_PYDANTIC["farmland_redline"] is FarmlandProtection
    assert THREE_LINE_BUNDLE_TO_PYDANTIC["urban_dev_boundary"] is UrbanDevBoundary
    assert THREE_LINE_BUNDLE_TO_PYDANTIC["village_construction_boundary"] is VillageDevBoundary
    # each must be a ControlLine subclass
    from app.modules.schema.types.spatial_types import ControlLine

    for cls in THREE_LINE_BUNDLE_TO_PYDANTIC.values():
        assert issubclass(cls, ControlLine), f"{cls} is not ControlLine"


def test_other_control_line_mapping_resolves_to_existing_pydantic_subclasses():
    assert OTHER_CONTROL_LINE_BUNDLE_TO_PYDANTIC["hazard_control_line"] is HazardControlLine
    assert OTHER_CONTROL_LINE_BUNDLE_TO_PYDANTIC["flood_control_line"] is FloodControlLine
    assert len(ALL_CONTROL_LINE_BUNDLE_TO_PYDANTIC) == 6


def test_three_line_bundle_keys_is_frozenset():
    assert isinstance(THREE_LINE_BUNDLE_KEYS, frozenset)
    assert "ecological_redline" in THREE_LINE_BUNDLE_KEYS
    assert "hazard_control_line" not in THREE_LINE_BUNDLE_KEYS