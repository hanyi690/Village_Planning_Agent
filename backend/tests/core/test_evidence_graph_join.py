from types import SimpleNamespace

from rdflib import Literal, RDF, URIRef

from app.contracts.domain.l1_contracts import L1Fact, L1LocationFact
from app.contracts.evidence.evidence_contracts import EvidenceBundle
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.spatial.spatial_reference_contracts import RefObject, SpatialReferenceSpec
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
from app.evidence.retrieval.evidence_graph import (
    EvidenceGraph,
    append_feature_identity_facts,
    enrich_evidence_packet_with_spatial_graph,
)
from app.infrastructure.kg.builder.base import PlanningKG
from app.infrastructure.kg.ontology import EntityTypes, PLN, Relations, SemanticPredicates
from app.infrastructure.kg.spatial_store import SpatialKGEntity, SpatialKGRelation
from app.spatial.model.workspace import SpatialWorkspace


def test_evidence_graph_uses_typed_l1_fact_when_location_facts_are_empty() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000125",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="bundle-digest-typed-l1"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-typed-l1",
        village_name="金田村",
        workspace=workspace,
        location_facts=[],
        l1_fact_records=[
            L1Fact(
                fact_id="l1:fact:typed-hall",
                statement="社前村现状设施包括祠堂",
                confidence=0.96,
                fact_kind="document_observation",
                dimension_key="socio_economic",
                subject_scope="祠堂",
                semantic_type="facility",
                attributes={
                    "normalized_name": "祠堂",
                    "role": "facility",
                    "location": "社前村",
                },
                source_refs=["report:current#socio_economic"],
                source_span="社前村现状设施包括祠堂",
            )
        ],
        kg=None,
        kg_version=1,
        l1_snapshot_ref="artifact://l1/typed-l1",
        data_snapshot=SimpleNamespace(digest="bundle-digest-typed-l1"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    result = context.evidence_graph.query_facility_bsms("社前村", "祠堂")

    assert result.status == "resolved"
    assert [candidate.feature_bsm for candidate in result.candidates] == [
        point.bsm
    ]
    assert any(
        item.get("step") == "evidence_graph_facility_join"
        for item in result.query_trace
    )


def test_l1_fact_with_multiple_villages_does_not_silently_anchor_first_village() -> None:
    village_a = SimpleNamespace(
        name="甲村",
        aliases=[],
        bsms=["parcel-a"],
        entity_uri="entity:village-a",
    )
    village_b = SimpleNamespace(
        name="乙村",
        aliases=[],
        bsms=["parcel-b"],
        entity_uri="entity:village-b",
    )
    villages = {"甲村": village_a, "乙村": village_b}
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="bundle-multiple-villages"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-multiple-villages-l1",
        village_name="总村",
        workspace=workspace,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                spatial_hint="",
                source_span="甲村、乙村均有祠堂设施",
                source_report_ref="report:current",
                source_authority_score=1.0,
                semantic_match_score=0.95,
                spatial_support_score=0.95,
                retrieval_score=0.95,
            )
        ],
        kg=None,
        kg_version=1,
        l1_snapshot_ref="l1:multiple-villages",
        data_snapshot=SimpleNamespace(digest="bundle-multiple-villages"),
        gazetteer=SimpleNamespace(
            entries=[village_a, village_b],
            resolve=lambda name, fuzzy=False: villages.get(str(name)),
        ),
    )

    index = PlaceEvidenceIndex.build(context)
    l1_entries = [
        entry
        for entry in index.entries
        if entry.canonical_name == "祠堂"
        and "l1_fact" in entry.provenance
    ]

    assert len(l1_entries) == 1
    assert any(
        item.startswith("village_anchor_ambiguous:")
        for item in l1_entries[0].provenance
    )
    assert l1_entries[0].anchor_bsms == []
    assert l1_entries[0].source_bsms == []


def test_evidence_graph_answers_village_facility_bsm_without_geometry_payload() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000123",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="bundle-digest-1"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-test",
        village_name="社前村",
        workspace=workspace,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                spatial_hint="社前村",
                confidence=0.95,
            )
        ],
        kg=None,
        kg_version=3,
        l1_snapshot_ref="artifact://l1/snapshot-1",
        data_snapshot=SimpleNamespace(digest="bundle-digest-1"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )
    packet = EvidencePacket(request="社前村祠堂的BSM")

    enriched = enrich_evidence_packet_with_spatial_graph(
        packet,
        context,
        query="社前村祠堂的BSM",
        village_name="社前村",
    )

    assert len(enriched.candidate_refs) == 1
    ref = enriched.candidate_refs[0]
    assert ref.identity.bundle_feature_bsm == "44142621100000000123"
    assert ref.identity.admin_code_12 == "441426211000"
    assert ref.identity.sequence_code_8 == "00000123"
    assert ref.geometry_ref == "bundle://feature/44142621100000000123"
    assert "116.0" not in ref.model_dump_json()
    assert enriched.bundle_snapshot_digest == "bundle-digest-1"
    assert enriched.kg_version == "3"
    assert enriched.l1_snapshot_ref == "artifact://l1/snapshot-1"


