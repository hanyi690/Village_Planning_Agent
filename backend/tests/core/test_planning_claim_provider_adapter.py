"""Provider-boundary recovery tests for structured L3 claim responses."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

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
                    "component_kind": "facility",
                    "claim_id": "industry-1",
                    "statement": "Provide a small agricultural service point.",
                    "intervention_action": "new",
                    "facility_parameters": {
                        "facility_type": "service point",
                        "action": "new",
                    },
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
    assert result.claims[0].claim_id == "industry-1"
    assert "claims" in invoker.messages[0][1]["content"]
    assert "PlanningClaimSet only" not in invoker.messages[0][1]["content"]


def test_provider_adapter_builds_dynamic_fact_id_closed_set() -> None:
    from app.infrastructure.llm.planning_claims import _dynamic_claim_output_model

    model = _dynamic_claim_output_model(
        ["l1:fact:current", "l1:fact:background"],
        ["l1:fact:current"],
    )
    schema_text = str(model.model_json_schema())

    assert "l1:fact:current" in schema_text
    assert "l1:fact:background" in schema_text
    with pytest.raises(ValidationError):
        model.model_validate({
            "claims": [{
                "component_kind": "facility",
                "claim_id": "facility-1",
                "intervention_action": "new",
                "facility_parameters": {"action": "new"},
                "source_fact_refs": ["l1:fact:background"],
            }],
        })
    empty_model = _dynamic_claim_output_model([], [])
    with pytest.raises(ValidationError):
        empty_model.model_validate({
            "claims": [{
                "component_kind": "facility",
                "claim_id": "facility-empty-catalog",
                "intervention_action": "new",
                "facility_parameters": {"action": "new"},
                "source_fact_refs": [None],
            }],
        })


def test_provider_adapter_fail_closes_tool_call_missing_without_reask(monkeypatch) -> None:
    import app.infrastructure.llm.planning_claims as planning_claims
    from app.infrastructure.llm.structured import structured_failure_code

    calls = 0

    async def fail_once(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("No tool calls or function call found in response")

    monkeypatch.setattr(planning_claims, "run_structured_output", fail_once)
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "1")

    with pytest.raises(ValueError, match="TOOL_CALL_MISSING") as raised:
        asyncio.run(PlanningClaimGenerator().generate_claims(
            "Generate one planning claim.",
            source_fact_ids=(),
            spatial_source_fact_ids=(),
        ))

    assert calls == 1
    assert structured_failure_code(raised.value) == "TOOL_CALL_MISSING"


def test_provider_adapter_does_not_turn_none_into_empty_claims(monkeypatch) -> None:
    import app.infrastructure.llm.planning_claims as planning_claims
    from app.infrastructure.llm.structured import structured_failure_code

    calls = 0

    async def return_none(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return None

    monkeypatch.setattr(planning_claims, "run_structured_output", return_none)
    monkeypatch.setenv("L3_PROVIDER_PARSE_RETRIES", "0")

    with pytest.raises(ValueError, match="TOOL_CALL_MISSING") as raised:
        asyncio.run(PlanningClaimGenerator().generate_claims(
            "Generate one planning claim.",
            source_fact_ids=(),
            spatial_source_fact_ids=(),
        ))

    assert calls == 1
    assert structured_failure_code(raised.value) == "TOOL_CALL_MISSING"


def test_l3_projection_cache_is_written_only_by_validated_caller(tmp_path, monkeypatch) -> None:
    from app.domain.program.claim_draft import L3ClaimOutput
    from app.domain.program import worker

    monkeypatch.setattr(
        "app.infrastructure.paths.session_run_dir",
        lambda _session_id: tmp_path,
    )

    class _Generator:
        async def generate_claims(self, _prompt, **_kwargs):
            return L3ClaimOutput()

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
            "component_kind": "facility",
            "claim_id": "facility-1",
            "statement": "配置公共服务设施",
            "intervention_action": "new",
            "facility_parameters": {"action": "new"},
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


def test_l3_report_cache_does_not_reuse_empty_body(tmp_path, monkeypatch) -> None:
    from app.domain.program import worker
    from app.domain.program.claim_draft import L3ReportOutput

    monkeypatch.setattr(
        "app.infrastructure.paths.session_run_dir",
        lambda _session_id: tmp_path,
    )
    prompt = "report prompt"
    cache_key = worker._projection_cache_key(
        prompt=prompt,
        validation_feedback=None,
        response_model=L3ReportOutput,
        cache_contract="l3-report-only-v2",
    )
    cache_path = worker._projection_cache_path(
        "l3-report-empty-cache",
        "traffic",
        cache_key,
        "report",
    )
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps({"report_body": ""}), encoding="utf-8")

    class _Generator:
        calls = 0

        async def generate_report(self, _prompt):
            self.calls += 1
            return L3ReportOutput(report_body="fresh report")

    generator = _Generator()
    result = asyncio.run(worker._cached_report_generation(
        generator,
        session_id="l3-report-empty-cache",
        dimension_key="traffic",
        prompt=prompt,
    ))

    assert generator.calls == 1
    assert result.report_body == "fresh report"


def test_provider_adapter_queue_wait_is_bounded(monkeypatch):
    import app.infrastructure.llm.planning_claims as planning_claims

    generator = PlanningClaimGenerator()
    generator._slots = asyncio.Semaphore(1)
    monkeypatch.setattr(planning_claims, "LLM_STREAM_TIMEOUT", 0.01)

    async def scenario():
        await generator._slots.acquire()
        try:
            with pytest.raises(asyncio.TimeoutError):
                await generator.generate_claims(
                    "Generate one planning claim.",
                    source_fact_ids=(),
                    spatial_source_fact_ids=(),
                )
        finally:
            generator._slots.release()

    asyncio.run(scenario())


def test_l3_worker_rejects_empty_human_report_body() -> None:
    from app.domain.program.worker import L3ReportBodyEmptyError, _require_l3_report_body

    with pytest.raises(L3ReportBodyEmptyError, match="L3_REPORT_BODY_EMPTY"):
        _require_l3_report_body("  ")
    assert _require_l3_report_body("【规划】正文") == "【规划】正文"


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
        l1_deps="现状道路分布于村庄主要居民点。",
        l2_deps="完善道路连接。",
    )

    assert "report_body" in prompt
    assert "结构化 schema 是字段、组件类型和参数块的唯一约束来源" in prompt
    assert "report-synthesis pass" in prompt
    assert "l1:fact:road-one" in prompt
    assert "feature:road:one" in prompt
    assert "source_fact_refs" in prompt
    assert "现状道路分布于村庄主要居民点。" in prompt
    assert "旧报告模板中的表格和‘至少列出’只是背景" in prompt


def test_l3_prompt_bounds_upstream_background_for_provider_context(monkeypatch) -> None:
    from app.domain.program.worker import _build_prompt

    monkeypatch.setattr(
        "app.infrastructure.context.planning_context_factory.get_cached_context",
        lambda _session_id: SimpleNamespace(input=lambda: {}, input_text=lambda _key, default: default),
    )
    prompt = _build_prompt(
        SimpleNamespace(key="industry"),
        {"session_id": "prompt-budget-test", "dimension_key": "industry"},
        l1_deps="L1" * 10000,
        l2_deps="L2" * 10000,
        same_layer_contexts="same" * 10000,
    )

    assert len(prompt) < 24000
    assert "【L1 现状分析已截断】" in prompt
    assert "【L2 规划思路已截断】" in prompt
