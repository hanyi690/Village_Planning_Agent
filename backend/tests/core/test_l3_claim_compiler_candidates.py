from __future__ import annotations

import json
from types import SimpleNamespace

from app.contracts.domain.planning_semantics import (
    FacilityPlanningParameters,
    PolygonPlanningParameters,
    RoadPlanningParameters,
)
from app.contracts.program import PlanningClaim
from app.domain.program.claim_compiler import (
    ClaimRegistry,
    ProjectIntentSkeleton,
    compatible_objects,
    create_grounding_request,
    decompose_project_intent,
    relation_options,
    source_fact_options,
)


def _claim(
    claim_id: str,
    category: str,
    *,
    asset_kind: str = "none",
    role: str | None = None,
) -> PlanningClaim:
    parameters = {
        "facility": {"facility_parameters": FacilityPlanningParameters(facility_type="clinic")},
        "road": {"road_parameters": RoadPlanningParameters(length_m=100)},
        "zone": {
            "polygon_parameters": PolygonPlanningParameters(
                materialization_role=role or "functional_overlay"
            )
        },
    }.get(category, {})
    return PlanningClaim(
        claim_id=claim_id,
        statement=claim_id,
        planning_role="spatial_intervention",
        project_package_ref=f"pkg:{claim_id}",
        suggested_category=category,
        suggested_output_kind={
            "facility": "point",
            "road": "line",
            "zone": "polygon",
        }[category],
        asset_kind=asset_kind,
        **parameters,
    )


def test_relation_options_are_catalog_derived_for_typed_subjects() -> None:
    axis_templates = {item.template for item in relation_options("axis")}
    site_templates = {item.template for item in relation_options("site_area")}

    assert "follow_alignment" in axis_templates
    assert "connect_network" not in axis_templates
    assert "serve" not in site_templates


def test_compatible_objects_returns_only_existing_typed_claim_ids() -> None:
    registry = ClaimRegistry.from_claims([
        _claim("facility-1", "facility", asset_kind="facility"),
        _claim("zone-1", "zone"),
        _claim("road-1", "road", asset_kind="road"),
    ])

    assert [item.ref_id for item in compatible_objects("serve", registry)] == [
        "facility-1",
        "zone-1",
    ]
    assert all(item.ref_id != "settlement:invented" for item in compatible_objects("serve", registry))


def test_source_fact_options_are_exact_and_spatially_filtered() -> None:
    facts = [
        SimpleNamespace(
            fact_id="l1:fact:road",
            fact_kind="spatial_observation",
            dimension_key="traffic",
            statement="现状道路",
        ),
        SimpleNamespace(
            fact_id="l1:fact:prose",
            fact_kind="document_observation",
            dimension_key="traffic",
            statement="规划背景",
        ),
    ]

    options = source_fact_options("traffic", "spatial_intervention", facts)

    assert [item.ref_id for item in options] == ["l1:fact:road"]


def test_source_fact_options_reject_noncanonical_fact_ids() -> None:
    facts = [
        SimpleNamespace(
            fact_id="l1:road:legacy",
            fact_kind="spatial_observation",
            dimension_key="traffic",
            statement="现状道路",
        ),
        SimpleNamespace(
            fact_id="l1:fact:canonical",
            fact_kind="spatial_observation",
            dimension_key="traffic",
            statement="现状道路（规范 ID）",
        ),
    ]

    options = source_fact_options("traffic", "spatial_intervention", facts)

    assert [item.ref_id for item in options] == ["l1:fact:canonical"]


