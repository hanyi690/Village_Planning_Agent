"""Closed-set GROUND/SELECT reasoning tests."""

from __future__ import annotations

import re
from types import SimpleNamespace

import pytest

from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounding_contracts import CandidateSite, GroundingResult
from app.contracts.spatial.spatial_reference_contracts import (
    CandidateSelectionBatchDecision,
    CandidateSelectionBatchProposal,
)
from app.spatial.grounding.call_budget import new_ground_llm_budget


def _candidate(target_id: str, candidate_id: str, score: float) -> CandidateSite:
    geometry = CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="polygon",
        role="parcel_candidate",
        wkt="POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))",
        identity_confidence=0.9,
        geometry_confidence=0.9,
        suitability_score=score,
        component_fact_refs=["fact:l1:1"],
    )
    return CandidateSite(
        site_id=f"site:{candidate_id}",
        candidate_id=candidate_id,
        target_ref=target_id,
        target_kind="site_area",
        expected_output_kind="polygon",
        geometry=geometry,
        component_fact_refs=["fact:l1:1"],
        evidence_refs=["evidence:parcel:1"],
    )


@pytest.mark.asyncio
async def test_ground_reasoning_uses_only_candidate_cards_and_validates_id(monkeypatch):
    from app.domain.ground.llm_reasoning import reason_ground_candidates
    from app.infrastructure.llm.manager import get_llm_manager

    monkeypatch.setenv("GROUND_LLM_ENABLED", "true")
    result = GroundingResult(
        candidates=[
            _candidate("target-1", "candidate-a", 0.8),
            _candidate("target-1", "candidate-b", 0.7),
        ]
    )
    seen: dict[str, object] = {}

    async def fake_run(spec, messages, **kwargs):
        seen["spec"] = spec
        seen["prompt"] = messages[0]["content"]
        prompt = messages[0]["content"]
        digest = re.search(r"input_digest=([0-9a-f]+)", prompt).group(1)
        return CandidateSelectionBatchProposal(
            decisions=[
                CandidateSelectionBatchDecision(
                    decision_id="ground:candidate-set:target-1",
                    status="selected",
                    selected_candidate_id="candidate-a",
                    input_digest=digest,
                )
            ]
        )

    monkeypatch.setattr(get_llm_manager(), "run_structured", fake_run)
    decisions = await reason_ground_candidates(
        result,
        [SimpleNamespace(target_id="target-1", spec_id="spec-1", type="attributive")],
        budget=new_ground_llm_budget(),
        llm=object(),
    )

    assert decisions["target-1"]["selected_candidate_id"] == "candidate-a"
    assert seen["spec"].contract_key == "ground.candidate_selection_batch"
    prompt = str(seen["prompt"])
    assert "candidate-a" in prompt
    assert "POLYGON" not in prompt
    assert "report_body" not in prompt
    assert "fact:l1:1" in prompt


@pytest.mark.asyncio
async def test_select_reasoning_is_advisory_and_uses_scenario_cards(monkeypatch):
    from app.infrastructure.llm.manager import get_llm_manager
    from app.workflow.stages.select import _reason_select_scenario

    monkeypatch.setenv("DISABLE_LLM", "false")
    scenario_set = SimpleNamespace(
        set_id="scenario-set-1",
        problem_fingerprint="problem-1",
        recommendation_policy="lexicographic",
        scenarios=[
            SimpleNamespace(
                scenario_id="scenario-a",
                status="complete",
                target_selections=[
                    SimpleNamespace(
                        target_id="target-1",
                        selection_mode="choose_one",
                        candidate_ids=["candidate-a"],
                    )
                ],
                objective_vector={"coverage": 1.0},
                metrics={"area": 1.0},
                findings=[],
            )
        ],
    )
    seen: dict[str, object] = {}

    async def fake_run(spec, messages, **kwargs):
        seen["spec"] = spec
        seen["prompt"] = messages[0]["content"]
        digest = re.search(r"input_digest=([0-9a-f]+)", messages[0]["content"]).group(1)
        from app.contracts.spatial.spatial_reference_contracts import CandidateSelectionProposal

        return CandidateSelectionProposal(
            status="selected",
            selected_candidate_id="scenario-a",
            input_digest=digest,
        )

    monkeypatch.setattr(get_llm_manager(), "run_structured", fake_run)
    decision = await _reason_select_scenario(scenario_set, llm=object())

    assert decision["selected_candidate_id"] == "scenario-a"
    assert seen["spec"].contract_key == "select.scenario_selection"
    prompt = str(seen["prompt"])
    assert "scenario-a" in prompt
    assert "candidate-a" in prompt
    assert "geometry_wkt" not in prompt
    assert "POLYGON" not in prompt
