"""Regression tests for L1 semantic spatial work-item coverage."""

from __future__ import annotations

import json

from app.data.ingestion.compiler.profiles.l1_observation import (
    _dedup_location_facts_local,
    compile_l1_observation,
)
from app.domain.assessment.observation_draft import (
    l1_observation_output_model_for_dimension,
)


def _instruction(observations: list[dict]) -> str:
    return json.dumps({"observations": observations}, ensure_ascii=False)


def _spatial_mention(scope: str, *, instance_label: str = "") -> dict:
    return {
        "target_name": "祠堂",
        "role": "facility",
        "village_scopes": [scope],
        "instance_label": instance_label,
        "instance_count": "3座",
        "resolution_state": "needs_retrieval",
    }


def test_l1_observe_contract_accepts_spatial_mentions_without_geometry() -> None:
    model = l1_observation_output_model_for_dimension("socio_economic")
    output = model.model_validate({
        "observations": [{
            "fact_type": "scoped_metric",
            "metric": "ancestral_halls",
            "scope": "金田村",
            "description": "祠堂3座，分布于社前村、黄竹村、田坑村",
            "spatial_mentions": [_spatial_mention(name) for name in ("社前村", "黄竹村", "田坑村")],
            "source_segment_ids": ["report:61"],
            "source_quote": "社前村、黄竹村、田坑村具有三座祠堂",
            "status": "confirmed",
        }],
    })
    assert len(output.observations[0].spatial_mentions) == 3
    assert all(
        item.resolution_state == "needs_retrieval"
        for item in output.observations[0].spatial_mentions
    )


def test_compiler_expands_three_shrine_scopes_and_retains_metric() -> None:
    snapshot = compile_l1_observation(
        dimension_key="socio_economic",
        content="",
        instruction=_instruction([{
            "fact_type": "scoped_metric",
            "metric": "ancestral_halls",
            "scope": "金田村",
            "description": "祠堂3座，分布于社前村、黄竹村、田坑村",
            "spatial_mentions": [_spatial_mention(name) for name in ("社前村", "黄竹村", "田坑村")],
            "source_segment_ids": ["report:61"],
            "source_quote": "社前村、黄竹村、田坑村具有三座祠堂",
            "status": "confirmed",
        }]),
        report_id="report:mvp",
    )

    assert len(snapshot.fact_records) == 1
    assert snapshot.fact_records[0].attributes["spatial_mention_count"] == "3"
    assert {
        (fact.target_name, tuple(fact.village_scopes), fact.role)
        for fact in snapshot.location_facts
    } == {
        ("祠堂", ("社前村",), "facility"),
        ("祠堂", ("黄竹村",), "facility"),
        ("祠堂", ("田坑村",), "facility"),
    }
    assert all(fact.provenance.source_quote for fact in snapshot.location_facts)
    assert all(fact.resolution_state == "needs_retrieval" for fact in snapshot.location_facts)


def test_demand_target_name_is_not_generic_protection_label() -> None:
    snapshot = compile_l1_observation(
        dimension_key="villager_wishes",
        content="",
        instruction=_instruction([{
            "fact_type": "demand",
            "demand_type": "祠堂修缮",
            "scope": "金田村",
            "spatial_requirement": "place_binding",
            "spatial_mentions": [
                {
                    "target_name": "祠堂",
                    "role": "facility",
                    "village_scopes": [name],
                    "resolution_state": "needs_retrieval",
                }
                for name in ("黄竹村", "社前村", "田坑村")
            ],
            "source_segment_ids": ["report:102"],
            "source_quote": "祠堂修缮",
            "status": "confirmed",
        }]),
        report_id="report:mvp",
    )

    assert {fact.target_name for fact in snapshot.location_facts} == {"祠堂"}
    assert {fact.normalized_name for fact in snapshot.location_facts} == {"祠堂"}


def test_scope_near_duplicate_is_diagnostic_only() -> None:
    snapshot = compile_l1_observation(
        dimension_key="villager_wishes",
        content="",
        instruction=_instruction([{
            "fact_type": "demand",
            "demand_type": "祠堂修缮",
            "scope": "金田村",
            "spatial_mentions": [
                _spatial_mention("杜前"),
                _spatial_mention("社前"),
            ],
            "source_segment_ids": ["report:61", "report:102"],
            "source_quote": "社前村、黄竹村、田坑村；杜前",
            "status": "confirmed",
        }]),
        report_id="report:mvp",
    )

    assert {fact.spatial_hint for fact in snapshot.location_facts} == {"杜前", "社前"}
    conflicts = [
        item for item in snapshot.diagnostics_by_dimension["villager_wishes"]
        if item.code == "L1_SCOPE_CONFLICT_CANDIDATE"
    ]
    assert conflicts
    assert "杜前" in conflicts[0].message and "社前" in conflicts[0].message


def test_scope_and_instance_are_part_of_local_deduplication() -> None:
    snapshot = compile_l1_observation(
        dimension_key="historical_culture",
        content="",
        instruction=_instruction([{
            "fact_type": "spatial_entity",
            "entity_type": "现状设施",
            "name": "祠堂",
            "locator": {"place_names": ["社前村"]},
            "spatial_mentions": [
                _spatial_mention("社前村", instance_label="祠堂-A"),
                _spatial_mention("社前村", instance_label="祠堂-B"),
                _spatial_mention("社前村", instance_label="祠堂-A"),
            ],
            "source_segment_ids": ["report:61"],
            "source_quote": "社前村具有三座祠堂",
            "status": "confirmed",
        }]),
        report_id="report:mvp",
    )

    assert len(snapshot.location_facts) == 2
    assert {fact.instance_label for fact in snapshot.location_facts} == {"祠堂-A", "祠堂-B"}
    assert len(_dedup_location_facts_local(snapshot.location_facts)) == 2
