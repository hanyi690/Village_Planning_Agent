import asyncio
from types import SimpleNamespace

import pytest

from app.infrastructure.llm.table_protocol import (
    build_llm_table,
    validate_flat_llm_rows,
)
from app.data.ingestion.compiler.profiles.l1_observation import (
    compile_l1_observation,
)
from app.modules.l1.gate import evaluate_l1_gate
from app.modules.l1.observation_draft import (
    normalize_l1_observation_provider_output,
)


def test_build_llm_table_is_bounded_and_tabular():
    rows, table = build_llm_table(
        ["row_ref", "value"],
        [{"row_ref": "r1", "value": "x"}],
        max_rows=1,
    )
    assert rows == [{"row_ref": "r1", "value": "x"}]
    assert table.splitlines()[0] == "| row_ref | value |"


def test_validate_flat_llm_rows_rejects_nested_large_payloads():
    with pytest.raises(ValueError):
        validate_flat_llm_rows(
            [{"row_ref": "r1", "value": {"nested": {"too": "deep"}}}],
            required_columns=["row_ref", "value"],
            max_depth=2,
        )
    with pytest.raises(ValueError):
        validate_flat_llm_rows(
            [{"row_ref": "r1"}, {"row_ref": "r2"}],
            required_columns=["row_ref"],
            max_rows=1,
        )


def test_l1_abstract_analysis_topic_is_quarantined_before_location_mentions():
    output = normalize_l1_observation_provider_output(
        "superior_planning",
        {
            "observations": [
                {
                    "fact_type": "spatial_entity",
                    "entity_type": "facility",
                    "name": "农业发展、设施现状评估",
                    "source_segment_ids": ["segment-1"],
                    "source_quote": "农业发展、设施现状评估",
                    "status": "confirmed",
                }
            ]
        },
    )
    snapshot = compile_l1_observation(
        dimension_key="superior_planning",
        content="## 现状\n【事实】农业发展、设施现状评估",
        instruction=output.model_dump_json(),
        report_id="report-abstract-topic",
    )
    gate = evaluate_l1_gate(snapshot, run_id="run-abstract-topic")

    assert output.observations == []
    assert len(output.quarantined_observations) == 1
    assert snapshot.location_mentions == []
    assert [issue.code for issue in snapshot.issues] == [
        "spatial_semantic_admission_failed"
    ]
    assert gate.passed is False
    assert gate.feedback_route == "L1"


@pytest.mark.parametrize("name", ["金田村委会", "古茶亭", "农业发展大道"])
def test_l1_source_named_physical_objects_remain_location_work_items(name):
    output = normalize_l1_observation_provider_output(
        "superior_planning",
        {
            "observations": [
                {
                    "fact_type": "spatial_entity",
                    "entity_type": "facility",
                    "name": name,
                    "source_segment_ids": ["segment-1"],
                    "source_quote": name,
                    "status": "confirmed",
                }
            ]
        },
    )
    snapshot = compile_l1_observation(
        dimension_key="superior_planning",
        content=f"## 现状\n【事实】{name}",
        instruction=output.model_dump_json(),
        report_id=f"report-{name}",
    )

    assert len(output.observations) == 1
    assert [item.normalized_name for item in snapshot.location_mentions] == [name]


