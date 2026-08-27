"""L1 typed-output recovery regressions."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.domain.assessment.observation_draft import L1ReportOutput


def _retry_exception_with_content(content: str):
    from instructor.core import InstructorRetryException

    completion = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=None),
            )
        ]
    )
    return InstructorRetryException(
        "No tool calls or function call found in response (mode: TOOLS)",
        last_completion=completion,
        n_attempts=1,
        total_usage=0,
    )


@pytest.mark.asyncio
async def test_l1_contract_rejects_content_json_without_tool_call(monkeypatch):
    from app.infrastructure.llm import structured

    class _Completions:
        async def create(self, **_kwargs):
            raise _retry_exception_with_content(
                '{"report_body":"道路现状清晰。"}'
            )

    class _Client:
        chat = type("_Chat", (), {"completions": _Completions()})()

    monkeypatch.setattr(structured, "get_async_instructor_client", lambda: _Client())
    monkeypatch.setattr(
        structured, "get_structured_model", lambda model=None: "deepseek-v4-flash"
    )

    with pytest.raises(Exception):
        await structured.run_structured_output(
            L1ReportOutput,
            [{"role": "user", "content": "return the typed L1 output"}],
            max_retries=1,
            timeout=2,
        )


def test_malformed_l1_failure_keeps_exact_dimension_and_never_completes():
    from app.workflow.conversation.edges import after_analysis

    state = {
        "phase": "layer1",
        "completed_dimensions": {"layer1": ["location"]},
        "dimension_failures": [{
            "stage": "L1",
            "dimension": "transportation",
            "code": "llm_typed_output_error",
            "message": "content is not complete strict JSON",
        }],
    }

    assert after_analysis(state) == "human_review"
    assert "transportation" not in state["completed_dimensions"]["layer1"]
    assert state["dimension_failures"][0]["code"] == "llm_typed_output_error"


@pytest.mark.asyncio
async def test_analyze_dimension_typed_exception_preserves_dimension_without_completion(
    monkeypatch,
):
    """Exercise the worker's real typed-output exception boundary offline."""

    from instructor.core import InstructorRetryException
    from app.domain.assessment import analysis_node
    from app.infrastructure.llm.dependency_context import DependencyContext

    cfg = SimpleNamespace(
        name="交通",
        layer=1,
        prefer_doc_types=None,
        tools=[],
        layer_depends_on=[],
    )

    async def _no_rag(*_args, **_kwargs):
        return "", None

    async def _no_deps(*_args, **_kwargs):
        return DependencyContext(
            dimension_key="transportation",
            layer=1,
            keys=(),
            artifacts=(),
        )

    async def _publish(*_args, **_kwargs):
        return None

    class _Stats:
        def start_dimension(self, *_args):
            return None

        def record_prompt(self, *_args):
            return None

    secret_model_body = "MODEL_BODY_SHOULD_NOT_LEAK" * 100
    runner_kwargs_seen: dict[str, object] = {}

    async def _typed_failure(*_args, **_kwargs):
        runner_kwargs_seen.update(_kwargs)
        raise InstructorRetryException(
            secret_model_body,
            last_completion=None,
            n_attempts=1,
            total_usage=0,
        )

    monkeypatch.setattr(analysis_node, "get_dimension_config", lambda _key: cfg)
    monkeypatch.setattr(analysis_node, "get_dimension_layer", lambda _key: 1)
    monkeypatch.setattr(analysis_node, "run_rag", _no_rag)
    monkeypatch.setattr(analysis_node, "load_dependency_context", _no_deps)
    monkeypatch.setattr(analysis_node, "publish_dimension_start", _publish)
    monkeypatch.setattr(analysis_node, "provider_failure_open", lambda _sid: False)
    monkeypatch.setattr(analysis_node, "dimension_failure_attempt", lambda state, key: {key: 1})
    monkeypatch.setattr(analysis_node, "_build_prompt", lambda *_args, **_kwargs: "prompt")
    monkeypatch.setattr(analysis_node, "run_rag", _no_rag)
    monkeypatch.setattr(
        "app.infrastructure.llm.structured.run_structured_output",
        _typed_failure,
    )
    monkeypatch.setattr(
        "app.infrastructure.events.event_hub.publish",
        _publish,
    )
    monkeypatch.setattr(
        "app.infrastructure.llm.stats_collector.StatsCollector.get_instance",
        lambda: _Stats(),
    )

    result = await analysis_node.analyze_dimension(
        {
            "dimension_key": "transportation",
            "session_id": "session-typed-failure",
            "phase": "layer1",
            "config": {},
        }
    )

    failure = result["provider_failures"][0]
    assert failure["dimension"] == "transportation"
    assert failure["code"] == "llm_typed_output_error"
    assert secret_model_body not in failure["message"]
    assert "completed_dimensions" not in result
    assert runner_kwargs_seen["max_retries"] == 0


