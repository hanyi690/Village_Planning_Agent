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
    assert "旧报告模板中的表格和‘至少列出’不是本轮输出指令" in prompt
    assert "suggested_output_kind 只能是 parcel/polygon/point/line/action" in prompt
    assert "avoid_constraint、near、serve、connect_network" in prompt
    assert "suggested_category=action、suggested_output_kind=action、asset_kind=none" in prompt


def test_non_spatial_claims_are_not_required_to_have_spatial_anchors():
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt(
        "industry",
        project_name="金田村",
        semantic_contract="industry contract",
    )

    assert "非空间指标可以没有 locator" in prompt
    assert "空间干预 claim 才需要" in prompt


def test_claims_prompt_has_reusable_package_typed_and_lineage_emit_checklist():
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt(
        "project_bank",
        project_name="金田村",
        semantic_contract="project package contract",
        location_evidence='{"fact_id":"l1:fact:001","source_refs":["l1:source:001"]}',
    )

    assert "只有 planning_role=spatial_intervention 或 project_package 的 claim 才必须有非空 project_package_ref" in prompt
    assert "对同一交付物的相关 claim 原样复用" in prompt
    assert "先选 category/output 的合法组合，再填写且只填写一个对应 typed 参数块" in prompt
    assert "L1 planning fact_id→source_fact_refs" in prompt
    assert "typed facts 的 source_refs→source_refs" in prompt
    assert "没有明确 ID 时保持引用为空，不得编造" in prompt