def test_l1_layer_aggregate_runs_independent_location_grounding(
    monkeypatch,
):
    from app.modules.ground.application import GroundApplication
    from app.modules.l1 import application as l1_application
    from app.workflow.layers.layer_aggregate_node import layer_aggregate_node

    calls = {"l1": 0, "ground": 0}

    async def fake_run_l1(state):
        calls["l1"] += 1
        return SimpleNamespace(to_state_patch=lambda: {"artifact_refs": {}})

    async def fake_location_ground(state):
        calls["ground"] += 1
        return {
            "artifact_refs": {
                "l1_observations": {"descriptor_digest": "observation-ref"},
                "l1_bindings": {"descriptor_digest": "binding-ref"},
            }
        }

    monkeypatch.setattr(l1_application, "run_l1", fake_run_l1)
    monkeypatch.setattr(
        GroundApplication,
        "materialize_l1_locations",
        fake_location_ground,
    )

    patch = asyncio.run(layer_aggregate_node({
        "session_id": "session-l1-order",
        "run_id": "run-l1-order",
        "phase": "layer1",
        "layer_just_completed": 1,
        "context_version": "context-v1",
        "context_ref": {"descriptor_digest": "context-ref"},
        "artifact_refs": {},
    }))

    assert calls == {"l1": 1, "ground": 1}
    assert patch["layer_just_completed"] is None
    assert set(patch["artifact_refs"]) == {"l1_observations", "l1_bindings"}


def test_l1_layer_aggregate_does_not_swallow_location_grounding_failure(
    monkeypatch,
):
    from app.modules.ground.application import GroundApplication
    from app.modules.l1 import application as l1_application
    from app.workflow.layers.layer_aggregate_node import layer_aggregate_node

    async def fake_run_l1(state):
        return SimpleNamespace(to_state_patch=lambda: {"artifact_refs": {}})

    async def failed_location_ground(state):
        raise RuntimeError("identity runtime unavailable")

    monkeypatch.setattr(l1_application, "run_l1", fake_run_l1)
    monkeypatch.setattr(
        GroundApplication,
        "materialize_l1_locations",
        failed_location_ground,
    )

    with pytest.raises(RuntimeError, match="identity runtime unavailable"):
        asyncio.run(layer_aggregate_node({
            "session_id": "session-l1-ground-failure",
            "run_id": "run-l1-ground-failure",
            "phase": "layer1",
            "layer_just_completed": 1,
            "context_version": "context-v1",
            "context_ref": {"descriptor_digest": "context-ref"},
            "artifact_refs": {},
        }))


def test_l1_identity_requirements_group_equivalent_mentions_by_scope():
    from app.contracts.l1.l1_contracts import (
        L1Snapshot,
        LocationMention,
        LocationScopeMention,
    )
    from app.modules.evidence.requirements import requirements_from_l1

    scope = LocationScopeMention(
        name="金田村",
        normalized_name="金田村",
        role="administrative_area",
    )
    snapshot = L1Snapshot(
        artifact_id="l1-grouping",
        context_fingerprint="context-one",
        location_mentions=[
            LocationMention(
                mention="村委会",
                normalized_name="金田村委会",
                role="facility",
                dimension_key="public_services",
                source_report_ref="report-services",
                scopes=[scope],
            ),
            LocationMention(
                mention="金田村委会",
                normalized_name="金田村委会",
                role="facility",
                dimension_key="location",
                source_report_ref="report-location",
                scopes=[scope],
            ),
        ],
    )

    requirements = requirements_from_l1(snapshot)

    assert len(requirements) == 1
    metadata = requirements[0].metadata
    assert metadata["location_mention_indexes"] == [0, 1]
    assert metadata["dimension_keys"] == ["public_services", "location"]
    assert metadata["scope_names"] == ["金田村"]


def test_l1_identity_requirements_keep_same_name_in_distinct_scopes():
    from app.contracts.l1.l1_contracts import (
        L1Snapshot,
        LocationMention,
        LocationScopeMention,
    )
    from app.modules.evidence.requirements import requirements_from_l1

    snapshot = L1Snapshot(
        artifact_id="l1-distinct-scope",
        context_fingerprint="context-one",
        location_mentions=[
            LocationMention(
                mention="卫生室",
                normalized_name="卫生室",
                role="facility",
                scopes=[LocationScopeMention(name="甲村")],
            ),
            LocationMention(
                mention="卫生室",
                normalized_name="卫生室",
                role="facility",
                scopes=[LocationScopeMention(name="乙村")],
            ),
        ],
    )

    requirements = requirements_from_l1(snapshot)

    assert len(requirements) == 2
    assert {tuple(item.metadata["scope_names"]) for item in requirements} == {
        ("甲村",),
        ("乙村",),
    }