def test_evidence_graph_returns_facility_bsm_and_nearby_parcel_bsm() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000123",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    parcel = SimpleNamespace(
        bsm="44142621100000009999",
        area_sqm=40_000.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [115.999, 23.999],
                [116.001, 23.999],
                [116.001, 24.001],
                [115.999, 24.001],
                [115.999, 23.999],
            ]],
        },
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [parcel],
        snapshot=SimpleNamespace(digest="bundle-digest-join"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-facility-parcel-test",
        village_name="社前村",
        workspace=workspace,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                spatial_hint="社前村",
                confidence=0.95,
            )
        ],
        kg=None,
        kg_version=1,
        l1_snapshot_ref="artifact://l1/facility-parcel",
        data_snapshot=SimpleNamespace(digest="bundle-digest-join"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )

    result = context.evidence_graph.query_facility_bsms("社前村", "祠堂")

    assert result.status == "resolved"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.feature_bsm == "44142621100000000123"
    assert candidate.related_parcel_bsms == ["44142621100000009999"]
    assert candidate.geometry_ref == "bundle://feature/44142621100000000123"


def test_facility_scope_can_use_gazetteer_parcel_join_without_l1_anchor() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000123",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    parcel = SimpleNamespace(
        bsm="44142621100000009999",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [115.999, 23.999], [116.001, 23.999],
                [116.001, 24.001], [115.999, 24.001],
                [115.999, 23.999],
            ]],
        },
    )
    village = SimpleNamespace(
        name="社前村",
        bsms=[parcel.bsm],
        aliases=[],
        confidence=0.95,
    )
    gazetteer = SimpleNamespace(
        entries=[village],
        resolve=lambda name, fuzzy=False: (
            village if str(name).replace("自然村", "").replace("村", "") == "社前" else None
        ),
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(
            get=lambda key: [parcel] if key == "landuse_current" else []
        ),
        current_parcels=lambda: [parcel],
        snapshot=SimpleNamespace(digest="bundle-digest-gazetteer-scope"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-gazetteer-scope",
        village_name="金田村",
        workspace=workspace,
        location_facts=[],
        kg=None,
        kg_version=1,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-digest-gazetteer-scope"),
        gazetteer=gazetteer,
    )
    graph = EvidenceGraph(context, index=PlaceEvidenceIndex.build(context))

    result = graph.query_facility_bsms("社前村", "祠堂")

    assert result.status == "resolved"
    assert [candidate.feature_bsm for candidate in result.candidates] == [point.bsm]
    assert result.candidates[0].related_parcel_bsms == [parcel.bsm]


def test_facility_scope_can_use_explicit_kg_village_relation() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000124",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    village_entity = SpatialKGEntity(
        entity_ref="kg:village:sheqian",
        entity_type="village",
        canonical_name="社前村",
    )
    relation = SpatialKGRelation(
        relation_id="relation:facility-village",
        subject_ref="poi:祠堂",
        predicate="located_in",
        object_ref="kg:village:sheqian",
        metric_value=None,
        metric_unit=None,
        tolerance=None,
        crs="EPSG:4326",
        method="test",
        provenance_refs=[],
    )
    kg = SimpleNamespace(
        find_entities=lambda **kwargs: [village_entity]
        if (
            kwargs.get("name") in {"社前村", "社前自然村"}
            or kwargs.get("entity_ref") == "kg:village:sheqian"
        )
        else [],
        find_relations=lambda **kwargs: [relation]
        if kwargs.get("subject_ref") == "poi:祠堂"
        else [],
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="bundle-digest-kg-scope"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-kg-scope",
        village_name="金田村",
        workspace=workspace,
        location_facts=[],
        kg=kg,
        kg_version=1,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-digest-kg-scope"),
        gazetteer=None,
    )
    graph = EvidenceGraph(context, index=PlaceEvidenceIndex.build(context))

    result = graph.query_facility_bsms("社前村", "祠堂")

    assert result.status == "resolved"
    assert result.candidates[0].feature_bsm == point.bsm


