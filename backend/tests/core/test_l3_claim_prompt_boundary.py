from __future__ import annotations

from types import SimpleNamespace


def _context_for_prompt():
    from app.contracts.domain.l1_contracts import L1Fact, L1LocationFact

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
        location_facts=[
            L1LocationFact(
                mention="金田古建筑群",
                normalized_name="金田古建筑群",
                role="heritage_site",
                spatial_hint="村域中部",
                source_report_ref="source_report_ref:foreign-id",
                dimension_key="historical_culture",
                evidence_refs=["l1:source:historical-culture-001"],
            )
        ],
        input_text=lambda _key, default: default,
    )


def test_claims_prompt_uses_configured_source_dimensions_and_exact_ids(monkeypatch):
    from app.domain.program.worker import _build_prompt

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: _context_for_prompt(),
    )
    prompt = _build_prompt(
        SimpleNamespace(key="heritage", layer_depends_on=["historical_culture"]),
        {"session_id": "prompt-boundary", "dimension_key": "heritage"},
    )

    assert '"dimension_key": "historical_culture"' in prompt
    assert "l1:fact:historical-culture-001" in prompt
    assert "source_report_ref:foreign-id" in prompt


def test_claims_prompt_has_no_unbound_metric_placeholders_or_legacy_output_order():
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt(
        "heritage",
        project_name="金田村",
        analysis_report="",
        planning_concept="",
        constraints="",
        knowledge_context="",
        dimension_plans="",
        semantic_contract="upstream_source_dimensions: [historical_culture]",
        evidence_context="typed facts",
    )

    assert "{landuse_metrics_farmland}" not in prompt
    assert "claims-only" in prompt
    assert "旧报告模板中的表格和‘至少列出’只是背景" in prompt
    assert "结构化 schema 是字段、组件类型和参数块的唯一约束来源" in prompt
    assert "candidate_context" in prompt


def test_non_spatial_claims_are_not_required_to_have_spatial_anchors():
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt(
        "industry",
        project_name="金田村",
        semantic_contract="industry contract",
    )

    assert "非空间指标可以没有 locator" in prompt
    assert "空间组件即使还没有 locator 也要保留语义" in prompt


def test_claims_prompt_has_reusable_package_typed_and_lineage_emit_checklist():
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt(
        "project_bank",
        project_name="金田村",
        semantic_contract="project package contract",
        location_evidence='{"fact_id":"l1:fact:001","source_refs":["l1:source:001"]}',
    )

    assert "复用同一个 project_package_ref" in prompt
    assert "source_fact_refs 只能逐字复制" in prompt
    assert "没有合适身份就留空" in prompt
