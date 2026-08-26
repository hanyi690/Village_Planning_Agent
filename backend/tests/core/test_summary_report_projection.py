from types import SimpleNamespace

import pytest
from pydantic import ValidationError


def test_derived_summary_is_typed_closed_and_code_owned() -> None:
    from app.data.ingestion.schemas import BaseDimensionSummary
    from app.data.ingestion.summary_generator import (
        build_derived_summary,
        derived_summary_schema,
    )

    summary = build_derived_summary(
        "traffic",
        1,
        word_count=12,
        metrics={"observation_count": 2},
        evidence_refs=["l1:fact:1"],
    )

    assert isinstance(summary, BaseDimensionSummary)
    assert summary.authority == "derived_summary"
    assert summary.summary_source == "derived_summary"
    assert summary.dimension_key == "traffic"
    assert summary.layer == 1

    with pytest.raises(ValidationError):
        derived_summary_schema("traffic").model_validate(
            {
                "dimension_key": "traffic",
                "layer": 1,
                "word_count": 12,
                "unexpected_semantics": "new project",
            },
            extra="forbid",
        )


def test_deterministic_summary_does_not_extract_semantic_values_with_regex() -> None:
    from app.data.ingestion.summary_generator import deterministic_summary_model

    summary = deterministic_summary_model(
        "land_use_planning",
        3,
        "建设用地 12 公顷，### 新增道路，森林覆盖率 40%",
    )

    assert summary.metrics == {}
    assert summary.key_points == []
    assert summary.summary_status == "deterministic"
    assert summary.authority == "derived_summary"


@pytest.mark.asyncio
async def test_dimension_complete_publishes_typed_projection_without_json_loads(monkeypatch) -> None:
    from app.data.ingestion.summary_generator import build_derived_summary
    from app.infrastructure.llm.dimension_runtime import publish_dimension_complete

    events: list[dict] = []

    async def publish(_session_id, event):
        events.append(event)

    monkeypatch.setattr("app.infrastructure.events.event_hub.publish", publish)
    summary = build_derived_summary("traffic", 1, word_count=5)

    await publish_dimension_complete(
        "session-1",
        "traffic",
        "交通",
        5,
        summary,
        "report-1",
        1,
        1,
        False,
    )

    assert events[0]["structured_summary"]["authority"] == "derived_summary"
    assert events[0]["structured_summary"]["dimension_key"] == "traffic"


def test_report_projection_quarantines_name_type_conflicts(monkeypatch) -> None:
    import app.data.ingestion.tables as tables
    from app.infrastructure.kg.enrichment.report_entity_enrichment import (
        project_report_entities,
    )

    monkeypatch.setattr(
        tables,
        "_extract_zone_tables",
        lambda _content: [SimpleNamespace(land_use="同名对象")],
    )
    monkeypatch.setattr(
        tables,
        "_extract_project_tables",
        lambda _content: [SimpleNamespace(type="同名对象")],
    )

    projection = project_report_entities({"dimension-a": "report"})

    assert projection["authority"] == "derived_projection"
    assert projection["projection_items"] == []
    assert projection["quarantined_projections"] == [
        {
            "code": "report_projection_name_conflict",
            "projection_name": "同名对象",
            "projection_types": ["FunctionalZone", "Project"],
            "source_dimensions": ["dimension-a"],
        }
    ]


@pytest.mark.asyncio
async def test_report_projection_does_not_write_semantic_entities(monkeypatch) -> None:
    import app.data.ingestion.tables as tables
    from app.infrastructure.kg.enrichment import report_entity_enrichment

    monkeypatch.setattr(
        tables,
        "_extract_zone_tables",
        lambda _content: [SimpleNamespace(land_use="生态区")],
    )
    monkeypatch.setattr(tables, "_extract_project_tables", lambda _content: [])

    built = []

    def build_gazetteer(*_args, **_kwargs):
        built.append(True)
        return object()

    monkeypatch.setattr(
        "app.infrastructure.kg.gazetteer.build_gazetteer",
        build_gazetteer,
    )

    result = await report_entity_enrichment.extract_bindings(
        "session-1",
        2,
        {"land_use_planning": "report"},
        kg=object(),
    )

    assert built == [True]
    assert result["semantic_entities"] == 0
    assert result["projection_items"][0]["authority"] == "derived_projection"


def test_unused_confirm_helpers_are_not_exported() -> None:
    import app.infrastructure.kg.enrichment.report_entity_enrichment as enrichment
    import app.infrastructure.kg.gazetteer as gazetteer
    import app.infrastructure.kg.gazetteer.gazetteer as gazetteer_module

    assert not hasattr(enrichment, "confirm_batch_with_llm")
    assert not hasattr(gazetteer_module, "confirm_with_llm")
    assert not hasattr(gazetteer, "confirm_with_llm")
