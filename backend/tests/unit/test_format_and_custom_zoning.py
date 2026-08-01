"""P6/P6.5 单测：format_bound_intent project 域 + CustomZoningGenerator 规则选择。"""

from app.agent.gis.format_bound_intent import format_bound_spatial_intent
from app.modules.schema.contracts.custom_zone_contracts import Vocabulary, VocabularyCategory
from app.modules.schema.encodings.dicts.vocabularies.loader import register_vocabulary
from app.tools.gis._generation.custom_zone_generator import CustomZoningGenerator


def test_format_project_domain_to_custom_zone_target():
    register_vocabulary(
        "sess_fmt_vocab",
        Vocabulary(
            name="sess_fmt_vocab",
            categories=[
                VocabularyCategory(code="FZ01", name_zh="生态保护区", color="#2d6a4f"),
                VocabularyCategory(code="FZ02", name_zh="农田保护区", color="#f2994a"),
            ],
        ),
    )
    bound = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "domain": "project",
                    "name": "生态保护区",
                    "evidence_text": "生态保护区 15.39%",
                    "source_bsm_list": ["44142611020200000563"],
                    "binding_status": "confirmed",
                    "confidence": 0.85,
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "domain": "zone",
                    "name": "农田保护区",
                    "evidence_text": "农田保护区占比3.35%",
                    "source_bsm_list": [],
                    "binding_status": "unresolved",
                },
            },
        ],
    }
    intent = format_bound_spatial_intent(
        village_name="金田村",
        bound_entities=bound,
        vocabulary_name="sess_fmt_vocab",
    )
    assert len(intent.custom_zone_targets) == 1
    cz = intent.custom_zone_targets[0]
    assert cz.vocabulary_name == "sess_fmt_vocab"
    assert cz.category_code == "FZ01"
    assert cz.target_bsms == ["44142611020200000563"]
    # zone 域带 area_ratio
    assert any(zt.land_use == "农田保护区" and abs(zt.area_ratio - 0.0335) < 1e-6 for zt in intent.zone_targets)


def test_custom_zoning_generator_selects_by_rules_without_bsm():
    from shapely.geometry import box

    vocab = Vocabulary(
        name="v1",
        categories=[
            VocabularyCategory(
                code="FZ01", name_zh="生态保护区", color="#2d6a4f",
                typing_rules=[{"kind": "dlbm_in", "value": ["0301", "0302"]}],
            )
        ],
    )
    parcels = [
        {"bsm": "P1", "dlbm": "0301", "geometry": box(0, 0, 1, 1)},
        {"bsm": "P2", "dlbm": "0101", "geometry": box(1, 0, 2, 1)},
    ]
    intent = {
        "vocabulary": vocab,
        "custom_zone_targets": [
            {"vocabulary_name": "v1", "category_code": "FZ01", "target_bsms": []}
        ],
    }
    zones = CustomZoningGenerator(parcels, intent).generate()
    assert len(zones) == 1
    zone = zones[0]
    assert zone["pln:category_code"] == "FZ01"
    assert zone["pln:target_bsms"] == ["P1"]
    assert zone["pln:color"] == "#2d6a4f"
