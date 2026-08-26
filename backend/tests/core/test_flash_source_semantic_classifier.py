from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.contracts.domain.l1_contracts import L1Fact
from app.contracts.evidence.source_semantic_contracts import (
    SourceFeatureDescriptor,
    SourceFeatureSemanticProposal,
    SourceFeatureSemanticProposalBatch,
)
from app.data.model.spatial_types import CurrentAnnotation
from app.evidence.identity.flash_source_semantic_classifier import (
    SourceSemanticClassifier,
    materialize_candidate_vocabulary,
)
from app.evidence.identity.source_semantic_runtime import (
    classify_source_semantics,
    kg_semantic_candidates,
)
from app.evidence.identity.source_semantic_store import SourceSemanticStore
from app.infrastructure.kg.ontology import EntityTypes
from app.infrastructure.kg.spatial_store import SpatialKGEntity
from app.workflow.stages.target_projection import _classify_source_semantics


def _facts() -> list[L1Fact]:
    return [
        L1Fact(
            fact_id="l1:fact:bus",
            statement="现状有3个公交站点",
            fact_kind="document_observation",
            semantic_type="facility",
            attributes={"normalized_name": "公交站点"},
            value=3,
            unit="处",
            source_refs=["report:traffic"],
        ),
        L1Fact(
            fact_id="l1:fact:parking",
            statement="现状有1个停车场",
            fact_kind="document_observation",
            semantic_type="facility",
            attributes={"normalized_name": "停车场"},
            value=1,
            unit="处",
            source_refs=["report:traffic"],
        ),
    ]


def _items() -> list[SourceFeatureDescriptor]:
    return [
        SourceFeatureDescriptor(
            source_feature_id=f"feature:{index}",
            raw_label=label,
            layer_key="annotations_current",
            geometry_kind="Point",
        )
        for index, label in enumerate(("站", "站", "站", "停"), start=1)
    ]


class _FakeStructured:
    def __init__(self, owner: "_FakeLLM", proposals: SourceFeatureSemanticProposalBatch):
        self.owner = owner
        self.proposals = proposals

    async def ainvoke(self, _messages):
        self.owner.calls += 1
        return self.proposals


class _FakeLLM:
    def __init__(self, batches: list[SourceFeatureSemanticProposalBatch]):
        self.batches = list(batches)
        self.calls = 0

    def with_structured_output(self, _response_model, **_kwargs):
        batch = self.batches[min(self.calls, len(self.batches) - 1)]
        return _FakeStructured(self, batch)


def _candidate_refs() -> tuple[str, str]:
    return "l1:l1:fact:bus:entity", "l1:l1:fact:parking:entity"


def _batch(*, parking_on: str = "feature:4", foreign: bool = False) -> SourceFeatureSemanticProposalBatch:
    bus_ref, parking_ref = _candidate_refs()
    if foreign:
        parking_ref = "l1:foreign:entity"
    return SourceFeatureSemanticProposalBatch(
        proposals=[
            SourceFeatureSemanticProposal(
                source_feature_id=f"feature:{index}",
                candidate_ref=parking_ref if f"feature:{index}" == parking_on else bus_ref,
                supporting_fact_refs=["l1:fact:parking"] if f"feature:{index}" == parking_on else ["l1:fact:bus"],
            )
            for index in range(1, 5)
        ]
    )


@pytest.mark.asyncio
async def test_two_agreeing_typed_passes_accept_closed_set_and_cache_replay():
    llm = _FakeLLM([_batch(), _batch()])
    store = SourceSemanticStore()
    classifier = SourceSemanticClassifier(llm=llm, store=store)

    first = await classifier.classify(
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="digest:1",
        source_items=_items(),
        l1_facts=_facts(),
    )
    second = await classifier.classify(
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="digest:1",
        source_items=_items(),
        l1_facts=_facts(),
    )

    assert llm.calls == 2
    assert first.fingerprint == second.fingerprint
    assert [item.semantic_type for item in first.decisions] == [
        "公交站点", "公交站点", "公交站点", "停车场"
    ]
    assert all(item.status == "accepted" for item in first.decisions)


