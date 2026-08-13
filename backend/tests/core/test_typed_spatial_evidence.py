"""Regression tests for typed spatial evidence (defect #4).

Non-village location facts (facility/project/road/water/area/landmark) must
survive the L1 -> gazetteer -> PlaceEvidenceIndex -> GROUND chain without
being coerced to the village role.
"""
from types import SimpleNamespace

from app.infrastructure.kg.gazetteer import GazetteerEntry
from app.infrastructure.kg.enrichment.report_entity_enrichment import _location_fact_mentions
from app.data.ingestion.compiler.profiles.l1_observation import (
    _extract_location_facts_from_observations,
)
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex


def test_facility_location_fact_keeps_facility_role():
    """Observations with a non-village name and explicit facility location
    must produce a facility fact (never coerced to village)."""
    import json

    observations = json.dumps([
        {"entity_type": "现状设施", "name": "祠堂", "location": "设施点", "description": "社前村祖祠", "scale": "1处"},
        {"entity_type": "现状设施", "name": "停车场", "location": "设施点", "description": "停车", "scale": "1处"},
    ], ensure_ascii=False)
    facts = _extract_location_facts_from_observations(
        observations,
        dimension_key="historical_culture",
        report_id="rpt-historical-culture-v1",
    )
    roles = {fact.normalized_name: fact.role for fact in facts}
    assert roles.get("祠堂") == "facility"
    assert roles.get("停车场") == "facility"
    # Defect 1: the explicit facility location part "设施点" must keep the
    # facility role instead of being coerced to village when a name is present.
    assert roles.get("设施点") == "facility"


def test_place_evidence_index_assigns_facility_role_from_gazetteer():
    """A gazetteer entry with source=kg_facility must be registered with the
    facility role (previously hard-coded to village)."""
    gazetteer = SimpleNamespace(entries=[
        GazetteerEntry(
            name="村委会",
            aliases=["村委"],
            entity_uri="pln:facility_1",
            bsms=["bsm-9"],
            centroid=[113.0, 23.0],
            source="kg_facility",
            confidence=0.9,
        ),
    ])
    context = SimpleNamespace(
        session_id="s1", version=1, kg_version=1,
        gazetteer=gazetteer, location_facts=[], bundle=None, kg=None,
    )
    context.current_parcels = lambda: []
    index = PlaceEvidenceIndex.build(context)

    entry = _entry_by_name(index, "村委会")
    assert entry is not None
    assert entry.role == "facility"
    assert "facility" in entry.entity_types


def test_gazetteer_l1_instruction_anchor_uses_uri_kind():
    """l1_instruction combo anchors must derive their role from the entity_uri
    kind segment (pln:anchor_<kind>_...), falling back to village."""
    gazetteer = SimpleNamespace(entries=[
        GazetteerEntry(
            name="停车场@园寨",
            aliases=["停车场"],
            entity_uri="pln:anchor_facility_停车场_园寨",
            bsms=["bsm-1"],
            centroid=[113.0, 23.0],
            source="l1_instruction",
            confidence=0.6,
        ),
        GazetteerEntry(
            name="古驿道@园寨",
            aliases=["古驿道"],
            entity_uri="pln:anchor_landmark_古驿道_园寨",
            bsms=["bsm-1"],
            centroid=[113.0, 23.0],
            source="l1_instruction",
            confidence=0.6,
        ),
        GazetteerEntry(
            name="园寨",
            entity_uri="pln:cluster_1",
            bsms=["bsm-1"],
            centroid=[113.0, 23.0],
            source="kg_cluster",
            confidence=0.9,
        ),
    ])
    context = SimpleNamespace(
        session_id="s1", version=1, kg_version=1,
        gazetteer=gazetteer, location_facts=[], bundle=None, kg=None,
    )
    context.current_parcels = lambda: []
    index = PlaceEvidenceIndex.build(context)

    assert _entry_by_name(index, "停车场@园寨").role == "facility"
    assert _entry_by_name(index, "古驿道@园寨").role == "landmark"
    assert _entry_by_name(index, "园寨").role == "village"


def test_location_fact_mentions_include_non_village_role():
    """_location_fact_mentions must not skip facility facts (previously the
    village-only filter dropped them)."""
    fact = SimpleNamespace(
        mention="祠堂",
        normalized_name="祠堂",
        role="facility",
        aliases=["祠堂"],
        spatial_hint="社前村",
        source_span="祠堂 | 设施点 | 社前村",
        dimension_key="historical_culture",
        source_report_ref="rpt-historical-culture-v1",
    )
    mentions = _location_fact_mentions([fact])
    assert len(mentions) == 1
    assert mentions[0]["name"] == "祠堂"
    assert mentions[0]["role"] == "facility"
    assert not mentions[0]["name"].endswith("村")


def test_village_fact_mentions_keep_village_name_suffix():
    """Village facts must keep the existing {base}村 name suffix behavior."""
    fact = SimpleNamespace(
        mention="园寨村",
        normalized_name="园寨村",
        role="village",
        aliases=["园寨"],
        spatial_hint="园寨",
        dimension_key="socio_economic",
        source_report_ref="rpt-socio-economic-v1",
    )
    mentions = _location_fact_mentions([fact])
    assert len(mentions) == 1
    assert mentions[0]["name"] == "园寨村"
    assert mentions[0]["role"] == "village"


def _entry_by_name(index: PlaceEvidenceIndex, name: str):
    for entry in index.entries:
        if entry.canonical_name == name:
            return entry
    return None
