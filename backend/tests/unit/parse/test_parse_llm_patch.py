"""Tests for the PARSE LLM patch path (P2): llm_patch + compile_program_async."""
from __future__ import annotations

import pytest

from app.agent.parse.aggregate import compile_program_async
from app.agent.parse.llm_patch import CompilationPatchList, generate_llm_patches
from app.modules.schema.contracts.l3_contracts import (
    PlanningIntervention,
    PlanningProgram,
)
from app.modules.schema.contracts.parse_result_contracts import (
    CompilationPatch,
    CompilationStatus,
    IntentCompilationResult,
    ParseDiagnostic,
    PatchOperation,
)


class _FakeCompletions:
    def __init__(self, payload):
        self._payload = payload

    def create(self, **kwargs):
        return self._payload


class _FakeChat:
    def __init__(self, payload):
        self.completions = _FakeCompletions(payload)


class _FakeClient:
    def __init__(self, payload):
        self.chat = _FakeChat(payload)


class _RaisingCompletions:
    def create(self, **kwargs):
        raise RuntimeError("llm unavailable")


class _RaisingClient:
    def __init__(self):
        self.chat = _FakeChat(_RaisingCompletions())


def _ambiguous_program(count: int = 3) -> PlanningProgram:
    return PlanningProgram(
        artifact_id="l3-amb",
        context_version="cv",
        interventions=[
            PlanningIntervention(
                intervention_id=f"iv-{i}",
                name=f"项目{i}",
                category="project",
                spatial_requirements={},
            )
            for i in range(count)
        ],
    )


def _ambiguous_diags(count: int = 3) -> list[ParseDiagnostic]:
    return [
        ParseDiagnostic(
            diagnostic_id=f"d-{i}",
            severity="warning",
            code="AMBIGUOUS_REFERENCE",
            message=f"ambiguous {i}",
        )
        for i in range(count)
    ]


def _patch_payload() -> CompilationPatchList:
    return CompilationPatchList(
        patches=[
            CompilationPatch(
                field_path="spatial_reference_specs",
                operation=PatchOperation.ADD,
                after={
                    "type": "directional",
                    "reference": {"kind": "village"},
                    "direction": "N",
                },
                actor="llm",
                confidence=0.9,
                rationale="补充方位参考",
            )
        ]
    )


def _install_client(monkeypatch, payload=None, raising=False):
    client = _RaisingClient() if raising else _FakeClient(payload)
    monkeypatch.setattr(
        "app.core.instructor_client.get_instructor_client", lambda: client
    )
    monkeypatch.setattr("app.core.instructor_client.get_flash_model", lambda: "flash-test")
    return client


@pytest.mark.asyncio
async def test_generate_llm_patches_returns_stamped_patches(monkeypatch):
    _install_client(monkeypatch, payload=_patch_payload())

    patches = await generate_llm_patches(
        IntentCompilationResult(), _ambiguous_diags(), _ambiguous_program()
    )

    assert len(patches) == 1
    assert patches[0].actor == "llm"
    assert patches[0].patch_id
    assert patches[0].field_path == "spatial_reference_specs"


@pytest.mark.asyncio
async def test_generate_llm_patches_client_unavailable_returns_empty(monkeypatch):
    def boom():
        raise RuntimeError("no api key")

    monkeypatch.setattr("app.core.instructor_client.get_instructor_client", boom)
    monkeypatch.setattr("app.core.instructor_client.get_flash_model", lambda: "flash-test")

    patches = await generate_llm_patches(
        IntentCompilationResult(), _ambiguous_diags(), _ambiguous_program()
    )

    assert patches == []


@pytest.mark.asyncio
async def test_generate_llm_patches_create_raises_returns_empty(monkeypatch):
    _install_client(monkeypatch, raising=True)

    patches = await generate_llm_patches(
        IntentCompilationResult(), _ambiguous_diags(), _ambiguous_program()
    )

    assert patches == []


@pytest.mark.asyncio
async def test_generate_llm_patches_empty_payload_returns_empty(monkeypatch):
    _install_client(monkeypatch, payload=CompilationPatchList(patches=[]))

    patches = await generate_llm_patches(
        IntentCompilationResult(), _ambiguous_diags(), _ambiguous_program()
    )

    assert patches == []


@pytest.mark.asyncio
async def test_generate_llm_patches_drops_unsupported_path(monkeypatch):
    payload = CompilationPatchList(
        patches=[
            CompilationPatch(
                field_path="not.a.real.path",
                operation=PatchOperation.UPDATE,
                after="x",
            )
        ]
    )
    _install_client(monkeypatch, payload=payload)

    patches = await generate_llm_patches(
        IntentCompilationResult(), _ambiguous_diags(), _ambiguous_program()
    )

    assert patches == []


@pytest.mark.asyncio
async def test_compile_program_async_applies_llm_patches(monkeypatch):
    _install_client(monkeypatch, payload=_patch_payload())
    program = _ambiguous_program(3)

    result, specs, gate = await compile_program_async(
        program, run_id="r", context_version="cv"
    )

    assert len(result.patches) >= 1
    assert result.patches[0].actor == "llm"
    assert len(specs) >= 1
    assert result.compilation_status != CompilationStatus.NEEDS_REVIEW
    assert gate.passed is True


@pytest.mark.asyncio
async def test_compile_program_async_llm_failure_falls_back_needs_review(monkeypatch):
    _install_client(monkeypatch, raising=True)
    program = _ambiguous_program(3)

    result, _, gate = await compile_program_async(
        program, run_id="r", context_version="cv"
    )

    assert result.compilation_status == CompilationStatus.NEEDS_REVIEW
    assert gate.passed is False
    assert gate.feedback_route == "HUMAN"


@pytest.mark.asyncio
async def test_compile_program_async_clean_compile_no_llm(monkeypatch):
    calls = []

    class _RecordingCompletions:
        def create(self, **kwargs):
            calls.append(kwargs)
            return _patch_payload()

    class _RecordingClient:
        def __init__(self):
            self.chat = _FakeChat(_RecordingCompletions())

    client = _RecordingClient()
    monkeypatch.setattr(
        "app.core.instructor_client.get_instructor_client", lambda: client
    )
    monkeypatch.setattr("app.core.instructor_client.get_flash_model", lambda: "flash-test")

    program = PlanningProgram(
        artifact_id="l3-ok",
        context_version="cv",
        interventions=[
            PlanningIntervention(
                intervention_id="iv-1",
                name="供水设施",
                category="project",
                spatial_requirements={"location": "村北"},
            )
        ],
    )
    result, specs, gate = await compile_program_async(
        program, run_id="r", context_version="cv"
    )

    assert calls == []
    assert gate.passed is True
    assert len(specs) >= 1


@pytest.mark.asyncio
async def test_parse_node_uses_async_entry(monkeypatch):
    from app.agent.bootstrap.post_l3_main_nodes import parse_node

    captured = {}

    async def fake_async_compile(program, run_id="", context_version=""):
        captured["run_id"] = run_id
        captured["program"] = program
        return object(), [object()], object()

    monkeypatch.setattr(
        "app.agent.parse.aggregate.compile_program_async", fake_async_compile
    )
    state = {
        "session_id": "s1",
        "run_id": "r1",
        "context_version": "cv",
        "planning_program": _ambiguous_program(),
    }
    out = await parse_node(state)

    assert captured["run_id"] == "r1"
    assert captured["program"] is state["planning_program"]
    assert "intent" in out
    assert "specs" in out
    assert "parse_gate" in out
    assert len(out["upstream_gates"]) == 1
