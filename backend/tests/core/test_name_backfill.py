"""Tests for LLM-assisted KG name backfill."""

from __future__ import annotations

import asyncio

from rdflib import Literal, RDF, URIRef

from app.infrastructure.kg.ontology import PLN, EntityTypes
from app.infrastructure.kg.builder.base import PlanningKG
from app.infrastructure.kg.enrichment.name_backfill import (
    NameMention,
    backfill_kg_names,
    build_candidates,
    nameless_entities,
)
from app.contracts.spatial.spatial_reference_contracts import CandidateSelectionProposal


def _kg() -> PlanningKG:
    kg = PlanningKG(village_name="test")
    road = URIRef("pln:road_1")
    kg.g.add((road, RDF.type, EntityTypes.Road))
    kg.g.add((road, PLN.name, Literal("道路_1")))
    kg.g.add((road, PLN.bsm, Literal("bsm-100")))
    kg.g.add((road, PLN.lon, Literal(113.1)))
    kg.g.add((road, PLN.lat, Literal(23.1)))
    water = URIRef("pln:water_2")
    kg.g.add((water, RDF.type, EntityTypes.WaterBody))
    kg.g.add((water, PLN.name, Literal("水体_2")))
    kg.g.add((water, PLN.bsm, Literal("bsm-200")))
    kg.g.add((water, PLN.lon, Literal(113.2)))
    kg.g.add((water, PLN.lat, Literal(23.2)))
    fac = URIRef("pln:fac_3")
    kg.g.add((fac, RDF.type, EntityTypes.Facility))
    kg.g.add((fac, PLN.name, Literal("祠堂")))
    kg.g.add((fac, PLN.bsm, Literal("bsm-300")))
    return kg


def _gazetteer():
    from app.infrastructure.kg.gazetteer import Gazetteer, GazetteerEntry

    return Gazetteer([
        GazetteerEntry(
            name="园寨村",
            bsms=["bsm-100", "bsm-200"],
            centroid=[113.15, 23.15],
            source="kg_cluster",
            confidence=0.9,
        )
    ])


def test_nameless_entities_filters_generic_names():
    kg = _kg()
    roads = nameless_entities(kg, "road")
    assert [e["current_name"] for e in roads] == ["道路_1"]
    waters = nameless_entities(kg, "water")
    assert [e["current_name"] for e in waters] == ["水体_2"]
    # 祠堂 is a real name, not a nameless entity
    assert nameless_entities(kg, "facility") == []


def test_build_candidates_narrows_by_type_and_location():
    kg = _kg()
    gaz = _gazetteer()
    roads = build_candidates(kg, gaz, NameMention(name="Y122乡道", role="road", location="园寨村"))
    assert [c["current_name"] for c in roads] == ["道路_1"]
    waters = build_candidates(kg, gaz, NameMention(name="金田河", role="water", location="园寨村"))
    assert [c["current_name"] for c in waters] == ["水体_2"]
    # location that matches nothing -> no candidates (fail-closed)
    empty = build_candidates(kg, gaz, NameMention(name="石窟河", role="water", location="营仔村"))
    assert empty == []


def test_backfill_writes_single_candidate_names():
    kg = _kg()
    gaz = _gazetteer()
    result = asyncio.run(backfill_kg_names(kg, gaz, [
        NameMention(name="Y122乡道", role="road", location="园寨村"),
        NameMention(name="金田河", role="water", location="园寨村"),
    ]))
    assert result.applied == 2
    road = next(kg.g.subjects(RDF.type, EntityTypes.Road))
    assert str(kg.g.value(road, PLN.name)) == "Y122乡道"
    water = next(kg.g.subjects(RDF.type, EntityTypes.WaterBody))
    assert str(kg.g.value(water, PLN.name)) == "金田河"


def test_backfill_unmatched_stays_unresolved():
    kg = _kg()
    gaz = _gazetteer()
    result = asyncio.run(backfill_kg_names(kg, gaz, [
        NameMention(name="石窟河", role="water", location="营仔村"),
    ]))
    assert result.applied == 0
    assert result.unresolved == ["石窟河"]


class _TypedChoiceModel:
    def __init__(self, owner):
        self.owner = owner

    async def ainvoke(self, _prompt):
        ids = [part.split()[0] for part in _prompt.split("candidate_id=")[1:]]
        digest = _prompt.split("input_digest=", 1)[1].split("；", 1)[0]
        self.owner.calls += 1
        return CandidateSelectionProposal(
            status="selected",
            selected_candidate_id=ids[1],
            input_digest=digest,
        )


class _TypedChoiceLLM:
    def __init__(self):
        self.calls = 0

    def with_structured_output(self, schema):
        assert schema is CandidateSelectionProposal
        return _TypedChoiceModel(self)


def test_backfill_ambiguous_name_requires_typed_llm_choice():
    kg = _kg()
    second = URIRef("pln:road_2")
    kg.g.add((second, RDF.type, EntityTypes.Road))
    kg.g.add((second, PLN.name, Literal("道路_2")))
    kg.g.add((second, PLN.bsm, Literal("bsm-100")))
    kg.g.add((second, PLN.lon, Literal(113.1)))
    kg.g.add((second, PLN.lat, Literal(23.1)))
    gaz = _gazetteer()
    llm = _TypedChoiceLLM()

    from app.spatial.grounding.call_budget import new_ground_llm_budget

    result = asyncio.run(backfill_kg_names(
        kg,
        gaz,
        [NameMention(name="Y122乡道", role="road", location="园寨村")],
        llm=llm,
        budget=new_ground_llm_budget(),
    ))

    assert result.applied == 1
    assert result.unresolved == []
    assert llm.calls == 1
    assert str(kg.g.value(second, PLN.name)) == "Y122乡道"
    first = URIRef("pln:road_1")
    assert str(kg.g.value(first, PLN.name)) == "道路_1"
