"""Cross-layer upstream enrichment + gate checks.

Covers ``enrich_program_from_upstream`` (L1/L2 artifact loading into the L3
program), the re-enabled cross-layer gate checks in ``evaluate_l3_gate`` /
``evaluate_l2_gate``, and the post-L3 ``_load_planning_program`` reuse path.
"""
from __future__ import annotations

import pytest

from app.agent.l2_strategize.gate import evaluate_l2_gate
from app.agent.l3_plan.aggregate import enrich_program_from_upstream
from app.agent.l3_plan.gate import evaluate_l3_gate
from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.evidence_contracts import EvidenceSource
from app.modules.schema.contracts.l1_contracts import L1Snapshot
from app.modules.schema.contracts.l2_contracts import L2Strategy
from app.modules.schema.contracts.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
)
from app.services.artifact_store import FilesystemArtifactStore


def _store_snapshot(base_dir, run_id="r1", constraints=None):
    store = FilesystemArtifactStore(base_dir=base_dir)
    snapshot = L1Snapshot(constraints=constraints or [])
    ref = ArtifactRef(
        artifact_id=f"l1-{run_id}-v1",
        module="l1_observe",
        run_id=run_id,
        artifact_type="L1Snapshot",
        revision="v1",
    )
    store.store(ref, snapshot.model_dump(mode="json"))
    return store


def _store_strategy(base_dir, run_id="r1", spatial_structure="村北产业区，村南居住区"):
    store = FilesystemArtifactStore(base_dir=base_dir)
    strategy = L2Strategy(
        spatial_structure=spatial_structure,
        development_goals=["生态宜居"],
        implementation_priorities=["产业优先"],
    )
    ref = ArtifactRef(
        artifact_id=f"l2-{run_id}-v1",
        module="l2_strategize",
        run_id=run_id,
        artifact_type="L2Strategy",
        revision="v1",
    )
    store.store(ref, strategy.model_dump(mode="json"))
    return store


# ── enrich_program_from_upstream ────────────────────────────────────────


def test_enrich_program_from_upstream_sets_refs_and_backfills(tmp_path):
    _store_snapshot(str(tmp_path), constraints=["生态保护红线内禁止开发"])
    _store_strategy(str(tmp_path))

    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="i1",
                name="项目A",
                constraints=["生态保护红线内禁止开发"],
            ),
            PlanningIntervention(intervention_id="i2", name="项目B"),
        ]
    )

    l1_constraints, l2_strategy = enrich_program_from_upstream(
        program, base_dir=str(tmp_path), run_id="r1"
    )

    assert program.l1_snapshot_ref == "l1-r1-v1"
    assert program.l2_strategy_ref == "l2-r1-v1"
    assert l1_constraints == ["生态保护红线内禁止开发"]
    assert l2_strategy is not None
    for intervention in program.interventions:
        assert intervention.derives_from_strategy == "村北产业区，村南居住区"

    codes = [i.code for i in program.program_issues]
    assert "l1_constraint_unaddressed" in codes
    assert "strategy_orphan" not in codes


def test_enrich_program_from_upstream_no_unaddressed_when_covered(tmp_path):
    _store_snapshot(str(tmp_path), constraints=["生态保护红线内禁止开发"])
    _store_strategy(str(tmp_path))

    program = PlanningProgram(
        interventions=[
            PlanningIntervention(
                intervention_id="i1",
                name="项目A",
                constraints=["生态保护红线内禁止开发"],
            ),
            PlanningIntervention(
                intervention_id="i2",
                name="项目B",
                constraints=["生态保护红线内禁止开发"],
            ),
        ]
    )
    enrich_program_from_upstream(program, base_dir=str(tmp_path), run_id="r1")
    assert not any(i.code == "l1_constraint_unaddressed" for i in program.program_issues)


def test_enrich_program_from_upstream_strategy_orphan_when_unmapped(tmp_path):
    _store_strategy(str(tmp_path))
    program = PlanningProgram(interventions=[])
    enrich_program_from_upstream(program, base_dir=str(tmp_path), run_id="r1")
    assert program.l2_strategy_ref == "l2-r1-v1"
    assert any(i.code == "strategy_orphan" for i in program.program_issues)


def test_enrich_program_from_upstream_missing_artifacts_graceful(tmp_path):
    program = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")]
    )
    l1_constraints, l2_strategy = enrich_program_from_upstream(
        program, base_dir=str(tmp_path), run_id="missing"
    )
    assert l1_constraints is None
    assert l2_strategy is None
    assert program.l1_snapshot_ref == ""
    assert program.l2_strategy_ref == ""
    assert program.program_issues == []


# ── evaluate_l3_gate cross-layer checks ─────────────────────────────────


def test_l3_gate_strategy_orphan_routes_l3():
    program = PlanningProgram(
        interventions=[],
        sources=[EvidenceSource(source_type="report", reference="L3:project_bank")],
    )
    strategy = L2Strategy(spatial_structure="村北产业区")
    d = evaluate_l3_gate(program, l2_strategy=strategy)
    assert d.passed is False
    assert d.feedback_route == "L3"
    assert any(r.request_id == "pr-l3-strategy-orphan" for r in d.pending_requests)
    assert any("村北产业区" in r.context.get("detail", "") for r in d.pending_requests)


