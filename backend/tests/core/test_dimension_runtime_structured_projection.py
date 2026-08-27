import json

import pytest


@pytest.mark.asyncio
async def test_dimension_complete_accepts_only_validated_summary_model(monkeypatch) -> None:
    from app.data.ingestion.summary_generator import build_derived_summary
    from app.infrastructure.llm.dimension_runtime import publish_dimension_complete

    events: list[dict] = []

    async def publish(_session_id, event):
        events.append(event)

    monkeypatch.setattr("app.infrastructure.events.event_hub.publish", publish)

    await publish_dimension_complete(
        "session-1",
        "traffic",
        "交通",
        12,
        {
            "authority": "derived_summary",
            "dimension_key": "traffic",
            "layer": 1,
            "unexpected_semantics": "new road",
        },
        "report-1",
        1,
        1,
        False,
    )
    assert events[0]["structured_summary"] is None

    summary = build_derived_summary("traffic", 1, word_count=12)
    await publish_dimension_complete(
        "session-1",
        "traffic",
        "交通",
        12,
        summary,
        "report-1",
        1,
        1,
        False,
    )
    assert events[1]["structured_summary"]["authority"] == "derived_summary"


@pytest.mark.asyncio
async def test_generate_summary_has_one_typed_generation_boundary(monkeypatch) -> None:
    from app.data.ingestion.summary_generator import build_derived_summary
    from app.infrastructure.llm import dimension_runtime

    calls: list[tuple[str, int, str]] = []

    async def generate_summary_model(
        dimension_key: str,
        layer: int,
        content: str,
        *,
        source_artifact=None,
    ):
        calls.append((dimension_key, layer, content))
        return build_derived_summary(
            dimension_key,
            layer,
            word_count=len(content),
            text_summary="动态摘要",
        )

    monkeypatch.setattr(
        "app.data.ingestion.summary_generator.generate_summary_model",
        generate_summary_model,
    )

    serialized = await dimension_runtime.generate_summary(
        "traffic",
        1,
        "报告正文",
        source_artifact={"report_body": "报告正文", "typed_instruction": {}},
    )

    assert calls == [("traffic", 1, "报告正文")]
    assert json.loads(serialized)["text_summary"] == "动态摘要"


@pytest.mark.asyncio
async def test_generate_summary_does_not_replace_generation_failure_with_semantics(monkeypatch) -> None:
    from app.infrastructure.llm import dimension_runtime

    async def fail_generation(*_args, **_kwargs):
        raise RuntimeError("structured generation failed")

    monkeypatch.setattr(
        "app.data.ingestion.summary_generator.generate_summary_model",
        fail_generation,
    )

    with pytest.raises(RuntimeError, match="structured generation failed"):
        await dimension_runtime.generate_summary(
            "traffic",
            1,
            "报告正文",
            source_artifact={"report_body": "报告正文", "typed_instruction": {}},
        )


def test_summary_metric_projection_ignores_pydantic_defaults() -> None:
    from app.data.ingestion.summary_generator import (
        _sync_schema_fields_to_metrics,
        derived_summary_schema,
    )

    schema = derived_summary_schema("location")
    summary = schema.model_validate(
        {
            "dimension_key": "location",
            "layer": 1,
            "word_count": 20,
            "province": "四川省",
        }
    )

    _sync_schema_fields_to_metrics(summary)

    assert summary.metrics == {"province": "四川省"}
    assert "road_connections" not in summary.metrics


@pytest.mark.asyncio
async def test_pending_summary_contains_no_semantic_excerpt(monkeypatch) -> None:
    import app.core.settings as settings
    from app.data.ingestion.summary_generator import generate_summary_model

    monkeypatch.setattr(settings, "BACKGROUND_SUMMARY_ENRICHMENT", True)

    async def no_result(*_args, **_kwargs):
        return None

    monkeypatch.setattr(
        "app.data.ingestion.summary_generator._instructor_generate",
        no_result,
    )

    summary = await generate_summary_model(
        "traffic",
        1,
        "报告中有未确认的规划语句",
        source_artifact={
            "report_body": "报告中有未确认的规划语句",
            "typed_instruction": {},
        },
    )

    assert summary.summary_status == "pending"
    assert summary.text_summary == ""
    assert summary.key_points == []
    assert summary.metrics == {}


@pytest.mark.asyncio
async def test_summary_runtime_accepts_the_complete_source_artifact(monkeypatch) -> None:
    from app.infrastructure.llm import dimension_runtime

    calls: list[tuple[str, int, str, object]] = []

    async def generate_summary_model(
        dimension_key: str,
        layer: int,
        content: str,
        *,
        source_artifact=None,
    ):
        calls.append((dimension_key, layer, content, source_artifact))
        from app.data.ingestion.summary_generator import build_derived_summary

        return build_derived_summary(
            dimension_key,
            layer,
            word_count=len(content),
            text_summary="动态摘要",
        )

    monkeypatch.setattr(
        "app.data.ingestion.summary_generator.generate_summary_model",
        generate_summary_model,
    )

    source_artifact = {
        "report_body": "完整正文",
        "typed_instruction": {"observations": [{"statement": "完整事实"}]},
    }
    serialized = await dimension_runtime.generate_summary(
        "traffic",
        1,
        "完整正文",
        source_artifact=source_artifact,
    )

    assert calls == [("traffic", 1, "完整正文", source_artifact)]
    assert json.loads(serialized)["text_summary"] == "动态摘要"


def test_removed_background_summary_entrypoint_is_not_exported() -> None:
    from app.infrastructure.llm import dimension_runtime

    assert not hasattr(dimension_runtime, "enrich_summary_background")
