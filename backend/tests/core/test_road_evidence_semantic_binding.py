from types import SimpleNamespace

import pytest
from rdflib import Literal

from app.contracts.domain.l1_contracts import L1Fact
from app.contracts.domain.planning_semantics import RoadPlanningParameters
from app.contracts.evidence.source_semantic_contracts import (
    SourceFeatureSemanticProposal,
    SourceFeatureSemanticProposalBatch,
)
from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)
from app.data.model.canonical import VillageBundle, VillageMetadata
from app.data.model.spatial_types import CurrentLandUseParcel, CurrentRoad
from app.contracts.ports.planning_ports import PlanningPorts
from app.domain.ground.aggregate import ground_aggregate
from app.evidence.identity.flash_source_semantic_classifier import (
    SourceSemanticClassifier,
)
from app.evidence.identity.source_semantic_runtime import classify_source_semantics
from app.evidence.retrieval.evidence_graph import (
    EvidenceGraph,
    enrich_evidence_packet_with_spatial_graph,
)
from app.infrastructure.context.planning_context import PlanningContext
from app.infrastructure.kg.builder import KGBuilder
from app.infrastructure.kg.ontology import PLN
from app.spatial.model.workspace import SpatialWorkspace


@pytest.mark.asyncio
async def test_simulated_minimax_binds_unnamed_road_to_bundle_line() -> None:
    bundle = VillageBundle(
        village_name="金田村",
        metadata=VillageMetadata(adcode_12="441426110000"),
    )
    bundle.add(
        CurrentRoad(
            geometry={
                "type": "MultiLineString",
                "coordinates": [[[116.0, 24.0], [116.01, 24.01]]],
            },
            _raw={
                "source_feature_id": "feature:road:one",
                "source_uri": "roads.geojson",
                "source_content_digest": "sha256:roads",
                "source_geometry_digest": "sha256:road:one",
            },
        )
    )
    bundle.add(
        CurrentLandUseParcel(
            geometry={
                "type": "Polygon",
                "coordinates": [[[115.999, 23.999], [115.999, 24.011], [116.011, 24.011], [116.011, 23.999], [115.999, 23.999]]],
            },
            dlbm="0101",
            area_sqm=1_000_000,
        )
    )
    road = bundle.lines.get("roads_current")[0]
    kg = KGBuilder.build("金田村", bundle)
    road_uri = next(kg.g.subjects(PLN.source_feature_id, Literal("feature:road:one")))
    parcel_bsm = bundle.polygons.get("landuse_current")[0].bsm
    parcel_uri = next(kg.g.subjects(PLN.bsm, Literal(parcel_bsm)))
    assert any(
        relation.object_ref == str(parcel_uri)
        and relation.predicate.endswith("sfIntersects")
        for relation in kg.find_relations(subject_ref=str(road_uri))
    )
    context = SimpleNamespace(
        session_id="road-semantic-binding",
        village_name="金田村",
        workspace=bundle,
        kg=kg,
        kg_version=1,
        location_facts=[],
        l1_fact_records=[
            L1Fact(
                fact_id="l1:road:one",
                statement="金田村现状有村道",
                fact_kind="document_observation",
                dimension_key="location",
                semantic_type="road",
                attributes={
                    "normalized_name": "村道",
                    "role": "road",
                    "location": "金田村",
                },
                source_refs=["report:traffic"],
                source_span="金田村现状有村道",
            )
        ],
        l1_snapshot_ref="artifact://l1/road-semantic",
        data_snapshot=SimpleNamespace(digest=bundle.spatial_snapshot_digest()),
        source_semantic_decisions={},
        source_semantic_diagnostics=[],
        source_semantic_fingerprint="",
        gazetteer=None,
        current_parcels=lambda: [],
    )
    proposal_batch = SourceFeatureSemanticProposalBatch(
        proposals=[
            SourceFeatureSemanticProposal(
                source_feature_id="feature:road:one",
                candidate_ref="l1:l1:road:one:entity",
                supporting_fact_refs=["l1:road:one"],
            )
        ]
    )

    class _Structured:
        async def ainvoke(self, _messages):
            return proposal_batch

    class _SimulatedMinimax:
        calls = 0

        def with_structured_output(self, _response_model, **_kwargs):
            self.calls += 1
            return _Structured()

    simulated = _SimulatedMinimax()
    snapshot, accepted, diagnostics = await classify_source_semantics(
        context,
        enabled=True,
        classifier=SourceSemanticClassifier(llm=simulated),
    )

    assert snapshot is not None
    assert diagnostics == []
    assert simulated.calls == 2
    assert accepted["feature:road:one"].semantic_type == "村道"
    assert snapshot.decisions[0].status == "accepted"

    # A planning claim may carry the typed L1 fact that authorizes the
    # existing-road operation.  The claim is still geometry-free; the
    # accepted source-semantic decision narrows the current bundle feature
    # set before target projection.
    from app.contracts.program import PlanningClaim
    from app.domain.program.claim_adapter import interventions_from_claims
    from app.data.ingestion.compiler.spec_mapper import map_intervention_to_spec

    claim = PlanningClaim(
        claim_id="road-upgrade-from-l1-fact",
        dimension_key="traffic",
        statement="金田村现状村道需要升级。",
        planning_role="spatial_intervention",
        project_package_ref="pkg-road-upgrade-from-l1-fact",
        suggested_category="road",
        suggested_output_kind="line",
        asset_kind="road",
        intervention_action="upgrade",
        suggested_interventions=["村道升级"],
        location_hints=["金田村"],
        source_fact_refs=["l1:road:one"],
        road_parameters=RoadPlanningParameters(
            action="upgrade",
            length_m=100,
        ),
    )
    intervention = interventions_from_claims([claim], dimension_key="traffic")[0]
    assert intervention.spatial_requirements["source_fact_refs"] == ["l1:road:one"]
    spec = map_intervention_to_spec(
        intervention,
        source_features={"road": [road]},
        source_semantic_decisions=context.source_semantic_decisions,
    )
    assert spec is not None
    assert spec.reference is not None
    assert spec.reference.filter["source_feature_ids"] == ["feature:road:one"]

    assert any(
        mention.normalized_name == "村道"
        for scope in context.evidence_graph.semantic_scopes
        for mention in scope.object_mentions
    )
    result = context.evidence_graph.resolve_mention("村道", role="road")

    assert result.status == "resolved"
    assert len(result.candidates) == 1
    candidate = result.candidates[0]
    assert candidate.canonical_name == "村道"
    assert candidate.entity_ref.endswith("road_44142611000000000001")
    assert any(
        candidate.entity_ref in relation_ref
        for relation_ref in candidate.relation_refs
    )
    assert candidate.feature_bsm == road.bsm
    assert candidate.geometry_ref == f"bundle://feature/{road.bsm}"
    assert candidate.source_feature_id == "feature:road:one"
    assert candidate.l1_fact_refs == ["report:traffic", "l1:road:one"]

    planning_context = PlanningContext(
        session_id="road-semantic-ground",
        village_name="金田村",
        workspace=SpatialWorkspace.from_bundle(
            bundle,
            session_id="road-semantic-ground",
        ),
        kg=kg,
        kg_session_ref="road-semantic-ground",
        ports=PlanningPorts(),
    )
    planning_context.l1_fact_records = list(context.l1_fact_records)
    planning_context.l1_snapshot_ref = context.l1_snapshot_ref
    planning_context.source_semantic_decisions = dict(
        context.source_semantic_decisions
    )
    planning_context.evidence_graph = EvidenceGraph.build(planning_context)
    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="金田村村道"),
        planning_context,
        query="金田村村道",
        village_name="金田村",
        entity_scope=["roads"],
    )
    assert len(packet.candidate_refs) == 1
    assert any(
        relation.predicate.endswith("sfIntersects")
        for relation in packet.relation_evidence
    )

    spec = SpatialReferenceSpec(
        type="directional",
        target_id="road-target",
        reference=RefObject(
            kind="entity_type",
            filter={"rdf_type": "Road", "label_contains": "村道"},
        ),
    )
    grounded = ground_aggregate(
        [spec],
        planning_context,
        target_metadata={
            "road-target": {
                "target_kind": "road",
                "expected_output_kind": "line",
            }
        },
        evidence_packets={"road-target": packet},
    )
    assert len(grounded.candidates) == 1
    geometry = grounded.candidates[0].geometry
    assert geometry is not None
    assert geometry.kind == "line"
    assert geometry.granularity == "exact_feature"
    assert geometry.role == "execution_geometry"
    assert geometry.source_feature_ids == ["feature:road:one"]
    assert geometry.feature_bsms == [road.bsm]