@pytest.mark.asyncio
async def test_disagreement_is_ambiguous_and_abbreviation_has_no_regex_fallback():
    llm = _FakeLLM([_batch(), _batch(parking_on="feature:3")])
    classifier = SourceSemanticClassifier(llm=llm)

    result = await classifier.classify(
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="digest:1",
        source_items=_items(),
        l1_facts=_facts(),
    )

    assert all(item.status == "ambiguous" for item in result.decisions)
    assert any("disagree" in item.reason for item in result.decisions)

    unavailable = await SourceSemanticClassifier(llm=None).classify(
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="digest:1",
        source_items=_items(),
        l1_facts=_facts(),
    )
    assert all(item.status == "unresolved" for item in unavailable.decisions)


@pytest.mark.asyncio
async def test_foreign_candidate_is_never_accepted():
    llm = _FakeLLM([_batch(foreign=True), _batch(foreign=True)])
    result = await SourceSemanticClassifier(llm=llm).classify(
        source_snapshot_ref="snapshot:1",
        source_snapshot_digest="digest:1",
        source_items=_items(),
        l1_facts=_facts(),
    )

    assert all(item.status == "unresolved" for item in result.decisions)
    assert any("foreign candidate" in finding for finding in result.verifier_findings)


@pytest.mark.asyncio
async def test_incompatible_source_items_do_not_consume_llm_batches():
    class _CountingStructured:
        async def ainvoke(self, _messages):
            return SourceFeatureSemanticProposalBatch(proposals=[
                SourceFeatureSemanticProposal(
                    source_feature_id="feature:point",
                    candidate_ref="l1:l1:fact:bus:entity",
                    supporting_fact_refs=["l1:fact:bus"],
                )
            ])

    class _CountingLLM:
        def __init__(self):
            self.calls = 0

        def with_structured_output(self, _response_model, **_kwargs):
            self.calls += 1
            return _CountingStructured()

    classifier_llm = _CountingLLM()
    result = await SourceSemanticClassifier(llm=classifier_llm).classify(
        source_snapshot_ref="snapshot:incompatible",
        source_snapshot_digest="digest:incompatible",
        source_items=[
            SourceFeatureDescriptor(
                source_feature_id="feature:point",
                raw_label="站",
                layer_key="annotations_current",
                geometry_kind="Point",
            ),
            SourceFeatureDescriptor(
                source_feature_id="feature:road-without-fact",
                raw_label="",
                layer_key="roads_current",
                geometry_kind="LineString",
            ),
        ],
        l1_facts=[_facts()[0].model_copy(update={"value": None, "unit": ""})],
    )

    assert classifier_llm.calls == 2
    decisions = {item.source_feature_id: item for item in result.decisions}
    assert decisions["feature:point"].status == "accepted"
    assert decisions["feature:road-without-fact"].status == "unresolved"
    assert decisions["feature:road-without-fact"].reason == (
        "no layer/geometry-compatible closed-set candidate"
    )


