from shapely.geometry import Polygon

from app.modules.kg.ontology import ThreeLineSubtypes
from app.modules.schema.contracts.custom_zone_contracts import (
    Vocabulary,
    VocabularyCategory,
)
from app.tools.gis._generation.custom_zone_generator import (
    CustomZoningGenerator,
)
from app.modules.schema.provenance import ProvenanceSource


def _parcel(bsm, dlbm=""):
    return {
        "bsm": bsm,
        "dlbm": dlbm,
        "geometry": Polygon([(0, 0), (1, 0), (1, 1), (0, 1)]),
    }


# v4: 词汇表为 LLM/报告动态提取的内存对象，不再加载固定 YAML
_LEAD_VOCAB = Vocabulary(
    name="jintian_industry",
    categories=[
        VocabularyCategory(
            code="IND_LEAD", name_zh="主导产业区", color="#CC5500",
            typing_rules=[{"kind": "dlbm_in", "value": ["2124", "2125"]}],
        )
    ],
)


def _intent(category_code, bsms):
    return {
        "vocabulary": _LEAD_VOCAB,
        "vocabulary_name": "jintian_industry",
        "custom_zone_targets": [
            {
                "vocabulary_name": "jintian_industry",
                "category_code": category_code,
                "target_bsms": bsms,
                "decided_by": "llm",
            }
        ],
    }


def test_generator_emits_functional_zones_with_provenance():
    parcels = [_parcel("P1", "2124"), _parcel("P2", "0301")]
    intent = _intent("IND_LEAD", ["P1"])
    gen = CustomZoningGenerator(parcels=parcels, intent=intent)
    zones = gen.generate()
    assert len(zones) == 1
    z = zones[0]
    assert z["pln:vocabulary_name"] == "jintian_industry"
    assert z["pln:category_code"] == "IND_LEAD"
    assert z["pln:category_name_zh"] == "主导产业区"
    assert z["pln:color"] == "#CC5500"
    assert z["pln:encoding_provenance"] == "custom:vocabulary"
    assert "P1" in z["pln:target_bsms"]
    assert "P2" not in z["pln:target_bsms"]


def test_generator_blocks_target_inside_ecological_redline():
    parcels = [_parcel("P1", "2124")]
    eco = Polygon([(0, 0), (2, 0), (2, 2), (0, 2)])
    three_lines = {
        ThreeLineSubtypes.ECOLOGICAL_REDLINE: [{"bsm": "EL1", "geometry": eco}],
    }
    intent = _intent("IND_LEAD", ["P1"])
    gen = CustomZoningGenerator(parcels=parcels, intent=intent, three_lines=three_lines)
    zones, audit = gen.generate_with_validation()
    assert zones == []
    blocked = [e for e in audit.report() if "protection_line_conflict" in (e.note or "")]
    assert len(blocked) == 1
    assert blocked[0].source == ProvenanceSource.CUSTOM_VOCABULARY.value


def test_generator_skips_unknown_bsm():
    parcels = [_parcel("P1", "2124")]
    intent = _intent("IND_LEAD", ["P1", "MISSING_BSM"])
    gen = CustomZoningGenerator(parcels=parcels, intent=intent)
    zones = gen.generate()
    assert len(zones) == 1
    assert zones[0]["pln:target_bsms"] == ["P1"]


def test_generator_unknown_category_logs_audit_no_zone():
    parcels = [_parcel("P1", "2124")]
    intent = _intent("UNKNOWN_CODE", ["P1"])
    gen = CustomZoningGenerator(parcels=parcels, intent=intent)
    zones, audit = gen.generate_with_validation()
    assert zones == []
    notes = [e.note for e in audit.report() if e.note]
    assert any("unknown category_code" in (n or "") for n in notes)