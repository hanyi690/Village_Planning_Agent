from __future__ import annotations

from types import SimpleNamespace


def _context_for_prompt():
    from app.contracts.domain.l1_contracts import L1Fact

    return SimpleNamespace(
        l1_fact_records=[
            L1Fact(
                fact_id="l1:fact:historical-culture-001",
                statement="金田古建筑群具有传统风貌保护价值",
                fact_kind="spatial_observation",
                dimension_key="historical_culture",
                semantic_type="heritage_site",
                subject_scope="金田村",
                attributes={"normalized_name": "金田古建筑群"},
                source_refs=["l1:source:historical-culture-001"],
                source_feature_ids=["feature:heritage:001"],
            ),
            L1Fact(
                fact_id="l1:fact:traffic-001",
                statement="村道连接居民点",
                fact_kind="spatial_observation",
                dimension_key="traffic",
                semantic_type="road",
                subject_scope="金田村",
                source_refs=["l1:source:traffic-001"],
                source_feature_ids=["feature:road:001"],
            ),
        ],
        location_facts=[],
        input_text=lambda _key, default: default,
    )


def test_l3_prompt_uses_only_canonical_fact_projection(monkeypatch):
    from app.domain.program.worker import _build_prompt

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: _context_for_prompt(),
    )
    prompt = _build_prompt(
        SimpleNamespace(key="heritage", layer_depends_on=["historical_culture"]),
        {"session_id": "prompt-boundary", "dimension_key": "heritage"},
    )

    assert "l1:fact:historical-culture-001" in prompt
    assert "l1:source:historical-culture-001" in prompt
    assert "source_report_ref:foreign-id" not in prompt
    assert "relation_template" in prompt
    assert "geometry" in prompt
    assert "候选" in prompt


def test_l3_prompt_has_rough_intent_boundary_and_no_execution_fields():
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt(
        "heritage",
        project_name="金田村",
        l1_facts="| fact_id | statement |\n| --- | --- |\n| l1:fact:1 | 古建筑 |",
        l2_decisions="| decision_type | statement_or_name |\n| --- | --- |\n| objective | 保护风貌 |",
        same_layer_claims="",
        evidence_context="| fact_id | statement |\n| --- | --- |\n| evidence:1 | 保护价值 |",
        semantic_contract="允许的 L3 claim family：protection, action",
    )

    assert "claims-only" in prompt
    assert "粗粒度" in prompt
    assert "非可执行" in prompt
    assert "grounding_requirements" in prompt
    assert "relation_template" in prompt
    assert "项目包拆解" in prompt
    assert "geometry" in prompt
    assert "candidate" in prompt
    assert "report_body" in prompt
    assert "l1:fact:1" in prompt
    assert "保护风貌" in prompt
    assert "保护价值" in prompt


def test_legacy_sections_are_not_consumed_by_l3_prompt():
    import inspect

    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    parameters = inspect.signature(get_dimension_prompt).parameters

    assert "analysis_report" not in parameters
    assert "planning_concept" not in parameters
    assert "professional_data_section" not in parameters
    assert "location_evidence" not in parameters
    assert "candidate_context" not in parameters
    assert "dimension_plans" not in parameters
