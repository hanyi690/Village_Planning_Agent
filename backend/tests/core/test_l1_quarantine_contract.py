import json

from app.data.ingestion.compiler.profiles.l1_observation import compile_l1_observation
from app.domain.assessment.observation_draft import build_l1_observation_output_model


def test_required_fact_type_missing_only_emits_dimension_local_diagnostic() -> None:
    response_model = build_l1_observation_output_model(
        ("scoped_metric", "constraint"),
        required_fact_types=("scoped_metric",),
    )

    output = response_model.model_validate(
        {
            "observations": [
                {
                    "fact_type": "constraint",
                    "constraint_type": "河道缓冲带",
                    "applies_to_scope": "全村",
                }
            ]
        }
    )

    assert len(output.observations) == 1
    assert output.required_fact_types == ("scoped_metric",)
    assert output.provisional_fact_records == []
    assert any(
        item == "l1_required_fact_type_missing:scoped_metric"
        for item in output.diagnostics
    )


def test_provisional_fact_does_not_satisfy_required_fact_coverage_or_authoritative_compile() -> None:
    response_model = build_l1_observation_output_model(
        ("scoped_metric", "constraint"),
        required_fact_types=("scoped_metric",),
    )

    output = response_model.model_validate(
        {
            "observations": [
                {
                    "fact_type": "scoped_metric",
                    "metric": "常住人口",
                    "scope": "全村",
                    "status": "uncertain",
                    "source_quote": "来源未核验",
                }
            ]
        }
    )

    assert len(output.observations) == 1
    assert len(output.provisional_fact_records) == 1
    assert any(
        item == "l1_required_fact_type_missing:scoped_metric"
        for item in output.diagnostics
    )

    snapshot = compile_l1_observation(
        dimension_key="socio_economic",
        content="社会经济现状说明。",
        instruction=output.model_dump_json(),
        report_id="report-provisional",
    )

    assert snapshot.fact_records == []
    assert snapshot.location_facts == []


def test_quarantined_observation_keeps_safe_payload_copy_and_error_path() -> None:
    response_model = build_l1_observation_output_model(("spatial_entity",))

    output = response_model.model_validate(
        {
            "observations": json.dumps(
                [
                    {
                        "fact_type": "spatial_entity",
                        "entity_type": "道路",
                        "name": "村道",
                        "locator": {"place_names": ["金田村"]},
                    },
                    {
                        "fact_type": "spatial_entity",
                        "entity_type": "道路",
                        "locator": {"place_names": ["金田村"]},
                        "source_quote": "现状村道",
                    },
                ],
                ensure_ascii=False,
            )
        }
    )

    assert len(output.observations) == 1
    assert len(output.quarantined_observations) == 1
    quarantined = output.quarantined_observations[0]
    assert quarantined.ordinal == 1
    assert quarantined.payload_digest
    assert quarantined.raw_payload["fact_type"] == "spatial_entity"
    assert "spatial_entity.name" in quarantined.error_paths
    assert "name" in quarantined.error_paths
