"""Offline production-chain regression for simulated L3 structured output."""

from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_simulated_l3_claim_survives_aggregate_cas_and_projection(
    monkeypatch, tmp_path
):
    monkeypatch.setenv("BACKEND_RUN_TMP_DIR", str(tmp_path))
    from app.infrastructure.paths import reset_run_tmp_root_cache

    reset_run_tmp_root_cache()

    from app.contracts.domain.l3_contracts import PlanningProgram
    from app.contracts.domain.planning_semantics import FacilityPlanningParameters
    from app.contracts.program import PlanningClaim, PlanningClaimSet
    from app.domain.program.aggregate import l3_aggregate
    from app.domain.program.semantic_repair import ProgramSemanticRepairResult
    from app.domain.program.target_projection.aggregate import project_program
    from app.infrastructure.artifacts.runtime import load_artifact
    from app.infrastructure.reports.report_store import ReportStore

    claim_set = PlanningClaimSet(
        dimension_key="public_service",
        claims=[
            PlanningClaim(
                claim_id="simulated-facility-1",
                dimension_key="public_service",
                statement="社前村现状祠堂需要保留并作为公共文化设施维护。",
                suggested_category="facility",
                suggested_output_kind="point",
                asset_kind="facility",
                suggested_interventions=["祠堂维护"],
                intervention_action="preserve",
                location_hints=["社前村", "祠堂"],
                evidence_refs=["l1:fact:祠堂:社前村"],
                facility_parameters=FacilityPlanningParameters(
                    facility_type="祠堂",
                    action="preserve",
                ),
            )
        ],
    )

    store = ReportStore.get_instance()

    async def fake_reports(_session_id, *, layer):
        assert layer == 3
        return {
            "public_service": {
                "instruction": claim_set.model_dump_json(),
                "report_id": "report:simulated-l3:public_service",
            }
        }

    async def no_provider_repair(program, **_kwargs):
        return ProgramSemanticRepairResult(program=program, applied=False)

    async def no_step_report(*_args, **_kwargs):
        return None

    monkeypatch.setattr(store, "get_layer_reports_with_sources", fake_reports)
    monkeypatch.setattr(
        "app.domain.program.semantic_repair.repair_planning_program",
        no_provider_repair,
    )
    monkeypatch.setattr(
        "app.infrastructure.reports.step_report.save_step_report",
        no_step_report,
    )

    state = {
        "session_id": "simulated-l3-session",
        "run_id": "simulated-l3-run",
        "branch_id": "main",
        "context_version": "ctx-1",
        "context_ref": {
            "session_id": "simulated-l3-session",
            "version": "ctx-1",
        },
        "artifact_refs": {},
    }
    aggregate_output = await l3_aggregate(state, base_dir=str(tmp_path))
    state["artifact_refs"].update(aggregate_output["artifact_refs"])

    program = load_artifact(state, "planning_program", PlanningProgram)
    result, specs, gate = project_program(
        program,
        run_id="simulated-l3-run",
        context_version="ctx-1",
    )

    assert result.typed_intent is not None
    assert result.typed_intent.facilities[0].location_hint == "社前村、祠堂"
    assert "l1:fact:祠堂:社前村" in program.interventions[0].evidence_refs
    assert specs[0].op == "and"
    assert specs[0].children[0].reference.filter == {"label_contains": "社前村"}
    assert specs[0].children[1].reference.filter == {"label_contains": "祠堂"}
    assert gate.passed
