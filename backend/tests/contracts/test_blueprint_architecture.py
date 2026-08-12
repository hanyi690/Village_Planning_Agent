"""Aggregate blueprint-convergence architecture guardrails (Phase 9)."""

from __future__ import annotations

import pathlib
import re

APP = pathlib.Path("app")


def _production_files() -> list[pathlib.Path]:
    return [p for p in APP.rglob("*.py") if "tests" not in str(p)]


def _has_text(files: list[pathlib.Path], needles: list[str]) -> list[tuple[str, str]]:
    hits = []
    for p in files:
        text = p.read_text(encoding="utf-8")
        for n in needles:
            if n in text:
                hits.append((str(p), n))
    return hits


def test_no_legacy_god_modules():
    needles = ["app.agent.", "app.modules."]
    assert not _has_text(_production_files(), needles), "legacy god modules still referenced"
    offenders = _has_text(_production_files(), ["app.services"])
    assert not offenders, "app.services reference remains"


def test_no_workflow_progress_or_legacy_gate():
    needles = ["WorkflowProgress", "LEGACY_GATE_STAGES", "l1_gate_decision", "l2_gate_decision", "l3_gate_decision"]
    assert not _has_text(_production_files(), needles), "workflow_progress / legacy gate still present"


def test_no_services_runtime_in_workflow_domain():
    files = [p for p in _production_files() if "/workflow/" in p.as_posix() or "/domain/" in p.as_posix()]
    assert not _has_text(files, ["app.services"]), "workflow/domain must not reference app.services"


def test_root_graph_is_single_artifact_producer():
    src = (APP / "workflow" / "root_graph.py").read_text(encoding="utf-8")
    forbidden = re.compile(r"store_artifact\(\s*state\s*,\s*\"(?:planning_program|deferral_ledger|site_selection|execution_plan|delivery_manifest)\"")
    assert not forbidden.search(src), "root_graph still writes domain artifacts directly"


def test_workflow_state_is_control_only():
    src = (APP / "workflow" / "state.py").read_text(encoding="utf-8")
    assert "Annotated[" in src
    assert "runtime: Annotated" in src