def test_evidence_graph_prefers_natural_village_scope_inside_admin_context() -> None:
    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000123",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="bundle-digest-admin"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-admin-test",
        village_name="金田村",
        workspace=workspace,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                spatial_hint="社前村",
                confidence=0.95,
            )
        ],
        kg=None,
        kg_version=1,
        l1_snapshot_ref="artifact://l1/admin-snapshot",
        data_snapshot=SimpleNamespace(digest="bundle-digest-admin"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )

    enriched = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="社前村祠堂的BSM"),
        context,
        query="社前村祠堂的BSM",
        village_name="金田村",
    )

    assert len(enriched.candidate_refs) == 1
    assert enriched.candidate_refs[0].identity.bundle_feature_bsm == "44142621100000000123"
    assert any(
        item.get("step") == "village_scope_hint" and item.get("value") == "社前村"
        for item in enriched.query_trace
    )


def test_evidence_graph_joins_topology_from_the_same_kg() -> None:
    kg = PlanningKG("社前村")
    facility_ref = URIRef("http://example.test/facility-1")
    village_ref = URIRef("http://example.test/village-1")
    kg.g.add((facility_ref, RDF.type, EntityTypes.Facility))
    kg.g.add((facility_ref, PLN.name, Literal("祠堂")))
    kg.g.add((facility_ref, PLN.bsm, Literal("44142621100000000123")))
    kg.g.add((village_ref, RDF.type, EntityTypes.ResidentialCluster))
    kg.g.add((village_ref, PLN.name, Literal("社前村")))
    kg.g.add((village_ref, PLN.bsm, Literal("44142621100000000001")))
    kg.g.add((facility_ref, Relations.sfWithin, village_ref))
    kg.rebuild_spatial_index()

    point = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm="44142621100000000123",
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="digest"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-topology-test",
        village_name="社前村",
        workspace=workspace,
        location_facts=[
            L1LocationFact(
                mention="祠堂",
                normalized_name="祠堂",
                role="facility",
                spatial_hint="社前村",
                confidence=0.95,
            )
        ],
        kg=kg,
        kg_version=1,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="digest"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )
    direct = context.evidence_graph.query_facility_bsms("社前村", "祠堂")
    enriched = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="社前村祠堂的BSM"),
        context,
        query="社前村祠堂的BSM",
        village_name="社前村",
    )

    assert len(enriched.candidate_refs) == 1
    assert len(enriched.relation_evidence) == 1
    relation = enriched.relation_evidence[0]
    assert relation.predicate == str(Relations.sfWithin)
    assert relation.object.identity.bundle_feature_bsm == "44142621100000000001"
    assert str(relation.relation_id) in direct.candidates[0].relation_refs
    relation_bundle = append_feature_identity_facts(
        EvidenceBundle(request="社前村祠堂的BSM"),
        enriched,
    )
    relation_fact = next(
        fact for fact in relation_bundle.facts if fact.fact_type == "spatial_relation"
    )
    assert relation_fact.fields["predicate"] == "sfWithin"
    assert relation_fact.fields["subject_bsm"] == "44142621100000000123"


def test_llm_topology_spec_filters_existing_bundle_candidates_via_kg_relation() -> None:
    road_bsm = "44142621100000008101"
    facility_near_bsm = "44142621100000008102"
    facility_far_bsm = "44142621100000008103"
    kg = PlanningKG("甲村")
    road_ref = URIRef("http://example.test/road-1")
    near_ref = URIRef("http://example.test/facility-near")
    far_ref = URIRef("http://example.test/facility-far")
    for entity_ref, entity_type, name, bsm in (
        (road_ref, EntityTypes.Road, "道路甲", road_bsm),
        (near_ref, EntityTypes.Facility, "祠堂", facility_near_bsm),
        (far_ref, EntityTypes.Facility, "祠堂", facility_far_bsm),
    ):
        kg.g.add((entity_ref, RDF.type, entity_type))
        kg.g.add((entity_ref, PLN.name, Literal(name)))
        kg.g.add((entity_ref, PLN.bsm, Literal(bsm)))
    kg.g.add((road_ref, Relations.sfIntersects, near_ref))
    kg.rebuild_spatial_index()

    near = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm=facility_near_bsm,
        geometry={"type": "Point", "coordinates": [116.0, 24.0]},
    )
    far = SimpleNamespace(
        text="祠堂",
        category="现状设施点",
        layer_type="facilities_current",
        bsm=facility_far_bsm,
        geometry={"type": "Point", "coordinates": [116.1, 24.1]},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [near, far] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="topology-semantic-digest"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-llm-topology-test",
        village_name="甲村",
        workspace=workspace,
        location_facts=[],
        kg=kg,
        kg_version=1,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="topology-semantic-digest"),
        gazetteer=None,
    )
    graph = EvidenceGraph(context, index=PlaceEvidenceIndex.build(context))
    spec = SpatialReferenceSpec(
        type="topological",
        topo="sfIntersects",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "道路甲"},
        ),
    )

    result = graph.query_facility_bsms(
        "甲村",
        "祠堂",
        spatial_spec=spec,
    )

    assert result.status == "resolved"
    assert [candidate.feature_bsm for candidate in result.candidates] == [
        facility_near_bsm
    ]
    topology_trace = [
        item for item in result.query_trace
        if item.get("step") == "kg_topology_qualifier"
    ]
    assert topology_trace
    assert topology_trace[-1]["items"][0]["evidence_available"] is True
    assert topology_trace[-1]["candidate_count_after"] == 1


