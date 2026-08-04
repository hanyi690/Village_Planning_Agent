"""Tests for the PARSE review package builder."""
from __future__ import annotations

from app.agent.parse.compile_node import compile_program_deterministic
from app.agent.parse.gate_node import evaluate_parse_gate
from app.agent.parse.review import build_parse_review_package
from app.modules.ports.artifact_store import ArtifactRef
from app.modules.schema.contracts.parse_result_contracts import CompilationStatus


def test_build_parse_review_package_full_program(planning_program):
    result, specs, _ = compile_program_deterministic(
        planning_program, run_id="r", context_version="cv"
    )
    result.compilation_status = CompilationStatus.VALIDATED
    gate_decision = evaluate_parse_gate(result, run_id="r", context_version="cv")
    artifact_ref = ArtifactRef(
        context_version="cv",
        artifact_id="parse-r-v1",
        module="parse",
        run_id="r",
        artifact_type="IntentCompilationResult",
        revision="v1",
    )
    pkg = build_parse_review_package(
        result=result,
        specs=specs,
        gate_decision=gate_decision,
        artifact_ref=artifact_ref,
        run_id="r",
    )

    assert set(pkg) == {
        "metadata",
        "编译摘要",
        "源字段->结构化字段映射",
        "编译诊断",
        "补丁清单",
        "SpatialReferenceSpec 清单",
        "Gate 决定",
        "profile trace",
    }
    assert pkg["metadata"]["artifact_type"] == "IntentCompilationResult"
    assert isinstance(pkg["编译诊断"], list)
    assert isinstance(pkg["补丁清单"], list)
    assert len(pkg["SpatialReferenceSpec 清单"]) >= 1
    assert isinstance(pkg["Gate 决定"]["passed"], bool)
    assert pkg["profile trace"]["mode"] == "compile"


def test_build_parse_review_package_empty_program(empty_program):
    result, specs, _ = compile_program_deterministic(
        empty_program, run_id="r", context_version="cv"
    )
    gate_decision = evaluate_parse_gate(result, run_id="r", context_version="cv")
    artifact_ref = ArtifactRef(
        context_version="cv",
        artifact_id="parse-empty-v1",
        module="parse",
        run_id="r",
        artifact_type="IntentCompilationResult",
        revision="v1",
    )
    pkg = build_parse_review_package(
        result=result,
        specs=specs,
        gate_decision=gate_decision,
        artifact_ref=artifact_ref,
        run_id="r",
    )

    assert pkg["SpatialReferenceSpec 清单"] == []
    assert pkg["编译摘要"]["intervention_count"] == 0
