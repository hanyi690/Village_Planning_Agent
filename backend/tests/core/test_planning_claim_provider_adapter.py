"""Provider-boundary recovery tests for structured L3 claim responses."""

from __future__ import annotations

import asyncio
import json
import logging
from types import SimpleNamespace

import pytest

from app.infrastructure.llm.planning_claims import PlanningClaimGenerator


class _StructuredInvoker:
    def __init__(self) -> None:
        self.calls = 0
        self.messages = []

    async def ainvoke(self, _messages):
        self.calls += 1
        self.messages.append(_messages)
        if self.calls == 1:
            return {"claims": "[{claim_id: broken}]"}
        return {
            "claims": [
                {
                    "claim_family": "facility",
                    "statement": "Provide a small agricultural service point.",
                    "planning_role": "spatial_intervention",
                }
            ],
        }


class _FakeLLM:
    def __init__(self, invoker: _StructuredInvoker) -> None:
        self.invoker = invoker

    def with_structured_output(self, *_args, **_kwargs):
        return self.invoker


def test_provider_adapter_retries_malformed_nested_json(monkeypatch):
    invoker = _StructuredInvoker()
    generator = PlanningClaimGenerator()
    generator._llm = _FakeLLM(invoker)
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "1")

    result = asyncio.run(generator.generate_claims(
        "Generate one planning claim.",
        source_fact_ids=(),
        spatial_source_fact_ids=(),
    ))

    assert invoker.calls == 2
    assert result.claims[0].claim_family == "facility"
    assert "claims" in invoker.messages[0][1]["content"]
    assert "PlanningClaimSet only" not in invoker.messages[0][1]["content"]


def test_provider_adapter_quarantines_schema_failure_with_auditable_counts(
    monkeypatch, caplog
):
    class _InvalidInvoker:
        async def ainvoke(self, _messages):
            return {
                "claims": [
                    {
            "claim_family": "facility",
            "statement": "invalid source ref",
            "source_fact_refs": 7,
                    }
                ]
            }

    class _InvalidLLM:
        def with_structured_output(self, *_args, **_kwargs):
            return _InvalidInvoker()

    generator = PlanningClaimGenerator()
    generator._llm = _InvalidLLM()
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "0")

    with caplog.at_level(logging.WARNING):
        result = asyncio.run(
            generator.generate_claims(
                "Generate one planning claim.",
                source_fact_ids=(),
                spatial_source_fact_ids=(),
            )
        )

    assert len(result.claims) == 1
    assert result.claims[0].source_fact_refs == ["7"]
    records = [
        record.getMessage()
        for record in caplog.records
        if "[planning_claims] output_observation=" in record.getMessage()
    ]
    assert records
    observation = json.loads(records[-1].split("output_observation=", 1)[1])
    assert observation["failure_code"] is None
    assert observation["failure_kind"] is None
    assert observation["root_type"] == "dict"
    assert observation["finish_reason"] is None
    assert observation["claim_counts"] == {
        "emitted": 1,
        "accepted": 1,
        "quarantined": 0,
    }
    assert "claim-with-invalid-ref" not in records[-1]


def test_provider_adapter_does_not_quarantine_provider_infrastructure_failure(
    monkeypatch, caplog
):
    class _TransportInvoker:
        async def ainvoke(self, _messages):
            raise ConnectionError("provider socket closed")

    class _TransportLLM:
        def with_structured_output(self, *_args, **_kwargs):
            return _TransportInvoker()

    generator = PlanningClaimGenerator()
    generator._llm = _TransportLLM()
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "0")
    monkeypatch.setenv("L3_TRANSIENT_RETRIES", "0")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(ValueError, match="PROVIDER_TRANSPORT"):
            asyncio.run(
                generator.generate_claims(
                    "Generate one planning claim.",
                    source_fact_ids=(),
                    spatial_source_fact_ids=(),
                )
            )

    records = [
        record.getMessage()
        for record in caplog.records
        if "[planning_claims] output_observation=" in record.getMessage()
    ]
    assert records
    observation = json.loads(records[-1].split("output_observation=", 1)[1])
    assert observation["failure_kind"] == "provider_infrastructure"
    assert observation["failure_code"] == "PROVIDER_TRANSPORT"
    assert observation["claim_counts"] == {
        "emitted": None,
        "accepted": 0,
        "quarantined": 0,
    }