def test_ground_resolver_uses_kg_topology_result_before_anchor_bundle_associations() -> None:
    road_bsm = "44142621100000008201"
    parcel_near_bsm = "44142621100000008202"
    parcel_other_bsm = "44142621100000008203"
    kg = PlanningKG("甲村")
    road_ref = URIRef("http://example.test/road-topology-ground")
    near_ref = URIRef("http://example.test/parcel-topology-near")
    other_ref = URIRef("http://example.test/parcel-topology-other")
    for entity_ref, entity_type, name, bsm in (
        (road_ref, EntityTypes.Road, "道路甲", road_bsm),
        (near_ref, EntityTypes.Parcel, "地块甲", parcel_near_bsm),
        (other_ref, EntityTypes.Parcel, "地块乙", parcel_other_bsm),
    ):
        kg.g.add((entity_ref, RDF.type, entity_type))
        kg.g.add((entity_ref, PLN.name, Literal(name)))
        kg.g.add((entity_ref, PLN.bsm, Literal(bsm)))
    kg.g.add((road_ref, Relations.sfIntersects, near_ref))
    kg.rebuild_spatial_index()

    parcel_near = SimpleNamespace(
        bsm=parcel_near_bsm,
        area_sqm=10_000.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        },
    )
    parcel_other = SimpleNamespace(
        bsm=parcel_other_bsm,
        area_sqm=10_000.0,
        geometry={
            "type": "Polygon",
            "coordinates": [[[2.0, 0.0], [3.0, 0.0], [3.0, 1.0], [2.0, 1.0], [2.0, 0.0]]],
        },
    )
    road = SimpleNamespace(
        bsm=road_bsm,
        text="道路甲",
        layer_type="roads_current",
        geometry={"type": "LineString", "coordinates": [[0.5, 0.5], [2.5, 0.5]]},
        _raw={"source_feature_id": "road-topology-ground"},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        lines=SimpleNamespace(
            get=lambda key: [road] if key == "roads_current" else []
        ),
        polygons=SimpleNamespace(
            get=lambda key: [parcel_near, parcel_other]
            if key == "landuse_current"
            else []
        ),
        current_parcels=lambda: [parcel_near, parcel_other],
        snapshot=SimpleNamespace(digest="ground-topology-digest"),
    )
    from app.infrastructure.kg.adapters.spatial_query_adapter import KGSpatialQueryAdapter
    from app.spatial.grounding.resolver import SpatialResolver

    context = SimpleNamespace(
        session_id="ground-topology-resolver-test",
        village_name="甲村",
        workspace=workspace,
        current_parcels=lambda: [parcel_near, parcel_other],
        location_facts=[],
        kg=kg,
        gazetteer=None,
        constraint_index=None,
        evidence_graph=EvidenceGraph(
            SimpleNamespace(
                session_id="ground-topology-resolver-test",
                village_name="甲村",
                workspace=workspace,
                current_parcels=lambda: [parcel_near, parcel_other],
                location_facts=[],
                kg=kg,
                gazetteer=None,
                data_snapshot=SimpleNamespace(digest="ground-topology-digest"),
                kg_version=1,
                l1_snapshot_ref="",
            ),
            index=PlaceEvidenceIndex.build(
                SimpleNamespace(
                    workspace=workspace,
                    current_parcels=lambda: [parcel_near, parcel_other],
                    location_facts=[],
                    kg=kg,
                    gazetteer=None,
                    village_name="甲村",
                    data_snapshot=SimpleNamespace(digest="ground-topology-digest"),
                )
            ),
        ),
        ports=SimpleNamespace(spatial_query=KGSpatialQueryAdapter(kg)),
    )
    context.evidence_graph.context = context
    spec = SpatialReferenceSpec(
        type="topological",
        topo="sfIntersects",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "道路甲"},
        ),
        target_id="target-ground-topology",
    )

    resolved = SpatialResolver(context).resolve_spec(spec)

    assert resolved.final_bsms == [parcel_near_bsm]
    assert "+kg_topology" in str(resolved.provenance.get("path", ""))
    assert resolved.provenance.get("relation_refs")
    assert "http://example.test/parcel-topology-near" in resolved.provenance.get(
        "entity_refs", []
    )


