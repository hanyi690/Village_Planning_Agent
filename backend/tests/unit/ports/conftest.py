from __future__ import annotations

import pytest
from rdflib import RDF, Literal

from app.modules.kg.builder.base import PlanningKG
from app.modules.kg.gazetteer.gazetteer import Gazetteer, GazetteerEntry
from app.modules.kg.ontology import PLN, EntityTypes, Relations


@pytest.fixture
def kg():
    kg = PlanningKG(village_name="test_village")
    g = kg.g
    p1 = PLN.Parcel_P001
    p2 = PLN.Parcel_P002
    road = PLN.Road_R001
    g.add((p1, RDF.type, EntityTypes.Parcel))
    g.add((p1, PLN.bsm, Literal("P001")))
    g.add((p1, PLN.dlbm, Literal("0101")))
    g.add((p2, RDF.type, EntityTypes.Parcel))
    g.add((p2, PLN.bsm, Literal("P002")))
    g.add((p2, PLN.dlbm, Literal("0102")))
    g.add((road, RDF.type, EntityTypes.Road))
    g.add((road, PLN.bsm, Literal("R001")))
    g.add((p2, Relations.sfTouches, road))
    return kg


@pytest.fixture
def gazetteer():
    gaz = Gazetteer()
    gaz.upsert(GazetteerEntry(
        name="园寨", aliases=["yz"], bsms=["P001"], source="kg_cluster", confidence=0.9,
    ))
    gaz.upsert(GazetteerEntry(
        name="田垄", bsms=["P002"], source="bundle_annotation", confidence=0.5,
    ))
    return gaz