def test_l3_candidate_context_exposes_exact_fact_catalog_and_spatial_subset(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1Fact
    from app.domain.program.worker import _l3_candidate_context

    context = SimpleNamespace(
        l1_fact_records=[
            L1Fact(
                fact_id="l1:fact:road",
                statement="现状道路",
                fact_kind="spatial_observation",
                dimension_key="traffic",
                semantic_type="road",
                source_refs=["report:traffic"],
            ),
            L1Fact(
                fact_id="l1:fact:background",
                statement="交通组织存在短板",
                fact_kind="document_observation",
                dimension_key="traffic",
                semantic_type="observation",
                source_refs=["report:traffic"],
            ),
        ]
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )

    payload = json.loads(
        _l3_candidate_context(
            {"session_id": "l3-candidate-context"},
            "traffic",
            ["traffic"],
        )
    )

    assert payload["source_fact_options"] == [
        "l1:fact:background",
        "l1:fact:road",
    ]
    assert payload["spatial_source_fact_options"] == ["l1:fact:road"]
    assert {
        item["fact_id"]: item["spatial_claim_allowed"]
        for item in payload["source_fact_catalog"]
    } == {
        "l1:fact:background": False,
        "l1:fact:road": True,
    }
    assert payload["source_fact_catalog_status"] == "usable"
    assert payload["source_fact_catalog_digest"]


def test_l3_prompt_uses_the_persisted_snapshot_instead_of_a_stale_context_cache(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1Fact, L1Snapshot
    from app.domain.program.worker import (
        _l3_candidate_context,
        _typed_l1_fact_evidence,
    )

    stale_context = SimpleNamespace(
        l1_fact_records=[L1Fact(
            fact_id="l1:fact:stale",
            statement="过期上下文事实",
            fact_kind="spatial_observation",
            dimension_key="traffic",
        )],
        location_facts=[],
    )
    snapshot = L1Snapshot(fact_records=[L1Fact(
        fact_id="l1:fact:current",
        statement="当前快照事实",
        fact_kind="spatial_observation",
        dimension_key="traffic",
    )])
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: stale_context,
    )
    monkeypatch.setattr(
        "app.infrastructure.artifacts.runtime.load_artifact",
        lambda _state, _key: snapshot,
    )
    state = {
        "session_id": "l3-snapshot-boundary",
        "artifact_refs": {"l1_snapshot": {"digest": "snapshot-current"}},
    }

    candidate_payload = json.loads(
        _l3_candidate_context(state, "traffic", ["traffic"])
    )
    evidence = _typed_l1_fact_evidence(
        state,
        "traffic",
        source_dimensions=["traffic"],
    )
    evidence_payload = json.loads(evidence[evidence.index("["):])

    assert candidate_payload["source_fact_options"] == ["l1:fact:current"]
    assert [item["fact_id"] for item in evidence_payload] == ["l1:fact:current"]
    assert "l1:fact:stale" not in evidence


def test_l3_source_fact_validation_rejects_unknown_and_non_spatial_refs(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1Fact
    from app.contracts.program import PlanningClaimSet
    from app.domain.program.worker import _spatial_claim_evidence_errors

    context = SimpleNamespace(
        l1_fact_records=[
            L1Fact(
                fact_id="l1:fact:road",
                statement="现状道路",
                fact_kind="spatial_observation",
                dimension_key="traffic",
                semantic_type="road",
                source_refs=["report:traffic"],
            ),
            L1Fact(
                fact_id="l1:fact:background",
                statement="交通组织存在短板",
                fact_kind="document_observation",
                dimension_key="traffic",
                semantic_type="observation",
                source_refs=["report:traffic"],
            ),
        ]
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )

    invalid = _claim("facility-1", "facility", asset_kind="facility").model_copy(
        update={
            "source_fact_refs": [
                "l1:fact:background",
                "l1:fact:missing",
            ]
        }
    )
    errors = _spatial_claim_evidence_errors(
        {"session_id": "l3-source-validation"},
        PlanningClaimSet(dimension_key="traffic", claims=[invalid]),
    )

    assert any("claim_unknown_source_fact" in error for error in errors)
    assert any("spatial_claim_non_spatial_fact" in error for error in errors)


def test_grounding_request_has_stable_typed_identity() -> None:
    request = create_grounding_request(
        claim_id="road-1",
        slot_path="spatial_requirements.relations[0].object_ref",
        expected_kind="network",
        query_text="沿金田河既有排水通道",
    )

    assert request.request_id.startswith("grounding:")
    assert request.expected_kind == "network"
    assert request.slot_path.endswith("object_ref")


def test_project_decomposition_separates_axis_zone_and_physical_components() -> None:
    plan = decompose_project_intent(ProjectIntentSkeleton(
        package_ref="pkg:cultural-corridor",
        statement="文化廊道连接村寨并服务周边居民点",
        component_kinds=("axis", "zone"),
        physical_kinds=("road",),
        semantic_relations=("connect_network", "serve"),
    ))

    kinds = {item.component_kind for item in plan.components}
    assert {"axis", "zone", "facility", "road"}.issubset(kinds)
