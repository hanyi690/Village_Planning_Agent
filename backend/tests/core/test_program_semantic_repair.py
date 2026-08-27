from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from app.contracts.domain.l3_contracts import (
    InterventionDependency,
    PlanningIntervention,
    PlanningProgram,
    ProgramIssue,
    RoadPlanningParameters,
)
from app.contracts.llm.decision_contracts import ClosedSetRef
from app.domain.program.semantic_repair import (
    Abstain,
    DependencyEdge,
    DuplicateMerge,
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
        asset_kind="road",
        execution_mode="spatial",
        expected_output_kind="line",
        claim_refs=[f"claim:{target_id}"],
        road_parameters=RoadPlanningParameters(
            action="upgrade",
            length_m=8000,
            roadbed_width_m=7.5,
            pavement_width_m=6,
            alignment_refs=["Y122乡道"],
        ),
    )


def _evidence(target_id: str) -> ClosedSetRef:
    return ClosedSetRef(namespace="claim", ref_id=target_id)


def _merge(canonical: str, duplicate: str) -> DuplicateMerge:
    return DuplicateMerge(
        canonical_target_id=canonical,
        duplicate_target_ids=[duplicate],
        evidence_refs=[_evidence(canonical)],
    )


def _edge(source: str, target: str) -> DependencyEdge:
    return DependencyEdge(
        from_intervention_id=source,
        to_intervention_id=target,
        dependency_type="semantic_dependency",
        evidence_refs=[_evidence(source)],
    )


class _FakeStructuredLLM:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[object] = []

    def with_structured_output(self, *_args, **_kwargs):
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        return response.model_dump(mode="json") if isinstance(response, BaseModel) else response


def test_repair_schema_exposes_only_typed_operations() -> None:
    schema = ProgramSemanticRepairCandidate.model_json_schema()

    assert list(schema["properties"]) == ["operations"]
    assert "patches" not in str(schema)
    assert "diagnostic_dispositions" not in str(schema)
    assert "duplicate_merge" in str(schema)
    assert "dependency_edge" in str(schema)
    assert "abstain" in str(schema)


def test_repair_provider_schema_does_not_embed_runtime_program_ids() -> None:
    from app.domain.program import semantic_repair

    program = PlanningProgram(interventions=[_road("road-1"), _road("road-2")])
    model = semantic_repair._dynamic_repair_model(program)
    schema_text = str(model.model_json_schema())

    assert model is ProgramSemanticRepairCandidate
    assert "road-1" not in schema_text
    assert "road-2" not in schema_text


def test_legacy_patch_and_diagnostic_fields_are_not_accepted() -> None:
    with pytest.raises(ValidationError):
        ProgramSemanticRepairCandidate.model_validate(
            {"patches": [], "diagnostic_dispositions": []}
        )


def test_semantic_operations_require_typed_evidence() -> None:
    with pytest.raises(ValidationError):
        DuplicateMerge(
            canonical_target_id="road-1",
            duplicate_target_ids=["road-2"],
            evidence_refs=[],
        )

    program = PlanningProgram(interventions=[_road("road-1"), _road("road-2", "道路硬化提升")])
    candidate = ProgramSemanticRepairCandidate(
        operations=[
            DuplicateMerge(
                canonical_target_id="road-1",
                duplicate_target_ids=["road-2"],
                evidence_refs=[ClosedSetRef(namespace="claim", ref_id="unknown")],
            )
        ]
    )

    assert any("unknown evidence" in error for error in validate_semantic_repair_candidate(program, candidate))


def test_duplicate_merge_preserves_source_typed_semantics_and_evidence() -> None:
    first = _road("road-a", "道路硬化升级")
    first.claim_refs = ["claim:A"]
    second = _road("road-b", "道路硬化提升")
    second.claim_refs = ["claim:B"]
    program = PlanningProgram(interventions=[first, second])
    candidate = ProgramSemanticRepairCandidate(
        operations=[
            DuplicateMerge(
                canonical_target_id="road-a",
                duplicate_target_ids=["road-b"],
                evidence_refs=[_evidence("A")],
            )
        ]
    )

    assert validate_semantic_repair_candidate(program, candidate) == []
    repaired = apply_semantic_repair_candidate(program, candidate)

    assert [item.target_id for item in repaired.interventions] == ["road-a"]
    assert repaired.interventions[0].claim_refs == ["claim:A", "claim:B"]
    assert repaired.interventions[0].road_parameters.length_m == 8000
    assert repaired.program_issues[-1].code == "semantic_repair_applied"