def test_l1_ground_projection_deduplicates_work_but_retains_source_mentions():
    from app.contracts.l1.l1_contracts import (
        LocationMention,
        LocationScopeMention,
    )
    from app.modules.ground.projections import build_l1_identity_work_items

    scope = LocationScopeMention(name="金田村", role="administrative_area")
    representatives, observations = build_l1_identity_work_items([
        LocationMention(
            mention="村委会",
            normalized_name="金田村委会",
            role="facility",
            dimension_key="location",
            source_report_ref="report-location",
            evidence_refs=["evidence:a"],
            scopes=[scope],
        ),
        LocationMention(
            mention="金田村委会",
            normalized_name="金田村委会",
            role="facility",
            dimension_key="public_services",
            source_report_ref="report-services",
            evidence_refs=["evidence:b"],
            scopes=[scope],
        ),
    ])

    assert len(representatives) == len(observations) == 1
    assert representatives[0].work_item_ref == observations[0].work_item_ref
    assert observations[0].observation_id.startswith("l1-location-work-item:")
    assert len(observations[0].source_mention_refs) == 2
    assert set(observations[0].evidence_refs) == {"evidence:a", "evidence:b"}
    assert {"report-location", "report-services"}.issubset(
        set(observations[0].source_refs)
    )


def test_l1_identity_status_is_resolved_for_one_entity_with_many_representations():
    from app.contracts.l1.l1_contracts import LocationMention
    from app.modules.ground.reference_resolution import (
        _binding_from_entity_rows,
    )

    entity_row = {
        "entity_ref": "entity:main-road",
        "parts": [
            {"source_feature_ref": "segment-a"},
            {"source_feature_ref": "segment-b"},
        ],
    }

    class WorldModelPort:
        snapshot_ref = "world-model://session/2/digest"
        snapshot_digest = "digest"

        def find_entities(self, **kwargs):
            return [entity_row]

        def representations_for(self, entity_ref, *, limit=50):
            return [
                {
                    "representation_ref": "representation:segment-a",
                    "resource_ref": "resource:segment-a",
                    "geometry_ref": "geometry:segment-a",
                    "entity_part_ref": "part:a",
                },
                {
                    "representation_ref": "representation:segment-b",
                    "resource_ref": "resource:segment-b",
                    "geometry_ref": "geometry:segment-b",
                    "entity_part_ref": "part:b",
                },
            ]

    context = SimpleNamespace(
        ports=SimpleNamespace(current_world=WorldModelPort()),
        world_model=SimpleNamespace(
            snapshot_ref="world-model://session/2/digest",
            snapshot_digest="digest",
        ),
        world_model_mode="v2_only",
    )
    binding = _binding_from_entity_rows(
        context,
        LocationMention(
            mention="主路",
            normalized_name="主路",
            role="road",
        ),
        "l1-location-work-item:road",
        {"entity:main-road": entity_row},
        match_mode="exact_name",
    )

    assert binding.identity_status == "resolved"
    assert binding.canonical_entity_ref == "entity:main-road"
    assert binding.candidate_entity_refs == ["entity:main-road"]
    assert len(binding.representation_refs) == 2
    assert len(binding.source_feature_ids) == 2
    assert binding.world_model_snapshot_digest == "digest"