def test_provider_adapter_closes_fact_ids_after_structured_parse() -> None:
    from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model

    model = _dynamic_claim_output_model(
        ["l1:fact:current", "l1:fact:background"],
        ["l1:fact:current"],
    )
    output = model.model_validate({
        "claims": [{
            "claim_family": "facility",
            "statement": "配置公共服务设施",
            "source_fact_refs": ["l1:fact:background"],
        }],
    })
    from app.domain.program.worker import _sanitize_l3_provider_component

    sanitized, diagnostics = _sanitize_l3_provider_component(
        output.claims[0],
        source_fact_ids=("l1:fact:current",),
        spatial_source_fact_ids=("l1:fact:current",),
    )
    assert sanitized["source_fact_refs"] == []
    assert any("l3_source_fact_closed_set" in item for item in diagnostics)


def test_l3_projection_cache_is_written_only_by_validated_caller(tmp_path, monkeypatch) -> None:
    from app.domain.program.claim_draft import L3RoughClaimOutput
    from app.domain.program import worker

    monkeypatch.setattr(
        "app.infrastructure.paths.session_run_dir",
        lambda _session_id: tmp_path,
    )

    class _Generator:
        async def generate_claims(self, _prompt, **_kwargs):
            return L3RoughClaimOutput()

    output = asyncio.run(worker._cached_claim_only_generation(
        _Generator(),
        session_id="l3-cache-boundary",
        dimension_key="traffic",
        prompt="claims prompt",
        source_fact_ids=(),
        spatial_source_fact_ids=(),
    ))

    assert list(tmp_path.rglob("*.json")) == []
    worker._persist_validated_claims(
        session_id="l3-cache-boundary",
        dimension_key="traffic",
        prompt="claims prompt",
        generated=output,
        source_fact_ids=(),
        spatial_source_fact_ids=(),
    )
    assert len(list(tmp_path.rglob("*.json"))) == 1


def test_l3_projection_cache_revalidates_current_fact_closed_set(tmp_path, monkeypatch) -> None:
    from app.domain.program import worker
    from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model

    monkeypatch.setattr(
        "app.infrastructure.paths.session_run_dir",
        lambda _session_id: tmp_path,
    )
    response_model = _dynamic_claim_output_model(
        ["l1:fact:current"],
        ["l1:fact:current"],
    )
    generated = response_model.model_validate({
        "claims": [{
            "claim_family": "facility",
            "statement": "配置公共服务设施",
            "source_fact_refs": ["l1:fact:current"],
        }],
    })
    worker._persist_validated_claims(
        session_id="l3-cache-closed-set",
        dimension_key="public_services",
        prompt="claims prompt",
        generated=generated,
        source_fact_ids=("l1:fact:current",),
        spatial_source_fact_ids=("l1:fact:current",),
    )
    cache_path = next(tmp_path.rglob("*.json"))
    cached_payload = json.loads(cache_path.read_text(encoding="utf-8"))
    cached_payload["claims"][0]["source_fact_refs"] = ["l1:fact:stale"]
    cache_path.write_text(
        json.dumps(cached_payload, ensure_ascii=False),
        encoding="utf-8",
    )

    class _Generator:
        calls = 0

        async def generate_claims(self, _prompt, **_kwargs):
            self.calls += 1
            return generated

    generator = _Generator()
    result = asyncio.run(worker._cached_claim_only_generation(
        generator,
        session_id="l3-cache-closed-set",
        dimension_key="public_services",
        prompt="claims prompt",
        source_fact_ids=("l1:fact:current",),
        spatial_source_fact_ids=("l1:fact:current",),
    ))

    assert generator.calls == 1
    assert result.claims[0].source_fact_refs == ["l1:fact:current"]


def test_l3_intent_summary_cache_does_not_reuse_empty_body(tmp_path, monkeypatch) -> None:
    from app.domain.program import worker
    from app.domain.program.claim_draft import L3IntentSummaryOutput

    monkeypatch.setattr(
        "app.infrastructure.paths.session_run_dir",
        lambda _session_id: tmp_path,
    )
    prompt = "report prompt"
    cache_key = worker._projection_cache_key(
        prompt=prompt,
        validation_feedback=None,
        response_model=L3IntentSummaryOutput,
        cache_contract="l3-intent-summary-v1",
    )
    cache_path = worker._projection_cache_path(
        "l3-report-empty-cache",
        "traffic",
        cache_key,
        "intent_summary",
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"summary_body": ""}), encoding="utf-8")

    class _Generator:
        calls = 0

        async def generate_intent_summary(self, _prompt):
            self.calls += 1
            return L3IntentSummaryOutput(summary_body="fresh summary")

    generator = _Generator()
    result = asyncio.run(worker._cached_intent_summary_generation(
        generator,
        session_id="l3-report-empty-cache",
        dimension_key="traffic",
        prompt=prompt,
    ))

    assert generator.calls == 1
    assert result.summary_body == "fresh summary"


