from __future__ import annotations

from pathlib import Path

import pytest

from app.contracts.domain.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
    RoadPlanningParameters,
)
from app.domain.program.gate import evaluate_l3_gate
from app.domain.program.semantic_repair import (
    DuplicateMerge,
    InterventionSemanticPatch,
    ProgramSemanticRepairCandidate,
    apply_semantic_repair_candidate,
    repair_planning_program,
    validate_semantic_repair_candidate,
)


def _road(target_id: str, name: str = "道路提升") -> PlanningIntervention:
    return PlanningIntervention(
        intervention_id=target_id,
        target_id=target_id,
        name=name,
        category="road",
        execution_mode="spatial",
        expected_output_kind="line",
        road_parameters=RoadPlanningParameters(
            action="upgrade",
            length_m=8000,
            roadbed_width_m=7.5,
            pavement_width_m=6,
            alignment_refs=["Y122乡道"],
        ),
    )


class _FakeStructuredLLM:
    def __init__(self, responses: list[ProgramSemanticRepairCandidate]) -> None:
        self.responses = list(responses)
        self.calls: list[object] = []

    def with_structured_output(self, *args, **kwargs):
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        return self.responses.pop(0)


class _QuotaExhausted(Exception):
    status_code = 429


@pytest.mark.asyncio
async def test_program_critic_rejects_object_field_patches_and_retries_with_feedback(
    tmp_path: Path,
) -> None:
    program = PlanningProgram(interventions=[_road("road-1")])
    invalid = ProgramSemanticRepairCandidate(
        patches=[
            InterventionSemanticPatch(
                target_id="road-1",
                road_parameters=RoadPlanningParameters(
                    action="upgrade",
                    length_m=5000,
                    pavement_width_m=5,
                ),
            )
        ]
    )
    valid = ProgramSemanticRepairCandidate()
    llm = _FakeStructuredLLM([invalid, valid])

    result = await repair_planning_program(
        program,
        llm=llm,
        cache_path=tmp_path / "critic-cache.json",
    )

    assert result.applied is True
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert "cannot patch object semantics" in llm.calls[1][1]["content"]
    assert result.program.interventions[0].road_parameters.length_m == 8000


@pytest.mark.asyncio
async def test_program_critic_cache_avoids_repeat_llm_calls(tmp_path: Path) -> None:
    program = PlanningProgram(interventions=[_road("road-1")])
    cache_path = tmp_path / "critic-cache.json"
    first_llm = _FakeStructuredLLM([ProgramSemanticRepairCandidate()])
    first = await repair_planning_program(program, llm=first_llm, cache_path=cache_path)
    second_llm = _FakeStructuredLLM([])
    second = await repair_planning_program(program, llm=second_llm, cache_path=cache_path)

    assert first.applied and second.applied
    assert len(second_llm.calls) == 0
    assert second.cache_hits == 1


def test_duplicate_merge_preserves_source_typed_semantics_and_evidence() -> None:
    first = _road("road-a", "道路硬化升级")
    first.claim_refs = ["A"]
    second = _road("road-b", "道路硬化提升")
    second.claim_refs = ["B"]
    program = PlanningProgram(interventions=[first, second])
    candidate = ProgramSemanticRepairCandidate(
        duplicate_merges=[
            DuplicateMerge(
                canonical_target_id="road-a",
                duplicate_target_ids=["road-b"],
            )
        ]
    )

    assert validate_semantic_repair_candidate(program, candidate) == []
    repaired = apply_semantic_repair_candidate(program, candidate)

    assert [item.target_id for item in repaired.interventions] == ["road-a"]
    assert repaired.interventions[0].claim_refs == ["A", "B"]
    assert repaired.interventions[0].road_parameters.length_m == 8000


@pytest.mark.asyncio
async def test_program_critic_skips_llm_when_source_dimension_has_an_error() -> None:
    program = PlanningProgram(
        interventions=[_road("road-1")],
        program_issues=[
            ProgramIssue(
                dimension_key="traffic_planning",
                severity="error",
                code="semantic_compile_exhausted",
                message="road dimensions unresolved",
            )
        ],
    )
    llm = _FakeStructuredLLM([])

    result = await repair_planning_program(program, llm=llm)

    assert result.applied is False
    assert result.attempts == 0
    assert len(llm.calls) == 0
    assert "traffic_planning:semantic_compile_exhausted" in result.validation_errors[0]