def test_evidence_graph_promotes_bundle_identity_to_answer_fact() -> None:
    from app.contracts.evidence.feature_identity_contracts import (
        BundleFeatureIdentity,
        FeatureEvidenceRef,
    )

    packet = EvidencePacket(
        request="社前村祠堂的BSM",
        candidate_refs=[
            FeatureEvidenceRef(
                identity=BundleFeatureIdentity(
                    bundle_feature_bsm="44142621100000000123",
                    source_feature_id="bundle:facility:44142621100000000123",
                    source_layer="current_facility",
                    bsm_kind="source",
                    bundle_snapshot_digest="digest-1",
                ),
                geometry_ref="bundle://feature/44142621100000000123",
                geometry_authority="bundle",
                related_parcel_bsms=["44142621100000009999"],
                provenance_refs=["l1:fact:祠堂"],
                source_authority_score=1.0,
                semantic_match_score=0.95,
                spatial_support_score=0.95,
                retrieval_score=0.95,
            )
        ],
    )

    result = append_feature_identity_facts(
        EvidenceBundle(request="社前村祠堂的BSM"),
        packet,
    )

    fact = result.facts[0]
    assert fact.fact_type == "bundle_feature_identity"
    assert fact.fields["bundle_feature_bsm"] == "44142621100000000123"
    assert fact.feature_bsm == "44142621100000000123"
    assert fact.related_parcel_bsms == ["44142621100000009999"]
    assert fact.spatial_refs == ["bundle://feature/44142621100000000123"]
    assert "116" not in fact.model_dump_json()


def test_evidence_graph_routes_non_facility_spatial_entity_by_scope() -> None:
    kg = PlanningKG("社前村")
    road_ref = URIRef("http://example.test/road-1")
    kg.g.add((road_ref, RDF.type, EntityTypes.Road))
    kg.g.add((road_ref, PLN.name, Literal("社前路")))
    kg.g.add((road_ref, PLN.bsm, Literal("44142621100000000222")))
    kg.g.add((road_ref, PLN.lon, Literal("116.01")))
    kg.g.add((road_ref, PLN.lat, Literal("24.01")))
    kg.g.add((road_ref, SemanticPredicates.gis_type_ref, Literal("roads_current")))
    kg.rebuild_spatial_index()

    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="road-digest"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-road-test",
        village_name="社前村",
        workspace=workspace,
        location_facts=[],
        kg=kg,
        kg_version=1,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="road-digest"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )

    enriched = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="社前村社前路的道路 BSM"),
        context,
        query="社前村社前路的道路 BSM",
        village_name="社前村",
        entity_scope=["roads"],
    )

    assert len(enriched.candidate_refs) == 1
    assert enriched.candidate_refs[0].identity.bundle_feature_bsm == "44142621100000000222"
    bundle = append_feature_identity_facts(
        EvidenceBundle(request="社前村社前路的道路 BSM"),
        enriched,
    )
    assert bundle.facts[0].statement.startswith("社前路")
    assert "BSM 为 44142621100000000222" in bundle.facts[0].statement
    assert "设施要素" not in bundle.facts[0].statement

    scope_only = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="社前村的道路"),
        context,
        query="社前村的道路",
        village_name="社前村",
        entity_scope=["roads"],
    )
    assert [
        ref.identity.bundle_feature_bsm for ref in scope_only.candidate_refs
    ] == ["44142621100000000222"]