def test_l3_worker_rejects_empty_intent_summary() -> None:
    from app.domain.program.worker import L3IntentSummaryEmptyError, _require_l3_intent_summary

    with pytest.raises(L3IntentSummaryEmptyError, match="L3_INTENT_SUMMARY_EMPTY"):
        _require_l3_intent_summary("  ")
    assert _require_l3_intent_summary("【规划】摘要") == "【规划】摘要"


def test_l3_report_id_is_stable_for_checkpoint_replay() -> None:
    from app.domain.program.worker import _stable_report_id

    first = _stable_report_id("session-a", "traffic", 2)
    second = _stable_report_id("session-a", "traffic", 2)

    assert first == second
    assert first != _stable_report_id("session-a", "traffic", 3)
    assert first != _stable_report_id("session-b", "traffic", 2)


def test_immediate_report_save_exposes_storage_failure() -> None:
    from app.infrastructure.llm.dimension_runtime import save_report_immediate

    class Store:
        async def bulk_save(self, _reports):
            raise OSError("database unavailable")

    result = asyncio.run(save_report_immediate(Store(), {
        "dimension_key": "traffic",
        "version": 1,
    }))

    assert result is False


def test_pending_report_flush_deduplicates_logical_versions() -> None:
    from app.workflow.plan_state.completion_node import _flush_pending_reports

    class Store:
        def __init__(self):
            self.saved = []

        async def bulk_save(self, reports):
            self.saved.extend(reports)

    store = Store()
    report = {
        "session_id": "session-a",
        "dimension_key": "traffic",
        "version": 1,
        "report_id": "report:stable",
    }
    result = asyncio.run(_flush_pending_reports(store, [report, dict(report)]))

    assert result == (True, [], "")
    assert store.saved == [report]


def test_l3_prompt_exposes_split_projections_and_typed_fact_ids(monkeypatch) -> None:
    from app.contracts.domain.l1_contracts import L1Fact
    from app.domain.program.worker import _build_prompt

    context = SimpleNamespace(
        l1_fact_records=[L1Fact(
            fact_id="l1:fact:road-one",
            statement="现状村道需要提升",
            fact_kind="document_observation",
            dimension_key="traffic",
            semantic_type="road",
            attributes={"normalized_name": "村道"},
            source_refs=["report:traffic"],
            source_feature_ids=["feature:road:one"],
        )],
        input_text=lambda _key, default: default,
    )
    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: context,
    )

    prompt = _build_prompt(
        SimpleNamespace(key="traffic"),
        {"session_id": "prompt-test", "dimension_key": "traffic"},
        l2_deps="完善道路连接。",
        same_layer_contexts="",
    )

    assert "report_body" in prompt
    assert "claims-only" in prompt
    assert "l1:fact:road-one" in prompt
    assert "feature:road:one" in prompt
    assert "source_fact_refs" in prompt
    assert "现状道路分布于村庄主要居民点。" not in prompt
    assert "旧报告模板" not in prompt


def test_l3_prompt_keeps_dependency_projection_structure_intact(monkeypatch) -> None:
    from app.domain.program.worker import _build_prompt

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: SimpleNamespace(input=lambda: {}, input_text=lambda _key, default: default),
    )
    prompt = _build_prompt(
        SimpleNamespace(key="industry"),
        {"session_id": "prompt-budget-test", "dimension_key": "industry"},
        l2_deps="| decision_type | statement_or_name |\n| --- | --- |\n| objective | 优先提升可达性 |",
        same_layer_contexts="| claim_family | statement |\n| --- | --- |\n| road | 避免重复道路意图 |",
    )

    assert "report:l1" not in prompt
    assert "现状事实摘要" not in prompt
    assert "优先提升可达性" in prompt
    assert "避免重复道路意图" in prompt
    assert "已截断" not in prompt
