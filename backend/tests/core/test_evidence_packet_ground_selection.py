from types import SimpleNamespace

from app.contracts.evidence.evidence_packet_contracts import EvidencePacket
from app.contracts.evidence.feature_identity_contracts import (
    BundleFeatureIdentity,
    FeatureEvidenceRef,
)
from app.contracts.spatial.spatial_reference_contracts import (
    RefObject,
    SpatialReferenceSpec,
)
from app.evidence.index.place_evidence_index import PlaceEvidenceIndex
from app.evidence.index.evidence_scorer import score_candidate
from app.evidence.retrieval.evidence_graph import (
    EvidenceGraph,
    enrich_evidence_packet_with_spatial_graph,
)
from app.spatial.grounding.resolver import SpatialResolver
from app.workflow.stages.ground import _ground_packet_query
from app.contracts.ports.place_resolution_contracts import PlaceEvidenceEntry
from app.domain.ground.aggregate import ground_aggregate


def _parcel(bsm: str, x0: float) -> SimpleNamespace:
    return SimpleNamespace(
        bsm=bsm,
        geometry={
            "type": "Polygon",
            "coordinates": [[
                [x0, 24.0],
                [x0 + 0.01, 24.0],
                [x0 + 0.01, 24.01],
                [x0, 24.01],
                [x0, 24.0],
            ]],
        },
        area_sqm=1_000_000.0,
    )


def _point(
    bsm: str,
    source_feature_id: str,
    x: float,
    *,
    text: str,
    address: str = "",
) -> SimpleNamespace:
    return SimpleNamespace(
        bsm=bsm,
        text=text,
        address=address,
        category="",
        properties={"address": address},
        geometry={"type": "Point", "coordinates": [x, 24.005]},
        _raw={"source_feature_id": source_feature_id},
    )


def _context(points: list[SimpleNamespace], parcels: list[SimpleNamespace]):
    def find_feature_by_bsm(bsm: str):
        for layer, features in {
            "facilities_current": points,
            "geological_hazard_points": points,
            "landuse_current": parcels,
        }.items():
            for feature in features:
                if str(feature.bsm) == str(bsm):
                    geometry_kind = "point" if feature in points else "polygon"
                    return geometry_kind, layer, feature
        return None

    workspace = SimpleNamespace(
        points={
            "facilities_current": points,
            "annotations_current": [],
            "geological_hazard_points": points,
        },
        lines={},
        polygons={"landuse_current": parcels},
        metadata=SimpleNamespace(crs="EPSG:4326"),
        find_feature_by_bsm=find_feature_by_bsm,
    )
    gazetteer = SimpleNamespace(
        entries=[],
        resolve=lambda _name, fuzzy=False: None,
    )
    context = SimpleNamespace(
        session_id="packet-selection-test",
        village_name="金田村",
        workspace=workspace,
        gazetteer=gazetteer,
        kg=None,
        kg_version=1,
        location_facts=[],
        l1_fact_records=[],
        l1_snapshot_ref="artifact://l1/test",
        data_snapshot=SimpleNamespace(digest="bundle:test"),
        constraint_index=None,
        ports=SimpleNamespace(spatial_query=None),
        current_parcels=lambda: parcels,
    )
    return context


def _feature_ref(
    point: SimpleNamespace,
    parcel_bsm: str,
    *,
    role: str = "facility",
    source_layer: str = "facilities_current",
) -> FeatureEvidenceRef:
    return FeatureEvidenceRef(
        identity=BundleFeatureIdentity(
            bundle_feature_bsm=point.bsm,
            canonical_name=point.text,
            entity_type=role,
            role=role,
            aliases=[point.address] if point.address else [],
            source_feature_id=point._raw["source_feature_id"],
            source_layer=source_layer,
            source_bsm=point.bsm,
            bsm_kind="source",
            bundle_snapshot_digest="bundle:test",
        ),
        entity_refs=[f"kg:{role}:{point.bsm}"],
        geometry_ref=f"bundle://feature/{point.bsm}",
        related_parcel_bsms=[parcel_bsm],
        provenance_refs=[f"bundle:{source_layer}"],
        source_authority_score=1.0,
        semantic_match_score=0.8,
        spatial_support_score=0.8,
        retrieval_score=0.8,
    )


