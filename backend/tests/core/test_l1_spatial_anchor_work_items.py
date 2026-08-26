"""Regression tests for L1 semantic spatial work-item coverage."""

from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

from app.data.ingestion.compiler.profiles.l1_observation import (
    _dedup_location_facts_local,
    compile_l1_observation,
)
from app.domain.assessment.observation_draft import (
    l1_observation_output_model_for_dimension,
)


def _instruction(observations: list[dict]) -> str:
    return json.dumps({"observations": observations}, ensure_ascii=False)


_REPORT_FIXTURE = (
    Path(__file__).parents[1] / "fixtures" / "mvp_village" / "current_report.md"
)


def _spatial_mention(
    scope: str,
    *,
    instance_label: str = "",
    source_feature_ids: list[str] | None = None,
) -> dict:
    mention = {
        "target_name": "祠堂",
        "role": "facility",
        "village_scopes": [scope],
        "instance_label": instance_label,
        "instance_count": "3座",
        "resolution_state": "needs_retrieval",
    }
    if source_feature_ids is not None:
        mention["source_feature_ids"] = source_feature_ids
    return mention


def _required_fixture_fragment(source: str, fragment: str) -> str:
    start = source.find(fragment)
    assert start >= 0
    return source[start:start + len(fragment)]


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
    report_source = _REPORT_FIXTURE.read_text(encoding="utf-8")
    historical_fragment = _required_fixture_fragment(
        report_source,
        "社前村，黄竹村，田坑村具有三座祠堂",
    )
    demand_fragment = _required_fixture_fragment(
        report_source,
        "黄竹、杜前、田坑",
    )
    assert "祠堂修缮" in report_source
    conflicting_scopes = set(
        re.findall(r"[杜社]前", f"{historical_fragment}；{demand_fragment}")
    )
    assert conflicting_scopes == {"杜前", "社前"}

    snapshot = compile_l1_observation(
        dimension_key="villager_wishes",
        content="",
        instruction=_instruction([{
            "fact_type": "demand",
            "demand_type": "祠堂修缮",
            "scope": "金田村",
            "spatial_mentions": [
                _spatial_mention(scope)
                for scope in sorted(conflicting_scopes)
            ],
            "source_segment_ids": ["report:61", "report:102"],
            "source_quote": f"{historical_fragment}；{demand_fragment}",
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


def test_source_feature_identity_and_legacy_no_feature_deduplication() -> None:
    snapshot = compile_l1_observation(
        dimension_key="historical_culture",
        content="",
        instruction=_instruction([{
            "fact_type": "spatial_entity",
            "entity_type": "现状设施",
            "name": "祠堂",
            "spatial_mentions": [
                _spatial_mention(
                    "社前村",
                    source_feature_ids=["kg:ancestral-hall:one"],
                ),
                _spatial_mention(
                    "社前村",
                    source_feature_ids=["bundle:ancestral-hall:two"],
                ),
                _spatial_mention("社前村"),
                _spatial_mention("社前村"),
            ],
            "source_segment_ids": ["report:61"],
            "source_quote": "社前村具有三座祠堂",
            "status": "confirmed",
        }]),
        report_id="report:mvp",
    )

    assert {
        tuple(fact.source_feature_ids)
        for fact in snapshot.location_facts
    } == {
        ("kg:ancestral-hall:one",),
        ("bundle:ancestral-hall:two",),
        (),
    }


def test_default_unknown_target_role_is_not_promoted_from_village_scope() -> None:
    model = l1_observation_output_model_for_dimension("villager_wishes")
    output = model.model_validate({
        "observations": [{
            "fact_type": "demand",
            "demand_type": "祠堂修缮",
            "scope": "金田村",
            "spatial_mentions": [{
                "target_name": "祠堂",
                "village_scopes": ["社前村"],
            }],
            "source_segment_ids": ["report:102"],
            "source_quote": "祠堂修缮",
            "status": "confirmed",
        }],
    })

    snapshot = compile_l1_observation(
        dimension_key="villager_wishes",
        content="",
        instruction=output.model_dump_json(),
        report_id="report:mvp",
    )

    assert len(snapshot.location_facts) == 1
    fact = snapshot.location_facts[0]
    assert fact.target_name == "祠堂"
    assert fact.role == "unknown"
    assert fact.village_scopes == ["社前村"]


def test_production_l1_observe_prompt_includes_spatial_coverage_contract(
    monkeypatch,
) -> None:
    from app.domain.assessment.analysis_node import _build_prompt

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: None,
    )
    prompt = _build_prompt(
        SimpleNamespace(
            key="historical_culture",
            layer=1,
            name="历史文化资源分析",
        ),
        {
            "session_id": "l1-spatial-coverage-contract",
            "dimension_key": "historical_culture",
            "project_name": "金田村",
            "config": {"village_name": "金田村"},
        },
        rag_context="",
        structured_pass="l1_observe",
    )

    assert "【L1 空间覆盖契约；dimension_key=historical_culture】" in prompt
    assert "spatial_mentions" in prompt
    assert "resolution_state=needs_retrieval" in prompt
    assert "禁止猜坐标" in prompt
