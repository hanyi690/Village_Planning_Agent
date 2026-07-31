from app.modules.kg.builder.layer1_control_lines import build_control_line_entities
from app.modules.kg.ontology import EntityTypes


def test_builds_present_three_lines_only():
    bundle = {
        "ecological_redline": [{"geometry": "POLYGON(...)", "bsm": "R1"}],
        "farmland_redline": [
            {"geometry": "POLYGON(...)", "bsm": "R2"},
            {"geometry": "POLYGON(...)", "bsm": "R3"},
        ],
    }
    entities, audit = build_control_line_entities(bundle)
    assert len(entities) == 3
    assert all(e["entity_type"] == EntityTypes.ControlLine for e in entities)
    subtypes = sorted(e["subtype"] for e in entities)
    assert subtypes == ["EcologicalRedline", "FarmlandProtection", "FarmlandProtection"]
    missing = audit.missing_layers()
    missing_layers = {e.layer for e in missing}
    assert "control_line.urban_dev_boundary" in missing_layers
    assert "control_line.village_construction_boundary" in missing_layers


def test_empty_bundle_emits_only_three_line_audit_by_default():
    entities, audit = build_control_line_entities({})
    assert entities == []
    missing_layers = {e.layer for e in audit.missing_layers()}
    # only 三线 4 keys audited by default
    assert missing_layers == {
        "control_line.ecological_redline",
        "control_line.farmland_redline",
        "control_line.urban_dev_boundary",
        "control_line.village_construction_boundary",
    }


def test_empty_bundle_with_audit_only_three_lines_false_emits_all_six():
    entities, audit = build_control_line_entities({}, audit_only_three_lines=False)
    assert entities == []
    missing_layers = {e.layer for e in audit.missing_layers()}
    assert "control_line.hazard_control_line" in missing_layers
    assert "control_line.flood_control_line" in missing_layers
    assert len(missing_layers) == 6


def test_hazard_and_flood_lines_produce_entities_when_present():
    bundle = {
        "hazard_control_line": [{"bsm": "H1", "geometry": "x"}],
        "flood_control_line": [{"bsm": "F1", "geometry": "x"}],
    }
    entities, audit = build_control_line_entities(bundle)
    subtypes = {e["subtype"] for e in entities}
    assert "HazardControlLine" in subtypes
    assert "FloodControlLine" in subtypes
    # default audit_only_three_lines=True → audit entries exist for missing 三线
    # but NOT for missing hazard/flood themselves
    audited_layers = {e.layer for e in audit.missing_layers()}
    assert "control_line.hazard_control_line" not in audited_layers
    assert "control_line.flood_control_line" not in audited_layers
    # however 三线 may still be audited (they're missing here)
    assert "control_line.ecological_redline" in audited_layers


def test_jintian_partial_three_lines():
    bundle = {
        "ecological_redline": [{"bsm": f"E{i}", "geometry": "x"} for i in range(5)],
        "farmland_redline": [{"bsm": f"F{i}", "geometry": "x"} for i in range(88)],
    }
    entities, audit = build_control_line_entities(bundle)
    assert len(entities) == 93
    assert all(e["entity_type"] == EntityTypes.ControlLine for e in entities)
    assert all(e["encoding_provenance"] == "derived:three_line_overlay" for e in entities)
    sources = {e.source for e in audit.missing_layers()}
    assert "missing:gd_urban_dev_boundary" in sources
    assert "missing:three_line" in sources