def test_ambiguous_packet_does_not_enter_ground_when_llm_is_disabled(
    monkeypatch,
) -> None:
    parcels = [
        _parcel("44142621100000000001", 116.0),
        _parcel("44142621100000000002", 116.02),
    ]
    points = [
        _point("00000000000000000892", "hall-1", 116.005, text="祠堂甲"),
        _point("00000000000000000899", "hall-2", 116.025, text="祠堂乙"),
    ]
    context = _context(points, parcels)
    packet = EvidencePacket(
        request="金田村祠堂",
        ambiguity_status="multiple",
        candidate_refs=[
            _feature_ref(points[0], parcels[0].bsm),
            _feature_ref(points[1], parcels[1].bsm),
        ],
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "祠堂"},
        ),
        target_id="facility-target",
    )
    monkeypatch.setenv("GROUND_LLM_ENABLED", "false")

    resolved = SpatialResolver(context).resolve_spec(
        spec,
        evidence_packet=packet,
    )

    assert resolved.final_bsms == []
    assert resolved.reference_geometries == []
    assert resolved.uncertainty_reason == "evidence_packet_selection_unresolved"
    assert resolved.provenance["packet_candidate_count"] == 2
    assert resolved.provenance["packet_selection_status"] == "selection_unresolved"


def test_single_spatial_candidate_does_not_require_llm_when_packet_has_other_gaps(
    monkeypatch,
) -> None:
    parcel = _parcel("44142621100000000001", 116.0)
    point = _point("00000000000000000892", "hall-1", 116.005, text="祠堂")
    context = _context([point], [parcel])
    packet = EvidencePacket(
        request="金田村社前村祠堂",
        ambiguity_status="multiple",
        sufficiency="sufficient",
        candidate_refs=[_feature_ref(point, parcel.bsm)],
        missing_evidence=["planning_background_incomplete"],
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "祠堂"},
        ),
        target_id="facility-target",
    )
    monkeypatch.setenv("GROUND_LLM_ENABLED", "false")

    resolved = SpatialResolver(context).resolve_spec(
        spec,
        evidence_packet=packet,
    )

    assert resolved.final_bsms == [parcel.bsm]
    assert resolved.feature_bsms == [point.bsm]
    assert resolved.provenance["packet_ambiguity_status"] == "multiple"
    assert resolved.provenance["packet_selection_status"] == "single_packet_candidate"


def test_ambiguous_packet_llm_choice_keeps_only_selected_bundle_identity(
    monkeypatch,
) -> None:
    parcels = [
        _parcel("44142621100000000001", 116.0),
        _parcel("44142621100000000002", 116.02),
    ]
    points = [
        _point("00000000000000000892", "hall-1", 116.005, text="祠堂甲"),
        _point("00000000000000000899", "hall-2", 116.025, text="祠堂乙"),
    ]
    context = _context(points, parcels)
    packet = EvidencePacket(
        request="金田村祠堂",
        ambiguity_status="multiple",
        candidate_refs=[
            _feature_ref(points[0], parcels[0].bsm),
            _feature_ref(points[1], parcels[1].bsm),
        ],
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(
            kind="place_name",
            filter={"label_contains": "祠堂"},
        ),
        target_id="facility-target",
    )
    prompts: list[str] = []

    class _Structured:
        def __init__(self, response_model):
            self.response_model = response_model

        def invoke(self, prompt: str):
            prompts.append(prompt)
            return self.response_model(candidate_index=2)

    class _LLM:
        def with_structured_output(self, response_model, **_kwargs):
            return _Structured(response_model)

    monkeypatch.setenv("GROUND_LLM_ENABLED", "true")
    monkeypatch.setattr(
        "app.infrastructure.llm.factory.create_flash_llm",
        lambda **_kwargs: _LLM(),
    )

    resolved = SpatialResolver(context).resolve_spec(
        spec,
        evidence_packet=packet,
    )

    assert resolved.final_bsms == [parcels[1].bsm]
    assert resolved.feature_bsms == [points[1].bsm]
    assert len(resolved.reference_geometries) == 1
    assert resolved.reference_geometries[0].feature_bsms == [points[1].bsm]
    assert resolved.provenance["packet_selection_status"] == "closed_set_llm_selected"
    assert resolved.provenance["selected_feature_bsms"] == [points[1].bsm]
    assert prompts and points[0].bsm in prompts[0] and points[1].bsm in prompts[0]