def test_l1_spatial_relation_preserves_direction_and_anchor_role():
    output = normalize_l1_observation_provider_output(
        "location",
        {
            "observations": [{
                "fact_type": "spatial_relation",
                "subject_ref": "居民点",
                "predicate": "west_of",
                "object_ref": "主路",
                "location_relation": "west_of",
                "source_segment_ids": ["segment-relation-1"],
                "source_quote": "居民点位于主路西侧",
                "status": "confirmed",
            }],
        },
    )
    mentions = output.observations[0].spatial_mentions

    assert [item.target_name for item in mentions] == ["居民点", "主路"]
    assert mentions[0].relation == "west_of"
    assert mentions[0].related_mentions == ["主路"]
    assert mentions[1].relation == ""
    assert mentions[1].related_mentions == []

    snapshot = compile_l1_observation(
        dimension_key="location",
        content="## 区位\n居民点位于主路西侧。",
        instruction=output.model_dump_json(),
        report_id="report-spatial-relation",
    )
    compiled = {
        item.target_name: item
        for item in snapshot.location_mentions
    }
    assert compiled["居民点"].relation == "west_of"
    assert compiled["居民点"].related_mentions == ["主路"]
    assert compiled["主路"].relation == ""


def test_l1_ground_binds_fuzzy_phrase_without_promoting_it_to_entity():
    from app.contracts.l1.l1_contracts import LocationMention
    from app.modules.ground.reference_resolution import (
        resolve_l1_location_mentions,
    )

    road = {
        "entity_ref": "entity:road",
        "canonical_name": "村道",
        "parts": [{"source_feature_ref": "road-segment-1"}],
    }

    class WorldModelPort:
        def find_entities(self, **kwargs):
            if kwargs.get("entity_ref") == "entity:road":
                return [road]
            if kwargs.get("name") == "村道":
                return [road]
            return []

        def representations_for(self, entity_ref, *, limit=50):
            assert entity_ref == "entity:road"
            return [{
                "representation_ref": "representation:road-line",
                "resource_ref": "resource:road-layer",
                "geometry_ref": "geometry:road-line",
                "geometry_kind": "line",
            }]

    context = SimpleNamespace(
        ports=SimpleNamespace(current_world=WorldModelPort()),
        world_model=SimpleNamespace(
            snapshot_ref="world-model://session/1/digest",
            snapshot_digest="world-digest",
        ),
        world_model_mode="v2_only",
        data_resource_catalog=SimpleNamespace(
            snapshot=SimpleNamespace(digest="data-digest", features=[]),
        ),
        location_mentions=[LocationMention(
            work_item_ref="work-item:road-nearby",
            mention="村道附近",
            normalized_name="村道附近",
            role="area",
            relation="near",
        )],
    )

    bindings = resolve_l1_location_mentions(context)

    assert len(bindings) == 1
    binding = bindings[0]
    assert binding.identity_status == "not_applicable"
    assert binding.canonical_entity_ref == ""
    assert binding.candidate_entity_refs == []
    assert binding.location_expression_status == "bound"
    assert binding.spatial_relation == "near"
    assert binding.anchor_entity_refs == ["entity:road"]
    assert binding.geometry_ref is None
    assert binding.geometry_refs == []
    assert binding.representation_refs == []
    assert binding.resource_refs == []
    assert binding.query_trace[-1]["geometry_operation"] == "none"