def test_l3_gate_empty_without_strategy_routes_human():
    program = PlanningProgram(interventions=[])
    d = evaluate_l3_gate(program, l2_strategy=None)
    assert d.passed is False
    assert d.feedback_route == "HUMAN"


def test_l3_gate_pass_with_strategy():
    program = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")],
        sources=[EvidenceSource(source_type="report", reference="L3:project_bank")],
    )
    strategy = L2Strategy(spatial_structure="村北产业区")
    d = evaluate_l3_gate(program, l2_strategy=strategy)
    assert d.passed is True
    assert d.feedback_route is None


def test_l3_gate_human_empty_notes_l1_constraints():
    program = PlanningProgram(interventions=[])
    d = evaluate_l3_gate(program, l1_constraints=["生态保护红线内禁止开发"])
    assert d.feedback_route == "HUMAN"
    assert any(
        r.context.get("l1_constraints_present") == 1 for r in d.pending_requests
    )


# ── evaluate_l2_gate cross-layer checks ─────────────────────────────────


def test_l2_gate_empty_with_l1_constraints_routes_human_with_pending():
    strategy = L2Strategy(development_goals=[], implementation_priorities=[], spatial_structure="")
    d = evaluate_l2_gate(strategy, l1_constraints=["生态保护红线内禁止开发"])
    assert d.passed is False
    assert d.feedback_route == "HUMAN"
    assert any(
        r.context.get("l1_constraints_present") == 1
        and r.request_type == "strategy_rework"
        for r in d.pending_requests
    )


def test_l2_gate_empty_without_l1_constraints_routes_human():
    strategy = L2Strategy(development_goals=[], implementation_priorities=[], spatial_structure="")
    d = evaluate_l2_gate(strategy, l1_constraints=[])
    assert d.passed is False
    assert d.feedback_route == "HUMAN"
    assert d.pending_requests == []


# ── post-L3 _load_planning_program reuse ────────────────────────────────


@pytest.mark.asyncio
async def test_load_planning_program_from_l3_ref(monkeypatch, tmp_path):
    from app.agent.bootstrap.post_l3_main_nodes import _load_planning_program

    store = FilesystemArtifactStore(base_dir=str(tmp_path))
    program = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")]
    )
    program.artifact_id = "l3-s1-v1"
    l3_ref = ArtifactRef(
        artifact_id="l3-s1-v1",
        module="l3_plan",
        run_id="s1",
        artifact_type="PlanningProgram",
        revision="v1",
    )
    store.store(l3_ref, program.model_dump(mode="json"))
    l3_program_ref = {
        "artifact_id": "l3-s1-v1",
        "module": "l3_plan",
        "run_id": "s1",
        "artifact_type": "PlanningProgram",
        "revision": "v1",
        "context_version": "",
    }

    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.FilesystemArtifactStore",
        lambda: FilesystemArtifactStore(base_dir=str(tmp_path)),
    )

    loaded = _load_planning_program(
        {"session_id": "s1", "context_version": "", "l3_program_ref": l3_program_ref}
    )
    assert isinstance(loaded, PlanningProgram)
    assert loaded.artifact_id == "l3-s1-v1"
    assert len(loaded.interventions) == 1


def test_load_planning_program_prefers_state_program(monkeypatch, tmp_path):
    from app.agent.bootstrap.artifact_runtime import store_artifact
    from app.agent.bootstrap.post_l3_main_nodes import _load_planning_program

    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.FilesystemArtifactStore",
        lambda: FilesystemArtifactStore(base_dir=str(tmp_path)),
    )
    program = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")]
    )
    state = {
        "session_id": "s1",
        "run_id": "r1",
        "context_version": "cv",
        "context_fingerprint": "sha256:test",
        "context_ref": {"session_id": "s1", "version": "cv"},
    }
    program_ref = store_artifact(
        state, "planning_program", "l3", "PlanningProgram", program.model_dump(mode="json")
    )
    state["artifact_refs"] = {"planning_program": program_ref}
    loaded = _load_planning_program(state)
    assert isinstance(loaded, PlanningProgram)
    assert len(loaded.interventions) == 1


def test_load_planning_program_from_state_dict(monkeypatch, tmp_path):
    from app.agent.bootstrap.artifact_runtime import store_artifact
    from app.agent.bootstrap.post_l3_main_nodes import _load_planning_program

    monkeypatch.setattr(
        "app.agent.bootstrap.artifact_runtime.FilesystemArtifactStore",
        lambda: FilesystemArtifactStore(base_dir=str(tmp_path)),
    )
    program = PlanningProgram(
        interventions=[PlanningIntervention(intervention_id="i1", name="项目A")]
    )
    state = {
        "session_id": "s1",
        "run_id": "r1",
        "context_version": "cv",
        "context_fingerprint": "sha256:test",
        "context_ref": {"session_id": "s1", "version": "cv"},
    }
    program_ref = store_artifact(
        state, "planning_program", "l3", "PlanningProgram", program.model_dump(mode="json")
    )
    state["artifact_refs"] = {"planning_program": program_ref}
    loaded = _load_planning_program(state)
    assert isinstance(loaded, PlanningProgram)
    assert len(loaded.interventions) == 1


def test_load_planning_program_missing_returns_none():
    from app.agent.bootstrap.post_l3_main_nodes import _load_planning_program

    assert _load_planning_program({"session_id": "s1"}) is None