def test_hazard_address_can_seed_natural_village_scope_from_related_parcel() -> None:
    parcel = _parcel("44142621100000000077", 116.0)
    hazard = _point(
        "00000000000000000777",
        "hazard-furnace-1",
        116.005,
        text="吴某屋后崩塌点",
        address="金田村炉池自然村吴某屋后",
    )
    context = _context([hazard], [parcel])
    context.workspace.points["facilities_current"] = []
    context.evidence_graph = EvidenceGraph(
        context,
        index=PlaceEvidenceIndex.build(context),
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(
            kind="village",
            filter={"label_contains": "炉池"},
        ),
        target_id="furnace-village",
    )
    packet = enrich_evidence_packet_with_spatial_graph(
        EvidencePacket(request="炉池自然村在哪里"),
        context,
        query="炉池自然村在哪里",
        village_name="金田村",
        entity_scope=["parcels", "hazards"],
        spatial_spec=spec,
    )

    assert len(packet.candidate_refs) == 1
    assert packet.candidate_refs[0].identity.role == "hazard"
    assert packet.candidate_refs[0].related_parcel_bsms == [parcel.bsm]

    resolved = SpatialResolver(context).resolve_spec(
        spec,
        evidence_packet=packet,
    )

    assert resolved.final_bsms == []
    assert resolved.reference_geometries == []
    assert resolved.search_scope is not None
    assert resolved.search_scope.scope_bsms == [parcel.bsm]
    assert resolved.spatial_domain_kind == "village_scope"
    assert resolved.uncertainty_reason == "evidence_derived_village_scope"
    assert resolved.feature_bsms == []
    assert resolved.provenance["not_exact_village_boundary"] is True
    assert resolved.provenance["scope_seed_parcel_bsms"] == [parcel.bsm]
    assert resolved.search_scope.diagnostics["anchor_feature_bsms"] == [hazard.bsm]

    query, scopes = _ground_packet_query(context, spec)
    assert "炉池" in query
    assert "hazards" in scopes


def test_separated_same_name_anchor_clusters_fail_closed_without_llm(
    monkeypatch,
) -> None:
    parcels = [
        _parcel("44142621100000000011", 116.0),
        _parcel("44142621100000000022", 116.1),
    ]
    hazards = [
        _point("00000000000000000111", "hazard-a", 116.005, text="炉池甲点"),
        _point("00000000000000000222", "hazard-b", 116.105, text="炉池乙点"),
    ]
    context = _context(hazards, parcels)
    packet = EvidencePacket(
        request="炉池自然村在哪里",
        ambiguity_status="multiple",
        candidate_refs=[
            _feature_ref(hazards[0], parcels[0].bsm, source_layer="geological_hazard_point"),
            _feature_ref(hazards[1], parcels[1].bsm, source_layer="geological_hazard_point"),
        ],
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="village", filter={"label_contains": "炉池"}),
        target_id="furnace-village",
    )
    monkeypatch.setenv("GROUND_LLM_ENABLED", "false")

    resolved = SpatialResolver(context).resolve_spec(spec, evidence_packet=packet)

    assert resolved.final_bsms == []
    assert resolved.uncertainty_reason == "evidence_anchor_clusters_unresolved"
    assert resolved.provenance["anchor_cluster_count"] == 2
    assert resolved.provenance["cluster_selection_reason"] == "ground_llm_disabled"