def test_dependency_edge_is_closed_and_cycles_are_rejected() -> None:
    program = PlanningProgram(
        interventions=[_road("road-1"), _road("road-2")],
        dependencies=[
            InterventionDependency(
                from_intervention_id="road-1",
                to_intervention_id="road-2",
                dependency_type="semantic_dependency",
            )
        ],
    )
    candidate = ProgramSemanticRepairCandidate(operations=[_edge("road-2", "road-1")])

    errors = validate_semantic_repair_candidate(program, candidate)

    assert any("cycle" in error for error in errors)
    with pytest.raises(ValueError, match="cycle"):
        apply_semantic_repair_candidate(program, candidate)


@pytest.mark.asyncio
async def test_invalid_operation_retries_then_applies_verified_operation() -> None:
    program = PlanningProgram(interventions=[_road("road-1"), _road("road-2")])
    invalid = ProgramSemanticRepairCandidate(
        operations=[
            DependencyEdge(
                from_intervention_id="road-1",
                to_intervention_id="road-1",
                dependency_type="semantic_dependency",
                evidence_refs=[_evidence("road-1")],
            )
        ]
    )
    valid = ProgramSemanticRepairCandidate(operations=[_edge("road-1", "road-2")])
    llm = _FakeStructuredLLM([invalid, valid])

    result = await repair_planning_program(program, llm=llm, max_rounds=3)

    assert result.applied is True
    assert result.attempts == 2
    assert len(llm.calls) == 2
    assert len(result.program.dependencies) == 1
    assert "patches" not in llm.calls[0][1]["content"]


@pytest.mark.asyncio
async def test_abstain_is_pending_and_does_not_mutate_program() -> None:
    program = PlanningProgram(interventions=[_road("road-1")])
    llm = _FakeStructuredLLM(
        [
            ProgramSemanticRepairCandidate(
                operations=[
                    Abstain(
                        decision_ref="road-1",
                        reason_code="duplicate_evidence_is_ambiguous",
                    )
                ]
            )
        ]
    )

    result = await repair_planning_program(program, llm=llm)

    assert result.applied is False
    assert result.attempts == 1
    assert result.pending[0].reason_code == "duplicate_evidence_is_ambiguous"
    assert result.program == program


@pytest.mark.asyncio
async def test_cache_key_includes_dynamic_candidate_set(tmp_path: Path) -> None:
    program = PlanningProgram(interventions=[_road("road-1"), _road("road-2")])
    cache_path = tmp_path / "critic-cache.json"
    first_llm = _FakeStructuredLLM(
        [ProgramSemanticRepairCandidate(operations=[_edge("road-1", "road-2")])]
    )
    first = await repair_planning_program(program, llm=first_llm, cache_path=cache_path)
    second_llm = _FakeStructuredLLM([])
    second = await repair_planning_program(program, llm=second_llm, cache_path=cache_path)

    assert first.applied and second.applied
    assert second.cache_hits == 1
    assert len(second_llm.calls) == 0
    assert first.candidate_set_digest == second.candidate_set_digest


@pytest.mark.asyncio
async def test_raw_json_string_is_rejected_without_semantic_regex_fallback() -> None:
    program = PlanningProgram(interventions=[_road("road-1")])
    llm = _FakeStructuredLLM(['{"operations": [{"operation": "abstain"}]}'])

    result = await repair_planning_program(program, llm=llm)

    assert result.applied is False
    assert result.attempts == 1
    assert result.program.program_issues[-1].code == "llm_semantic_repair_failed"
    assert len(llm.calls) == 1


@pytest.mark.asyncio
async def test_source_error_is_returned_to_l3_without_provider_call() -> None:
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
async def test_classification_only_diagnostic_is_not_a_source_repair_error() -> None:
    program = PlanningProgram(
        interventions=[_road("road-1")],
        program_issues=[
            ProgramIssue(
                severity="error",
                code="classification_decision_required",
                message="classification decision is pending",
            ),
            ProgramIssue(severity="warning", code="source_warning", message="source warning"),
        ],
    )
    llm = _FakeStructuredLLM(
        [
            ProgramSemanticRepairCandidate(
                operations=[Abstain(decision_ref="program", reason_code="classification_pending")]
            )
        ]
    )

    result = await repair_planning_program(program, llm=llm)

    assert result.applied is False
    assert len(llm.calls) == 1
    assert [issue.code for issue in result.program.program_issues] == [
        "classification_decision_required",
        "source_warning",
    ]


def test_repair_does_not_fill_missing_materialization_role() -> None:
    protection = PlanningIntervention(
        intervention_id="protection-1",
        target_id="protection-1",
        name="生态保护",
        category="protection",
        execution_mode="spatial",
        expected_output_kind="polygon",
        claim_refs=["claim:protection-1"],
    )
    program = PlanningProgram(interventions=[protection])
    repaired = apply_semantic_repair_candidate(
        program,
        ProgramSemanticRepairCandidate(
            operations=[Abstain(decision_ref="protection-1", reason_code="no_evidence")]
        ),
    )

    assert repaired.interventions[0].materialization_role is None
