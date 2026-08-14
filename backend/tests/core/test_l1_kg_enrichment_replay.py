"""L1 KG enrichment replay on resume.

L1 ground_anchors injects real names into the in-memory session KG (idempotent:
placeholders only).  Resume rebuilds the base KG from the bundle, so the
enrichment must be re-applied from the persisted grounded_anchors artifact.
This pins the idempotent injection contract.
"""
from __future__ import annotations

from rdflib import Graph, Literal, Namespace, URIRef

PLN = Namespace("http://village-planning.org/ontology#")
RDF = Namespace("http://www.w3.org/1999/02/22-rdf-syntax-ns#")


def _kg():
    from app.infrastructure.kg.builder.base import PlanningKG

    kg = PlanningKG(village_name="金田村")
    cluster = PLN.settlement_cluster_1
    kg.g.add((cluster, RDF.type, PLN.ResidentialCluster))
    kg.g.add((cluster, PLN.name, Literal("居民点1")))
    kg.g.add((cluster, PLN.bsm, Literal("bsm-1")))
    fac = PLN.facility_1
    kg.g.add((fac, RDF.type, PLN.Facility))
    kg.g.add((fac, PLN.name, Literal("设施_1")))
    parcel = PLN.parcel_1
    kg.g.add((parcel, PLN.bsm, Literal("bsm-1")))
    from app.infrastructure.kg.ontology import Relations

    kg.g.add((parcel, Relations.sfWithin, cluster))
    return kg


def _anchors():
    from types import SimpleNamespace

    return [
        SimpleNamespace(
            normalized_name="园寨村",
            role="village",
            source_bsms=["bsm-1"],
            entity_ref="",
            entity_type="ResidentialCluster",
            source_report_ref="r1",
            confidence=0.9,
        ),
        SimpleNamespace(
            normalized_name="祠堂",
            role="facility",
            source_bsms=[],
            entity_ref=str(PLN.facility_1),
            entity_type="Facility",
            source_report_ref="r1",
            confidence=0.8,
        ),
    ]


def test_inject_anchors_replaces_placeholders():
    from app.domain.ground.anchors import _inject_anchors_into_kg

    kg = _kg()
    written = _inject_anchors_into_kg(None, kg, _anchors(), "s-replay")
    assert written >= 2
    assert str(kg.g.value(PLN.settlement_cluster_1, PLN.name)) == "园寨村"
    assert str(kg.g.value(PLN.facility_1, PLN.name)) == "祠堂"


def test_inject_anchors_is_idempotent():
    from app.domain.ground.anchors import _inject_anchors_into_kg

    kg = _kg()
    _inject_anchors_into_kg(None, kg, _anchors(), "s-replay")
    second = _inject_anchors_into_kg(None, kg, _anchors(), "s-replay")
    assert second == 0
    assert str(kg.g.value(PLN.settlement_cluster_1, PLN.name)) == "园寨村"


def test_inject_never_overwrites_real_name():
    from app.domain.ground.anchors import _inject_anchors_into_kg
    from types import SimpleNamespace

    kg = _kg()
    kg.g.set((PLN.settlement_cluster_1, PLN.name, Literal("真实村名")))
    anchors = [
        SimpleNamespace(
            normalized_name="另一个村", role="village", source_bsms=["bsm-1"],
            entity_ref="", entity_type="ResidentialCluster",
            source_report_ref="r1", confidence=0.9,
        )
    ]
    written = _inject_anchors_into_kg(None, kg, anchors, "s-replay")
    assert written == 0
    assert str(kg.g.value(PLN.settlement_cluster_1, PLN.name)) == "真实村名"