def test_llm_selects_one_spatial_cluster_without_merging_distant_parcels(
    monkeypatch,
) -> None:
    parcels = [
        _parcel("44142621100000000011", 116.0),
        _parcel("44142621100000000022", 116.1),
    ]
    hazards = [
        _point("00000000000000000111", "hazard-a", 116.005, text="炉池甲点"),
        _point("00000000000000000222", "hazard-b", 116.105, text="炉池乙点"),
    ]
    context = _context(hazards, parcels)
    packet = EvidencePacket(
        request="报告中的炉池乙点附近自然村",
        ambiguity_status="multiple",
        source_spans=["规划对象位于炉池乙点附近"],
        candidate_refs=[
            _feature_ref(hazards[0], parcels[0].bsm, source_layer="geological_hazard_point"),
            _feature_ref(hazards[1], parcels[1].bsm, source_layer="geological_hazard_point"),
        ],
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(kind="village", filter={"label_contains": "炉池"}),
        target_id="furnace-village",
    )
    prompts: list[str] = []

    class _Structured:
        def __init__(self, response_model):
            self.response_model = response_model

        def invoke(self, prompt: str):
            prompts.append(prompt)
            return self.response_model(candidate_index=2)

    class _LLM:
        def with_structured_output(self, response_model, **_kwargs):
            return _Structured(response_model)

    monkeypatch.setenv("GROUND_LLM_ENABLED", "true")
    monkeypatch.setattr(
        "app.infrastructure.llm.factory.create_flash_llm",
        lambda **_kwargs: _LLM(),
    )

    resolved = SpatialResolver(context).resolve_spec(spec, evidence_packet=packet)

    assert resolved.final_bsms == []
    assert resolved.feature_bsms == []
    assert resolved.search_scope is not None
    assert resolved.search_scope.scope_bsms == [parcels[1].bsm]
    assert resolved.provenance["anchor_cluster_count"] == 2
    assert resolved.provenance["selected_anchor_cluster_index"] == 2
    assert resolved.provenance["anchor_cluster_selection"] == "closed_set_llm_selected_cluster"
    assert resolved.search_scope.diagnostics["anchor_feature_bsms"] == [hazards[1].bsm]
    assert prompts and hazards[0].bsm in prompts[0] and hazards[1].bsm in prompts[0]
    assert "规划对象位于炉池乙点附近" in prompts[0]
    assert "L1_facts=" in prompts[0]
    assert "KG_topology=" in prompts[0]
    assert "scores=semantic:" in prompts[0]


def test_explicit_multi_id_source_collection_remains_all_members() -> None:
    parcels = [
        _parcel("44142621100000000001", 116.0),
        _parcel("44142621100000000002", 116.02),
    ]
    points = [
        _point("00000000000000000892", "member-1", 116.005, text="成员甲"),
        _point("00000000000000000899", "member-2", 116.025, text="成员乙"),
    ]
    context = _context(points, parcels)
    packet = EvidencePacket(
        request="显式设施集合",
        ambiguity_status="multiple",
        candidate_refs=[
            _feature_ref(points[0], parcels[0].bsm),
            _feature_ref(points[1], parcels[1].bsm),
        ],
    )
    spec = SpatialReferenceSpec(
        type="attributive",
        reference=RefObject(
            kind="entity_type",
            filter={
                "source_feature_ids": ["member-1", "member-2"],
            },
        ),
        source_collection_key="current_facility",
        target_id="explicit-collection",
    )

    result = ground_aggregate(
        [spec],
        context,
        target_metadata={
            "explicit-collection": {
                "target_kind": "facility",
                "expected_output_kind": "point",
            }
        },
        evidence_packets={"explicit-collection": packet},
    )

    assert len(result.candidates) == 2
    assert result.problem is not None
    assert result.problem.candidate_domains[0].selection_mode == "all_members"
    assert all(
        candidate.geometry.candidate_membership == "required_member"
        for candidate in result.candidates
    )


def test_named_village_parcel_overlap_is_exposed_as_selection_evidence() -> None:
    entry = PlaceEvidenceEntry(
        canonical_name="同名设施",
        role="facility",
        related_parcel_bsms=["P-SHEQIAN"],
        source_bsms=["P-SHEQIAN"],
    )
    context = SimpleNamespace(
        gazetteer=SimpleNamespace(
            entries=[
                SimpleNamespace(
                    name="社前村",
                    aliases=["社前"],
                    bsms=["P-SHEQIAN"],
                )
            ]
        ),
        kg=None,
    )

    evidence = score_candidate(
        "同名设施",
        entry,
        role="facility",
        hints="目标位于社前村",
        context=context,
    )

    assert evidence["geometry_near_anchor"] == 0.5