@pytest.mark.asyncio
async def test_axis_fact_uses_current_road_line_compatibility_without_alias_mapping():
    fact = L1Fact(
        fact_id="l1:fact:axis",
        statement="金田村现状有一条发展轴线",
        fact_kind="document_observation",
        semantic_type="axis",
        attributes={"normalized_name": "发展轴线"},
        value=1,
        unit="条",
        source_refs=["report:spatial-structure"],
    )
    item = SourceFeatureDescriptor(
        source_feature_id="feature:axis-line",
        raw_label="",
        layer_key="roads_current",
        geometry_kind="MultiLineString",
    )
    proposal = SourceFeatureSemanticProposalBatch(
        proposals=[SourceFeatureSemanticProposal(
            source_feature_id="feature:axis-line",
            candidate_ref="l1:l1:fact:axis:entity",
            supporting_fact_refs=["l1:fact:axis"],
        )]
    )

    result = await SourceSemanticClassifier(
        llm=_FakeLLM([proposal, proposal]),
    ).classify(
        source_snapshot_ref="snapshot:axis",
        source_snapshot_digest="digest:axis",
        source_items=[item],
        l1_facts=[fact],
    )

    decision = result.decisions[0]
    assert decision.status == "accepted"
    assert decision.semantic_type == "发展轴线"
    assert decision.supporting_fact_refs == ["l1:fact:axis"]


@pytest.mark.asyncio
async def test_target_projection_installs_only_accepted_overlay_into_evidence_graph():
    feature_ids = ("feature:1", "feature:2", "feature:3")
    batch = SourceFeatureSemanticProposalBatch(
        proposals=[
            SourceFeatureSemanticProposal(
                source_feature_id=feature_id,
                candidate_ref="l1:l1:fact:bus:entity",
                supporting_fact_refs=["l1:fact:bus"],
            )
            for feature_id in feature_ids
        ]
    )
    llm = _FakeLLM([batch, batch])
    classifier = SourceSemanticClassifier(llm=llm)
    features = [
        CurrentAnnotation(
            geometry={"type": "Point", "coordinates": [116.0 + index * 0.001, 24.8]},
            text="站",
            category="现状设施点",
            _raw={"source_feature_id": feature_id},
        )
        for index, feature_id in enumerate(feature_ids)
    ]
    workspace = SimpleNamespace(
        points={"annotations_current": features, "facilities_current": []},
        lines={"roads_current": []},
        polygons={},
    )
    context = SimpleNamespace(
        session_id="semantic-target-test",
        version=1,
        kg_version=1,
        kg=None,
        workspace=workspace,
        current_parcels=lambda: [],
        location_facts=[],
        l1_fact_records=[_facts()[0]],
        l1_snapshot_ref="l1:snapshot:1",
        data_snapshot=None,
        content_hash="context:digest",
        source_semantic_decisions={},
        evidence_graph_key="graph:base",
    )
    state = {
        "config": {"source_semantic_llm_enabled": True},
        "artifact_refs": {},
        "source_semantic_classifier": classifier,
    }

    snapshot, accepted, diagnostics = await _classify_source_semantics(
        state,
        context,
        {"facility": features, "road": []},
    )

    assert snapshot is not None
    assert diagnostics == []
    assert set(accepted) == set(feature_ids)
    assert all(item.status == "accepted" for item in snapshot.decisions)
    assert set(context.source_semantic_decisions) == set(feature_ids)
    assert context.evidence_graph is not None
    assert "source-semantic:" in context.evidence_graph_key


@pytest.mark.asyncio
async def test_query_runtime_uses_explicit_minimax_classifier_and_installs_overlay():
    feature = CurrentAnnotation(
        geometry={"type": "Point", "coordinates": [116.0, 24.8]},
        text="祠",
        category="现状设施点",
        _raw={"source_feature_id": "feature:runtime:1"},
    )
    proposal_batch = SourceFeatureSemanticProposalBatch(
        proposals=[SourceFeatureSemanticProposal(
            source_feature_id="feature:runtime:1",
            candidate_ref="l1:l1:fact:shrine:entity",
            supporting_fact_refs=["l1:fact:shrine"],
        )]
    )
    llm = _FakeLLM([proposal_batch, proposal_batch])
    classifier = SourceSemanticClassifier(llm=llm)
    fact = L1Fact(
        fact_id="l1:fact:shrine",
        statement="现状有祠堂",
        fact_kind="document_observation",
        semantic_type="facility",
        attributes={"normalized_name": "祠堂"},
        value=1,
        unit="处",
        source_refs=["report:current"],
    )
    context = SimpleNamespace(
        session_id="runtime-query-1",
        version=1,
        kg_version=1,
        kg=None,
        workspace=SimpleNamespace(
            points={"annotations_current": [feature], "facilities_current": []},
            lines={"roads_current": []},
        ),
        l1_fact_records=[fact],
        l1_snapshot_ref="l1:runtime:1",
        data_snapshot=None,
        content_hash="runtime:digest:1",
        source_semantic_decisions={},
        source_semantic_fingerprint="",
        evidence_graph_key="graph:runtime",
    )
    snapshot, accepted, diagnostics = await classify_source_semantics(
        context,
        enabled=True,
        classifier=classifier,
    )

    assert snapshot is not None
    assert diagnostics == []
    assert set(accepted) == {"feature:runtime:1"}
    assert context.source_semantic_decisions["feature:runtime:1"].semantic_type == "祠堂"
    assert llm.calls == 2