def test_typed_output_failure_is_a_transient_code():
    from app.workflow.failure_codes import TRANSIENT_LLM_FAILURE_CODES

    assert "llm_typed_output_error" in TRANSIENT_LLM_FAILURE_CODES


@pytest.mark.parametrize(
    "code",
    ["L1_SNAPSHOT_LOAD_FAILED", "DATA_PIPELINE_FAILED"],
)
def test_l1_runtime_warning_never_logs_exception_body(monkeypatch, code):
    from app.domain.assessment import analysis_node

    warnings: list[tuple] = []
    secret = "MODEL_OR_TOOL_BODY_SHOULD_NOT_LEAK" * 100
    monkeypatch.setattr(
        analysis_node.logger,
        "warning",
        lambda *args, **_kwargs: warnings.append(args),
    )

    analysis_node._log_bounded_runtime_warning(
        "transportation",
        code,
        RuntimeError(secret),
    )

    rendered = " ".join(str(item) for warning in warnings for item in warning)
    assert secret not in rendered
    assert code in rendered
    assert "RuntimeError" in rendered


def test_retry_exhaustion_is_an_explicit_failed_diagnostic_terminal():
    from app.workflow.root_graph import _provider_resume_patch
    from app.workflow.plan_state.state import _preserve_fatal_error

    patch = _provider_resume_patch(
        {
            "phase": "layer1",
            "dimension_retry_limit": 1,
            "dimension_retry_counts": {"transportation": 2},
            "provider_failures": [{
                "stage": "L1",
                "dimension": "transportation",
                "code": "llm_typed_output_error",
            }],
        },
        [],
    )

    assert patch["fatal_error"]["code"] == "LLM_DIMENSION_RETRY_EXHAUSTED"
    assert patch["diagnostic_terminal"] == patch["fatal_error"]
    assert patch["delivery_status"] == "diagnostic_only"
    assert patch["phase"] == "completed"
    assert patch["status"] == "failed"
    assert _preserve_fatal_error(
        {"code": "llm_typed_output_error"}, patch["fatal_error"]
    ) == patch["fatal_error"]


@pytest.mark.asyncio
async def test_workflow_state_runtime_adapter_merge_persists_exhaustion_fatal_error():
    """Pin the compact WorkflowState channel, not only the legacy state."""

    from app.workflow.runtime_adapter import adapt_node, initial_workflow_state
    from app.workflow.state import _merge_fatal_error
    from app.workflow.root_graph import _provider_resume_patch

    exhaustion = _provider_resume_patch(
        {
            "phase": "layer1",
            "dimension_retry_limit": 1,
            "dimension_retry_counts": {"transportation": 2},
            "provider_failures": [{
                "stage": "L1",
                "dimension": "transportation",
                "code": "llm_typed_output_error",
            }],
        },
        [],
    )
    checkpoint = initial_workflow_state({
        "session_id": "session-compact-merge",
        "phase": "layer1",
        "fatal_error": {
            "stage": "L1",
            "dimension": "transportation",
            "code": "llm_typed_output_error",
        },
    })

    async def _terminal_patch(_state):
        return exhaustion

    packed = await adapt_node(_terminal_patch)(checkpoint)
    merged_fatal = _merge_fatal_error(
        checkpoint["fatal_error"], packed["fatal_error"]
    )

    assert packed["fatal_error"]["code"] == "LLM_DIMENSION_RETRY_EXHAUSTED"
    assert merged_fatal["code"] == "LLM_DIMENSION_RETRY_EXHAUSTED"