def test_l1_ground_relative_location_keeps_scope_and_gap_semantics():
    from app.contracts.l1.l1_contracts import (
        LocationMention,
        LocationScopeMention,
    )
    from app.modules.ground.reference_resolution import (
        resolve_l1_location_mentions,
    )

    rows = {
        "entity:road-a": {
            "entity_ref": "entity:road-a",
            "canonical_name": "主路",
            "parts": [{"source_feature_ref": "road-a"}],
        },
        "entity:road-b": {
            "entity_ref": "entity:road-b",
            "canonical_name": "主路",
            "parts": [{"source_feature_ref": "road-b"}],
        },
    }

    class WorldModelPort:
        def find_entities(self, **kwargs):
            entity_ref = kwargs.get("entity_ref")
            source_ref = kwargs.get("source_feature_ref")
            name = kwargs.get("name")
            if entity_ref in rows:
                return [rows[entity_ref]]
            if source_ref == "road-a":
                return [rows["entity:road-a"]]
            if source_ref == "road-b":
                return [rows["entity:road-b"]]
            if name == "主路":
                return [rows["entity:road-a"], rows["entity:road-b"]]
            return []

        def representations_for(self, entity_ref, *, limit=50):
            suffix = entity_ref.rsplit("-", 1)[-1]
            return [{
                "representation_ref": f"representation:{suffix}",
                "resource_ref": f"resource:{suffix}",
                "geometry_ref": f"geometry:{suffix}",
            }]

    scope_a = LocationScopeMention(name="甲村")
    scope_b = LocationScopeMention(name="乙村")
    mentions = [
        LocationMention(
            work_item_ref="work-item:road-a",
            mention="主路",
            normalized_name="主路",
            role="road",
            scopes=[scope_a],
            source_feature_ids=["road-a"],
        ),
        LocationMention(
            work_item_ref="work-item:road-b",
            mention="主路",
            normalized_name="主路",
            role="road",
            scopes=[scope_b],
            source_feature_ids=["road-b"],
        ),
        LocationMention(
            work_item_ref="work-item:near-road-a",
            mention="主路附近",
            normalized_name="主路附近",
            role="area",
            relation="near",
            related_mentions=["主路"],
            scopes=[scope_a],
        ),
        LocationMention(
            work_item_ref="work-item:near-road-ambiguous",
            mention="主路附近",
            normalized_name="主路附近",
            role="area",
            relation="near",
            related_mentions=["主路"],
        ),
        LocationMention(
            work_item_ref="work-item:near-pond",
            mention="水塘附近",
            normalized_name="水塘附近",
            role="area",
            relation="near",
        ),
    ]
    context = SimpleNamespace(
        ports=SimpleNamespace(current_world=WorldModelPort()),
        world_model=SimpleNamespace(
            snapshot_ref="world-model://session/1/digest",
            snapshot_digest="world-digest",
        ),
        world_model_mode="v2_only",
        data_resource_catalog=SimpleNamespace(
            snapshot=SimpleNamespace(digest="data-digest", features=[]),
            get_feature=lambda _source_ref: None,
        ),
        location_mentions=mentions,
    )

    bindings = {
        item.mention_ref: item
        for item in resolve_l1_location_mentions(context)
    }

    scoped = bindings["work-item:near-road-a"]
    assert scoped.identity_status == "not_applicable"
    assert scoped.location_expression_status == "bound"
    assert scoped.anchor_entity_refs == ["entity:road-a"]
    ambiguous = bindings["work-item:near-road-ambiguous"]
    assert ambiguous.location_expression_status == "ambiguous"
    assert ambiguous.anchor_entity_refs == [
        "entity:road-a", "entity:road-b"
    ]
    unresolved = bindings["work-item:near-pond"]
    assert unresolved.location_expression_status == "unresolved"
    assert unresolved.anchor_entity_refs == []


def test_l1_retry_gate_includes_relative_location_gaps():
    from app.contracts.evidence.identity_contracts import (
        GroundedEntityBinding,
    )
    from app.modules.ground.application import _l1_retry_observations

    bound = GroundedEntityBinding(
        binding_id="binding:bound",
        mention_ref="work-item:bound",
        status="not_applicable",
        location_expression_ref="location-expression:bound",
        location_expression_status="bound",
        spatial_relation="near",
        anchor_entity_refs=["entity:road"],
    )
    ambiguous = GroundedEntityBinding(
        binding_id="binding:ambiguous",
        mention_ref="work-item:ambiguous",
        status="not_applicable",
        location_expression_ref="location-expression:ambiguous",
        location_expression_status="ambiguous",
        spatial_relation="near",
        anchor_entity_refs=["entity:road-a", "entity:road-b"],
    )
    unresolved = GroundedEntityBinding(
        binding_id="binding:unresolved",
        mention_ref="work-item:unresolved",
        status="not_applicable",
        location_expression_ref="location-expression:unresolved",
        location_expression_status="unresolved",
        spatial_relation="west_of",
    )

    assert _l1_retry_observations([bound, ambiguous, unresolved]) == {
        "work-item:ambiguous",
        "work-item:unresolved",
    }
