"""P6/P6.5 单测：format_bound_intent project 域 + CustomZoningGenerator 规则选择。"""

from app.agent.ground.format_bound_intent import format_bound_spatial_intent
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
    # project 域 1 个 + P6.6 zone 域匹配（农田保护区→FZ02）1 个
    assert len(intent.custom_zone_targets) == 2
    cz = intent.custom_zone_targets[0]
    assert cz.vocabulary_name == "sess_fmt_vocab"
    assert cz.category_code == "FZ01"
    assert cz.target_bsms == ["44142611020200000563"]
    codes = {c.category_code for c in intent.custom_zone_targets}
    assert codes == {"FZ01", "FZ02"}
    # zone 域带 area_ratio
    assert any(zt.land_use == "农田保护区" and abs(zt.area_ratio - 0.0335) < 1e-6 for zt in intent.zone_targets)


def test_format_dedupes_zone_targets_by_land_use():
    """同 land_use 的 zone 域实体应合并候选 BSM，不产生重复 ZoneTarget（KG URI 冲突根因）。"""
    from app.modules.schema.contracts.parse_contracts import SpatialPlanningIntent
    from app.modules.schema.contracts.parse_contracts import ZoneTarget

    fallback = SpatialPlanningIntent(
        zone_targets=[
            ZoneTarget(land_use="生态保护区", source_instruction_id=""),
        ]
    )
    bound = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "domain": "zone",
                    "planning_zone": "生态保护区",
                    "evidence_text": "生态保护区 330 公顷",
                    "source_bsm_list": ["44142611020200000563"],
                    "binding_status": "candidate",
                },
            },
            {
                "type": "Feature",
                "properties": {
                    "domain": "zone",
                    "planning_zone": "农田保护区",
                    "evidence_text": "农田保护区 85 公顷",
                    "source_bsm_list": [],
                    "binding_status": "unresolved",
                },
            },
        ],
    }
    intent = format_bound_spatial_intent(
        village_name="金田村",
        bound_entities=bound,
        fallback_intent=fallback,
    )
    names = [zt.land_use for zt in intent.zone_targets]
    assert len(names) == len(set(names)), f"duplicate zone land_use: {names}"
    assert names.count("生态保护区") == 1
    eco = next(zt for zt in intent.zone_targets if zt.land_use == "生态保护区")
    assert "44142611020200000563" in eco.candidate_bsms


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
