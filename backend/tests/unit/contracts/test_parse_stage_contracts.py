from app.modules.schema.contracts.parse_result_contracts import (
    IntentCompilationResult, ProjectRequirement, CompilationError,
    ParseMode, CompilationStatus, PatchOperation, CompilationPatch,
    ParseDiagnostic, ParseTrace, ParseRevisionRequest,
)


def test_parse_mode_enum():
    assert ParseMode.COMPILE.value == "compile"
    assert ParseMode.REPAIR.value == "repair"
    assert ParseMode.REVISE.value == "revise"


def test_compilation_status_enum():
    assert CompilationStatus.NEEDS_REPAIR.value == "needs_repair"
    assert CompilationStatus.COMMITTED.value == "committed"


def test_patch_operation_enum():
    assert PatchOperation.MERGE.value == "merge"


def test_compilation_patch_fields():
    p = CompilationPatch(field_path="project_requirements.0.functions", operation=PatchOperation.ADD,
                         after=["医疗"], actor="user", confidence=1.0, base_revision="r2",
                         source_text_loc="L3.md:42")
    assert p.operation == PatchOperation.ADD
    assert p.actor == "user"
    assert p.base_revision == "r2"


def test_parse_diagnostic():
    d = ParseDiagnostic(severity="error", code="TABLE_CORRUPT", message="表格损坏")
    assert d.severity == "error"
    assert d.field_path == ""


def test_parse_trace():
    t = ParseTrace(mode=ParseMode.COMPILE, steps=[{"node": "extract", "ok": True}])
    assert t.mode == ParseMode.COMPILE
    assert len(t.steps) == 1


def test_parse_revision_request():
    req = ParseRevisionRequest(request_id="pr-1", mode=ParseMode.REPAIR, program_ref="l3-1", base_revision_ref="r1")
    assert req.mode == ParseMode.REPAIR
    assert req.base_revision_ref == "r1"


def test_intent_compilation_result_upgraded():
    icr = IntentCompilationResult(context_version="v1", artifact_id="parse-1",
                                  program_ref="l3-1", base_revision_ref="r1",
                                  project_requirements=[ProjectRequirement(project_ref="iv-1")],
                                  compilation_status=CompilationStatus.DRAFT)
    assert icr.schema_version == "1.0"
    assert icr.program_ref == "l3-1"
    assert icr.compilation_status == CompilationStatus.DRAFT
    assert icr.project_requirements[0].project_ref == "iv-1"
    assert icr.patches == []
    assert icr.spatial_reference_specs == []


def test_patch_does_not_carry_reasoning_trace():
    # per review: 只保存简要判断依据，不保存模型内部推理链
    import pydantic
    p = CompilationPatch(rationale="面积不足")
    assert not hasattr(p, "internal_reasoning") or p.internal_reasoning is None
