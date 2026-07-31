from app.modules.kg.builder.layer1_three_lines import build_three_line_entities
from app.modules.kg.ontology import EntityTypes, ThreeLineSubtypes


def test_builds_present_lines_only():
    bundle = {
        ThreeLineSubtypes.ECOLOGICAL_REDLINE: [{"geometry": "POLYGON(...)", "bsm": "R1"}],
        ThreeLineSubtypes.FARMLAND_REDLINE: [
            {"geometry": "POLYGON(...)", "bsm": "R2"},
            {"geometry": "POLYGON(...)", "bsm": "R3"},
        ],
    }
    entities, audit = build_three_line_entities(bundle)
    assert len(entities) == 3
    subtypes = [e["subtype"] for e in entities]
    assert subtypes.count(ThreeLineSubtypes.ECOLOGICAL_REDLINE) == 1
    assert subtypes.count(ThreeLineSubtypes.FARMLAND_REDLINE) == 2
    assert all(e["entity_type"] == EntityTypes.ThreeLine for e in entities)

    missing = audit.missing_layers()
    sources = {e.source for e in missing}
    assert "missing:gd_urban_dev_boundary" in sources
    assert any("missing:three_line" in s for s in sources)


def test_empty_bundle_emits_all_missing():
    entities, audit = build_three_line_entities({})
    assert entities == []
    assert len(audit.missing_layers()) == 4


def test_jintian_partial_three_lines():
    """Jintian has ecological_protection (5) + farmland_protection (88), missing UDB and ZJDJSFWX."""
    bundle = {
        ThreeLineSubtypes.ECOLOGICAL_REDLINE: [{"bsm": f"E{i}", "geometry": "x"} for i in range(5)],
        ThreeLineSubtypes.FARMLAND_REDLINE: [{"bsm": f"F{i}", "geometry": "x"} for i in range(88)],
    }
    entities, audit = build_three_line_entities(bundle)
    assert len(entities) == 93
    assert all(e["encoding_provenance"] == "derived:three_line_overlay" for e in entities)
    missing = audit.missing_layers()
    assert any(e.source == "missing:gd_urban_dev_boundary" for e in missing)