@pytest.mark.asyncio
async def test_program_critic_runs_for_classification_only_and_preserves_diagnostics(
    tmp_path: Path,
) -> None:
    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="zone-1",
                target_id="zone-1",
                name="公共服务设施用地",
                category="zone",
                execution_mode="spatial",
                expected_output_kind="polygon",
            )
        ],
        program_issues=[
            ProgramIssue(
                severity="error",
                code="classification_decision_required",
                message="classification decision is pending",
            ),
            ProgramIssue(
                severity="warning",
                code="source_warning",
                message="source warning",
            ),
            ProgramIssue(
                severity="info",
                code="source_note",
                message="source note",
            ),
        ],
    )
    llm = _FakeStructuredLLM([ProgramSemanticRepairCandidate()])

    result = await repair_planning_program(
        program,
        llm=llm,
        cache_path=tmp_path / "critic-cache.json",
    )

    assert result.applied is True
    assert len(llm.calls) == 1
    issues = {
        issue.code: issue
        for issue in result.program.program_issues
        if issue.code != "semantic_repair_applied"
    }
    assert issues["classification_decision_required"].severity == "error"
    assert issues["source_warning"].severity == "warning"
    assert issues["source_note"].severity == "info"


@pytest.mark.asyncio
async def test_program_critic_partitions_mixed_classification_and_source_errors() -> None:
    program = PlanningProgram(
        interventions=[_road("road-1")],
        program_issues=[
            ProgramIssue(
                severity="error",
                code="classification_decision_required",
                message="classification decision is pending",
            ),
            ProgramIssue(
                dimension_key="traffic_planning",
                severity="error",
                code="semantic_compile_exhausted",
                message="road dimensions unresolved",
            ),
            ProgramIssue(
                severity="warning",
                code="source_warning",
                message="source warning",
            ),
        ],
    )
    llm = _FakeStructuredLLM([])

    result = await repair_planning_program(program, llm=llm)

    assert result.applied is False
    assert result.attempts == 0
    assert len(llm.calls) == 0
    assert result.validation_errors == [
        "traffic_planning:semantic_compile_exhausted:road dimensions unresolved"
    ]
    assert [issue.code for issue in result.program.program_issues] == [
        "classification_decision_required",
        "semantic_compile_exhausted",
        "source_warning",
    ]


@pytest.mark.asyncio
async def test_program_critic_provider_is_disabled_without_explicit_enablement(
    monkeypatch,
) -> None:
    monkeypatch.delenv("L3_SEMANTIC_REPAIR_LLM_ENABLED", raising=False)

    result = await repair_planning_program(
        PlanningProgram(interventions=[_road("road-disabled")]),
    )

    assert result.applied is False
    assert result.attempts == 0
    assert [issue.code for issue in result.program.program_issues] == [
        "llm_semantic_repair_disabled"
    ]
    assert result.validation_errors


@pytest.mark.asyncio
async def test_program_critic_stops_immediately_on_provider_quota_exhaustion() -> None:
    class _QuotaLLM:
        def __init__(self) -> None:
            self.calls = 0

        def with_structured_output(self, *args, **kwargs):
            return self

        async def ainvoke(self, _messages):
            self.calls += 1
            raise _QuotaExhausted(
                "GoUsageLimitError: weekly usage limit reached"
            )

    llm = _QuotaLLM()
    result = await repair_planning_program(
        PlanningProgram(interventions=[_road("road-1")]),
        llm=llm,
        max_rounds=3,
    )

    assert llm.calls == 1
    assert result.attempts == 1
    assert result.program.program_issues[-1].code == "llm_provider_quota_exhausted"


def test_program_critic_cannot_downgrade_source_diagnostics() -> None:
    program = PlanningProgram(interventions=[_road("road-1")])
    candidate = ProgramSemanticRepairCandidate(
        diagnostic_dispositions=[
            {"issue_index": 0, "resolution": "audit_only"}
        ]
    )

    errors = validate_semantic_repair_candidate(program, candidate)

    assert any("cannot hide or downgrade" in error for error in errors)


def test_l3_gate_routes_every_unresolved_error_back_to_l3() -> None:
    program = PlanningProgram(
        interventions=[_road("road-1")],
        program_issues=[
            ProgramIssue(
                severity="error",
                code="semantic_compile_exhausted",
                message="source object semantics unresolved",
            )
        ],
    )

    gate = evaluate_l3_gate(program)

    assert gate.passed is False
    assert gate.feedback_route == "L3"


def test_functional_overlay_does_not_request_land_use_classification() -> None:
    from app.contracts.domain.planning_semantics import PolygonPlanningParameters
    from app.domain.program.classification import classification_review_targets

    overlay = PlanningIntervention(
        intervention_id="functional-1",
        target_id="functional-1",
        name="一心一带三区",
        category="zone",
        execution_mode="spatial",
        expected_output_kind="polygon",
        materialization_role="functional_overlay",
        polygon_parameters=PolygonPlanningParameters(
            materialization_role="functional_overlay",
            planning_zone="产业空间结构",
        ),
    )

    assert classification_review_targets(
        PlanningProgram(interventions=[overlay])
    ) == []