def test_evidence_graph_indexes_named_bundle_road_without_kg_name() -> None:
    road = SimpleNamespace(
        bsm="44142621100000000333",
        text="入村道路",
        geometry={
            "type": "LineString",
            "coordinates": [[116.0, 24.0], [116.002, 24.0]],
        },
        _raw={"source_feature_id": "road-source-1"},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        lines=SimpleNamespace(
            get=lambda key: [road] if key == "roads_current" else []
        ),
        polygons=SimpleNamespace(get=lambda key: []),
        current_parcels=lambda: [],
        snapshot=SimpleNamespace(digest="bundle-road-digest"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-bundle-road-test",
        village_name="社前村",
        workspace=workspace,
        location_facts=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-road-digest"),
        gazetteer=None,
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )

    enriched = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="入村道路的 BSM"),
        context,
        query="入村道路的 BSM",
        village_name="社前村",
        entity_scope=["roads"],
    )

    assert len(enriched.candidate_refs) == 1
    ref = enriched.candidate_refs[0]
    assert ref.identity.bundle_feature_bsm == "44142621100000000333"
    assert ref.identity.source_feature_id == "road-source-1"
    assert ref.geometry_ref == "bundle://feature/44142621100000000333"


def test_scope_only_road_query_uses_bundle_parcel_topology_to_isolate_village() -> None:
    parcel_a = SimpleNamespace(
        bsm="44142621100000001001",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        },
    )
    parcel_b = SimpleNamespace(
        bsm="44142621100000001002",
        geometry={
            "type": "Polygon",
            "coordinates": [[[10.0, 0.0], [11.0, 0.0], [11.0, 1.0], [10.0, 1.0], [10.0, 0.0]]],
        },
    )
    road_a = SimpleNamespace(
        bsm="44142621100000002001",
        text="村道甲",
        geometry={"type": "LineString", "coordinates": [[0.1, 0.5], [0.9, 0.5]]},
        _raw={"source_feature_id": "road-a"},
    )
    road_b = SimpleNamespace(
        bsm="44142621100000002002",
        text="村道乙",
        geometry={"type": "LineString", "coordinates": [[10.1, 0.5], [10.9, 0.5]]},
        _raw={"source_feature_id": "road-b"},
    )
    village_a = SimpleNamespace(name="甲村", aliases=[], bsms=[parcel_a.bsm])
    village_b = SimpleNamespace(name="乙村", aliases=[], bsms=[parcel_b.bsm])
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        lines=SimpleNamespace(
            get=lambda key: [road_a, road_b] if key == "roads_current" else []
        ),
        polygons=SimpleNamespace(
            get=lambda key: [parcel_a, parcel_b] if key == "landuse_current" else []
        ),
        current_parcels=lambda: [parcel_a, parcel_b],
        snapshot=SimpleNamespace(digest="bundle-road-scope"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-road-scope",
        village_name="总村",
        workspace=workspace,
        current_parcels=lambda: [parcel_a, parcel_b],
        location_facts=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-road-scope"),
        gazetteer=SimpleNamespace(entries=[village_a, village_b]),
    )
    context.evidence_graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="甲村的道路"),
        context,
        query="甲村的道路",
        village_name="总村",
        entity_scope=["roads"],
    )

    assert [
        ref.identity.bundle_feature_bsm for ref in packet.candidate_refs
    ] == [road_a.bsm]


def test_directional_scope_query_filters_same_village_roads_by_bundle_bbox_topology() -> None:
    parcel_west = SimpleNamespace(
        bsm="44142621100000003001",
        geometry={
            "type": "Polygon",
            "coordinates": [[[-0.008, -0.002], [-0.004, -0.002], [-0.004, 0.002], [-0.008, 0.002], [-0.008, -0.002]]],
        },
    )
    parcel_east = SimpleNamespace(
        bsm="44142621100000003002",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.004, -0.002], [0.008, -0.002], [0.008, 0.002], [0.004, 0.002], [0.004, -0.002]]],
        },
    )
    road_west = SimpleNamespace(
        bsm="44142621100000004001",
        text="西侧道路",
        geometry={"type": "LineString", "coordinates": [[-0.007, 0.0], [-0.005, 0.0]]},
        _raw={"source_feature_id": "west-road"},
    )
    road_east = SimpleNamespace(
        bsm="44142621100000004002",
        text="东侧道路",
        geometry={"type": "LineString", "coordinates": [[0.005, 0.0], [0.007, 0.0]]},
        _raw={"source_feature_id": "east-road"},
    )
    village = SimpleNamespace(
        name="甲村",
        aliases=[],
        bsms=[parcel_west.bsm, parcel_east.bsm],
        centroid=(0.0, 0.0),
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        lines=SimpleNamespace(
            get=lambda key: [road_west, road_east] if key == "roads_current" else []
        ),
        polygons=SimpleNamespace(
            get=lambda key: [parcel_west, parcel_east] if key == "landuse_current" else []
        ),
        current_parcels=lambda: [parcel_west, parcel_east],
        snapshot=SimpleNamespace(digest="bundle-directional-scope"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-directional-scope",
        village_name="甲村",
        workspace=workspace,
        current_parcels=lambda: [parcel_west, parcel_east],
        location_facts=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-directional-scope"),
        gazetteer=SimpleNamespace(entries=[village]),
    )
    context.evidence_graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="甲村西侧的道路"),
        context,
        query="甲村西侧的道路",
        village_name="甲村",
        entity_scope=["roads"],
    )

    assert [
        ref.identity.bundle_feature_bsm for ref in packet.candidate_refs
    ] == [road_west.bsm]
    assert any(
        trace.get("step") == "directional_scope_hint"
        and trace.get("value") == "west"
        for trace in packet.query_trace
    )