def test_kg_vocabulary_enriches_matching_l1_candidate_without_creating_duplicate_choice():
    fact = L1Fact(
        fact_id="l1:fact:shrine",
        statement="现状有祠堂",
        fact_kind="document_observation",
        semantic_type="facility",
        attributes={"normalized_name": "祠堂"},
        source_refs=["report:current"],
    )
    concept = SpatialKGEntity(
        entity_ref="http://village-planning.org/entity/facility/shrine-1",
        entity_type=str(EntityTypes.Facility),
        canonical_name="祠堂",
        feature_bsm="00000000000000000001",
        source_feature_id="feature:shrine:1",
        source_layer="current_annotation",
    )
    calls = []

    def find_entities(**_filters):
        calls.append(_filters)
        assert _filters["entity_type"] == str(EntityTypes.Facility)
        return [concept]

    context = SimpleNamespace(kg=SimpleNamespace(find_entities=find_entities))

    cached_candidates = kg_semantic_candidates(
        context,
        [fact, fact.model_copy(update={"fact_id": "l1:fact:shrine:duplicate"})],
    )
    assert len(cached_candidates) == 2
    assert len(calls) == 1

    kg_candidates = kg_semantic_candidates(context, [fact])
    assert len(kg_candidates) == 1
    assert kg_candidates[0].origin == "kg_snapshot"
    assert kg_candidates[0].optional_kg_concept_ref == concept.entity_ref

    vocabulary = materialize_candidate_vocabulary([fact], kg_candidates)
    assert len(vocabulary) == 1
    assert vocabulary[0].candidate_ref == "l1:l1:fact:shrine:entity"
    assert vocabulary[0].optional_kg_concept_ref == concept.entity_ref
    assert vocabulary[0].supporting_fact_refs == ["l1:fact:shrine"]


def test_noncanonical_l1_fact_ids_never_enter_semantic_candidate_vocabulary():
    legacy = _facts()[0].model_copy(update={"fact_id": "l1:legacy:bus"})

    assert materialize_candidate_vocabulary([legacy]) == []


@pytest.mark.asyncio
async def test_query_runtime_disabled_is_explicit_and_does_not_call_classifier():
    context = SimpleNamespace(
        session_id="runtime-query-disabled",
        version=1,
        workspace=SimpleNamespace(
            points={"annotations_current": []},
            lines={"roads_current": []},
        ),
        l1_fact_records=[],
        source_semantic_decisions={},
        source_semantic_fingerprint="",
        evidence_graph_key="graph:disabled",
    )
    llm = _FakeLLM([])
    snapshot, accepted, diagnostics = await classify_source_semantics(
        context,
        enabled=False,
        classifier=SourceSemanticClassifier(llm=llm),
    )

    assert snapshot is None
    assert accepted == {}
    assert any(item["code"] == "SOURCE_SEMANTIC_INPUT_EMPTY" for item in diagnostics)
    assert llm.calls == 0