def test_llm_spatial_spec_filters_fuzzy_direction_without_regex_phrase() -> None:
    parcel_west = SimpleNamespace(
        bsm="44142621100000007001",
        geometry={
            "type": "Polygon",
            "coordinates": [[[-0.008, -0.002], [-0.004, -0.002], [-0.004, 0.002], [-0.008, 0.002], [-0.008, -0.002]]],
        },
    )
    parcel_east = SimpleNamespace(
        bsm="44142621100000007002",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.004, -0.002], [0.008, -0.002], [0.008, 0.002], [0.004, 0.002], [0.004, -0.002]]],
        },
    )
    road_west = SimpleNamespace(
        bsm="44142621100000008001",
        text="道路甲",
        geometry={"type": "LineString", "coordinates": [[-0.007, 0.0], [-0.005, 0.0]]},
        _raw={"source_feature_id": "fuzzy-west-road"},
    )
    road_east = SimpleNamespace(
        bsm="44142621100000008002",
        text="道路乙",
        geometry={"type": "LineString", "coordinates": [[0.005, 0.0], [0.007, 0.0]]},
        _raw={"source_feature_id": "fuzzy-east-road"},
    )
    village = SimpleNamespace(
        name="甲村",
        aliases=[],
        bsms=[parcel_west.bsm, parcel_east.bsm],
        centroid=(0.0, 0.0),
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        lines=SimpleNamespace(
            get=lambda key: [road_west, road_east] if key == "roads_current" else []
        ),
        polygons=SimpleNamespace(
            get=lambda key: [parcel_west, parcel_east] if key == "landuse_current" else []
        ),
        current_parcels=lambda: [parcel_west, parcel_east],
        snapshot=SimpleNamespace(digest="bundle-llm-fuzzy-direction"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-llm-fuzzy-direction",
        village_name="甲村",
        workspace=workspace,
        current_parcels=lambda: [parcel_west, parcel_east],
        location_facts=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-llm-fuzzy-direction"),
        gazetteer=SimpleNamespace(entries=[village]),
    )
    context.evidence_graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )
    spec = SpatialReferenceSpec(
        type="composed",
        op="and",
        children=[
            SpatialReferenceSpec(type="directional", direction="W"),
            SpatialReferenceSpec(
                type="attributive",
                reference=RefObject(
                    kind="entity_type",
                    filter={"label_contains": "道路"},
                ),
            ),
        ],
    )

    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="甲村靠山一侧的一条道路"),
        context,
        query="甲村靠山一侧的一条道路",
        village_name="甲村",
        entity_scope=["roads"],
        spatial_spec=spec,
    )

    assert [
        ref.identity.bundle_feature_bsm for ref in packet.candidate_refs
    ] == [road_west.bsm]
    assert any(
        trace.get("step") == "directional_scope_hint"
        and trace.get("parser") == "llm_structured"
        for trace in packet.query_trace
    )


def test_multi_village_same_name_facility_stays_ambiguous() -> None:
    parcel_a = SimpleNamespace(
        bsm="44142621100000005001",
        geometry={
            "type": "Polygon",
            "coordinates": [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0], [0.0, 1.0], [0.0, 0.0]]],
        },
    )
    parcel_b = SimpleNamespace(
        bsm="44142621100000005002",
        geometry={
            "type": "Polygon",
            "coordinates": [[[10.0, 0.0], [11.0, 0.0], [11.0, 1.0], [10.0, 1.0], [10.0, 0.0]]],
        },
    )
    point_a = SimpleNamespace(
        text="祠堂",
        layer_type="facilities_current",
        bsm="44142621100000006001",
        geometry={"type": "Point", "coordinates": [0.5, 0.5]},
    )
    point_b = SimpleNamespace(
        text="祠堂",
        layer_type="facilities_current",
        bsm="44142621100000006002",
        geometry={"type": "Point", "coordinates": [10.5, 0.5]},
    )
    village_a = SimpleNamespace(name="甲村", aliases=[], bsms=[parcel_a.bsm])
    village_b = SimpleNamespace(name="乙村", aliases=[], bsms=[parcel_b.bsm])
    villages = {"甲村": village_a, "乙村": village_b}
    workspace = SimpleNamespace(
        points=SimpleNamespace(
            get=lambda key: [point_a, point_b] if key == "facilities_current" else []
        ),
        polygons=SimpleNamespace(
            get=lambda key: [parcel_a, parcel_b] if key == "landuse_current" else []
        ),
        current_parcels=lambda: [parcel_a, parcel_b],
        snapshot=SimpleNamespace(digest="bundle-multi-village-facility"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-multi-village-facility",
        village_name="总村",
        workspace=workspace,
        current_parcels=lambda: [parcel_a, parcel_b],
        location_facts=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="",
        data_snapshot=SimpleNamespace(digest="bundle-multi-village-facility"),
        gazetteer=SimpleNamespace(
            entries=[village_a, village_b],
            resolve=lambda name, fuzzy=False: villages.get(
                str(name).replace("自然村", "").replace("村", "") + "村"
            ),
        ),
    )
    context.evidence_graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )

    result = context.evidence_graph.query_facility_bsms(
        "甲村、乙村",
        "祠堂",
    )

    assert result.status == "ambiguous"
    assert {
        candidate.feature_bsm for candidate in result.candidates
    } == {point_a.bsm, point_b.bsm}
    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="甲村祠堂的BSM"),
        context,
        query="甲村、乙村祠堂的BSM",
        village_name="甲村、乙村",
        entity_scope=["facilities"],
    )
    assert packet.ambiguity_status == "multiple"


def test_evidence_graph_resolves_l1_scope_and_landuse_semantics_to_parcel_bsm() -> None:
    parcel = SimpleNamespace(
        bsm="44142621100000000444",
        dlbm="0101",
        zone_type="耕地",
        planning_zone="农田保护区",
        layer_type="landuse_current",
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [116.0, 24.0], [116.01, 24.0], [116.01, 24.01],
                [116.0, 24.01], [116.0, 24.0],
            ]],
        },
        _raw={"source_feature_id": "parcel-source-1"},
    )
    workspace = SimpleNamespace(
        points=SimpleNamespace(get=lambda key: []),
        polygons=SimpleNamespace(
            get=lambda key: [parcel] if key == "landuse_current" else []
        ),
        current_parcels=lambda: [parcel],
        snapshot=SimpleNamespace(digest="parcel-semantic-digest"),
    )
    context = SimpleNamespace(
        session_id="evidence-graph-parcel-semantic-test",
        village_name="金田村",
        workspace=workspace,
        location_facts=[],
        kg=None,
        kg_version=0,
        l1_snapshot_ref="artifact://l1/parcel-semantic",
        data_snapshot=SimpleNamespace(digest="parcel-semantic-digest"),
        gazetteer=SimpleNamespace(
            entries=[
                SimpleNamespace(
                    name="社前村",
                    bsms=[parcel.bsm],
                    aliases=[],
                    confidence=0.95,
                )
            ]
        ),
    )
    context.evidence_graph = EvidenceGraph(
        context, index=PlaceEvidenceIndex.build(context)
    )

    assert context.evidence_graph.candidate_bsms("社前村耕地", role="unknown") == [
        parcel.bsm
    ]

    enriched = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="社前村耕地的地块BSM"),
        context,
        query="社前村耕地的地块BSM",
        village_name="金田村",
        entity_scope=["parcels"],
    )

    assert len(enriched.candidate_refs) == 1
    ref = enriched.candidate_refs[0]
    assert ref.identity.bundle_feature_bsm == parcel.bsm
    assert ref.identity.source_feature_id == "parcel-source-1"
    assert ref.geometry_ref == f"bundle://feature/{parcel.bsm}"
    bundle = append_feature_identity_facts(
        EvidenceBundle(request="社前村耕地的地块BSM"),
        enriched,
    )
    assert bundle.facts[0].statement.startswith("耕地")
    assert "BSM 为 44142621100000000444" in bundle.facts[0].statement
