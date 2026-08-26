# L3 Claim Compiler Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 L3 从“LLM 一次性生成扁平 PlanningClaimDraft”收敛为组件 schema、候选引用/关系、局部失败隔离和依赖闭包 gate，并同步缩短重复的 L3 prompt。

**Architecture:** Provider-facing `L3ClaimOutput` 使用带 `component_kind` discriminator 的互斥组件 union；保留 `PlanningClaimDraft` 作为兼容适配层，把组件转换成现有严格 claim normalizer。关系 catalog、typed reference registry 和 failure-scope/no-progress 模块提供确定性候选与诊断；TARGET_PROJECTION 只接收 admitted dependency closure，非法 claim 继续 quarantine。Prompt 只描述语义任务、证据来源、组件拆分和候选选择，不复制 schema/catalog 的硬约束。

**Tech Stack:** Python 3.12, Pydantic V2 discriminated unions, pytest, existing L3 claim normalizer, relation catalog, LangChain/instructor structured output.

## Global Constraints

- 现有未提交改动按候选补丁审查；对新 compiler 已覆盖的 claim 局部修复、draft 层关系诊断和 prompt 硬规则必须删除，不能并行保留两套逻辑。
- 不使用 `git reset --hard` 或 `git checkout --`；删除冗余逻辑使用精确补丁并逐项验证。
- Provider 输出仍不得包含 BSM、坐标、WKT、GeoJSON、候选几何或可执行 solver target。
- `PlanningClaim`/`PlanningIntervention` 的严格 contract 和 fail-closed solver admission 不放宽；只缩小失败影响范围。
- accepted claim 的 `claim_id` 和完整对象在局部修复、跨轮重试和缓存恢复中保持不变。
- `semantic_compile_exhausted` 只能作为 warning/telemetry，不能制造新的 blocking issue 或触发整维度重生成。
- 前端 prompt 使用单引号、LF、2 空格；Python 使用 4 空格；编辑采用短锚点和 `apply_patch`。

---

### Task 1: 建立互斥 Claim Component provider schema

**Files:**
- Modify: `backend/app/domain/program/claim_draft.py` near provider draft models and `L3ClaimOutput`
- Modify: `backend/app/domain/program/worker.py` in `_cached_claim_only_generation()` and `_normalize_with_structural_repair()`
- Test: `backend/tests/core/test_l3_claim_component_schema.py`
- Update: `backend/tests/core/test_l3_structural_repair.py` only where legacy input compatibility is asserted

**Interfaces:**
- `ClaimComponentDraft = Annotated[FacilityComponentDraft | RoadComponentDraft | LinearComponentDraft | AxisComponentDraft | RestorationOverlayComponentDraft | ProtectionOverlayComponentDraft | ZoneComponentDraft | SiteAreaComponentDraft | NonSpatialActionComponentDraft, Field(discriminator="component_kind")]`
- `component_to_planning_claim_draft(component: ClaimComponentDraft, *, dimension_key: str = "") -> PlanningClaimDraft`
- `coerce_claim_component(value: Any) -> dict[str, Any]`
- `L3ClaimOutput.claims: list[ClaimComponentDraft]`

- [ ] **Step 1: Write failing schema tests**

```python
def test_l3_schema_has_discriminator_and_one_of() -> None:
    from app.domain.program.claim_draft import L3ClaimOutput

    schema = L3ClaimOutput.model_json_schema()
    claims = schema["properties"]["claims"]["items"]
    assert claims["discriminator"]["propertyName"] == "component_kind"
    assert len(claims["oneOf"]) >= 8


def test_facility_component_cannot_expose_linear_block() -> None:
    from pydantic import ValidationError
    from app.domain.program.claim_draft import L3ClaimOutput

    with pytest.raises(ValidationError):
        L3ClaimOutput.model_validate({"claims": [{
            "component_kind": "facility",
            "claim_id": "facility-1",
            "statement": "建设服务设施",
            "facility_parameters": {"facility_type": "clinic"},
            "linear_parameters": {"material": "pipe"},
        }]})


def test_legacy_flat_provider_payload_is_only_compatibility_input() -> None:
    from app.domain.program.claim_draft import L3ClaimOutput, component_to_planning_claim_draft

    output = L3ClaimOutput.model_validate({"claims": [{
        "claim_id": "facility-1",
        "statement": "建设服务设施",
        "suggested_category": "facility",
        "suggested_output_kind": "point",
        "facility_parameters": {"facility_type": "clinic"},
    }]})
    draft = component_to_planning_claim_draft(output.claims[0])
    assert draft.suggested_category == "facility"
    assert draft.facility_parameters is not None
```

- [ ] **Step 2: Run the focused tests and verify they fail against the flat schema**

Run: `python -m pytest -q -o addopts='' backend/tests/core/test_l3_claim_component_schema.py`

Expected: FAIL because `L3ClaimOutput` has no discriminator and `component_kind`.

- [ ] **Step 3: Add component models and the legacy adapter**

Use common evidence/identity fields on a private base model, put only the matching parameter block on each component, and fix category/output/asset values with `Literal`. In the `L3ClaimOutput` `claims` validator, infer `component_kind` only when a legacy fixture/provider object omits it; the generated JSON schema must contain only the discriminated union. Keep `PlanningClaimDraft` unchanged as the local normalization input so existing recorded runs remain readable.

- [ ] **Step 4: Convert components at the worker boundary**

Replace `PlanningClaimDraftSet(claims=list(output.claims))` with:

```python
draft_set = PlanningClaimDraftSet(
    dimension_key=dimension_key,
    claims=[
        component_to_planning_claim_draft(item, dimension_key=dimension_key)
        for item in current_output.claims
    ],
)
```

Apply the same conversion in local repair responses; accepted drafts remain in the existing `merge_repaired_claim_drafts()` map keyed by their original `claim_id`.

- [ ] **Step 5: Remove superseded draft-level repair logic**

删除现有 `repair_claim_draft_set_contracts()` 及其 worker 调用；组件 discriminator 负责形状互斥，candidate selector 负责局部候选，最终 relation validator 负责关系闭合。保留空值 action 的 wire compatibility 仅当 provider fixture 仍需要，并为它单独写 adapter 测试，不把它扩展为新的语义修复路径。

- [ ] **Step 6: Run the focused schema, provider, and structural repair tests**

Run: `python -m pytest -q -o addopts='' backend/tests/core/test_l3_claim_component_schema.py backend/tests/core/test_planning_claim_provider_adapter.py backend/tests/core/test_l3_structural_repair.py`

Expected: all pass, including old recorded/simulated flat fixtures through the compatibility adapter.

---

### Task 2: Add typed reference registry, relation candidates, and component decomposition

**Files:**
- Create: `backend/app/domain/program/claim_compiler.py`
- Modify: `backend/app/domain/program/target_projection/relation_catalog.py`
- Modify: `backend/app/domain/program/worker.py` in prompt evidence and spatial reference validation
- Test: `backend/tests/core/test_l3_claim_compiler_candidates.py`

**Interfaces:**
- `TypedRef(ref_id: str, kind: str, label: str = "", source: str = "")`
- `ClaimRegistry.from_claims(claims: Iterable[PlanningClaim]) -> ClaimRegistry`
- `source_fact_options(dimension_key: str, claim_semantics: str, facts: Iterable[Any]) -> list[TypedRef]`
- `relation_options(subject_kind: str) -> tuple[RelationCandidate, ...]`
- `compatible_objects(relation_template: str, registry: ClaimRegistry) -> list[TypedRef]`
- `create_grounding_request(*, claim_id: str, slot_path: str, expected_kind: str, query_text: str, source_span: str = "") -> TypedGroundingRequest`
- `decompose_project_intent(skeleton: ProjectIntentSkeleton) -> ProjectComponentPlan`

- [ ] **Step 1: Write candidate and decomposition tests**

```python
def test_relation_options_never_offer_connect_network_for_axis() -> None:
    from app.domain.program.claim_compiler import relation_options

    assert "connect_network" not in {item.template for item in relation_options("axis")}
    assert "follow_alignment" in {item.template for item in relation_options("axis")}


def test_compatible_objects_filters_registry_by_catalog_kind() -> None:
    from app.domain.program.claim_compiler import ClaimRegistry, compatible_objects

    registry = ClaimRegistry.from_claims([facility_claim, zone_claim, road_claim])
    assert [item.ref_id for item in compatible_objects("serve", registry)] == ["facility-1"]


def test_missing_endpoint_creates_typed_grounding_request() -> None:
    from app.domain.program.claim_compiler import create_grounding_request

    request = create_grounding_request(
        claim_id="road-1",
        slot_path="spatial_requirements.relations[0].object_ref",
        expected_kind="network",
        query_text="沿金田河既有排水通道",
    )
    assert request.expected_kind == "network"
    assert request.slot_path.endswith("object_ref")
```

- [ ] **Step 2: Implement candidate functions as catalog-derived data**

`relation_options()` must read `RELATION_CATALOG`, never duplicate its subject/object/ref-kind sets. `compatible_objects()` must use the catalog's `object_kinds` and only return current registry IDs; it must never promote a location hint to a claim ID. `source_fact_options()` must filter to actual fact IDs and the allowed spatial fact kinds for spatial semantics. Remove the existing draft-level subject/object relation checks if these functions and the final relation validator cover the same cases; there must be one diagnostic owner per contract.

- [ ] **Step 3: Implement deterministic project-package decomposition**

Represent a package as a semantic skeleton plus typed components. When a skeleton contains both an axis and a physical connection, emit `axis` and `road/linear` components; when it contains a service zone and a service node, emit `zone` and `facility`; when it contains protection/restoration and explicit physical works, keep overlay and physical work separate. If the text contains only conceptual “串联/服务/修复” language with no physical component, retain the semantic objective and do not invent an executable hard relation.

- [ ] **Step 4: Add bounded candidate information to the prompt context**

Render only the current dimension's source fact IDs and a short relation candidate table. The worker's exact identity validator remains authoritative; unknown refs produce a typed grounding request diagnostic rather than a fabricated replacement.

- [ ] **Step 5: Run candidate tests and existing relation/claim tests**

Run: `python -m pytest -q -o addopts='' backend/tests/core/test_l3_claim_compiler_candidates.py backend/tests/core/test_l3_claim_contract_closure.py backend/tests/core/test_planning_intent_graph_compiler.py backend/tests/core/test_parameterized_intent_graph_compiler.py`

Expected: all pass; the existing relation catalog remains the single source of truth.

---

### Task 3: Add failure scopes, dependency-closure decisions, and no-progress detection

**Files:**
- Create: `backend/app/domain/program/failure_scope.py`
- Modify: `backend/app/contracts/domain/l3_contracts.py` to add `root_issue_id`, `failure_scope`, and `dependency_scope` defaults to `ProgramIssue`
- Modify: `backend/app/domain/program/aggregate.py` to classify claim diagnostics
- Modify: `backend/app/domain/program/gate.py` to gate only unsafe active closures
- Modify: `backend/app/domain/program/worker.py` to stop repeated local repair and downgrade telemetry
- Test: `backend/tests/core/test_l3_failure_scope.py`

**Interfaces:**
- `FailureScope = Enum("field", "relation", "claim", "project_package", "program")`
- `error_fingerprint(issue: object) -> str`
- `ClaimDependencyGraph.from_program(program: PlanningProgram) -> ClaimDependencyGraph`
- `classify_failure_scope(issue: ProgramIssue, dependency_graph: ClaimDependencyGraph) -> FailureDecision`
- `CompileSnapshot(accepted_claim_ids: frozenset[str], failure_fingerprints: frozenset[str], failed_dependency_scope: frozenset[str])`
- `detect_no_progress(previous: CompileSnapshot, current: CompileSnapshot) -> NoProgressDecision`

- [ ] **Step 1: Write failure-scope and loop-breaker tests**

```python
def test_semantic_compile_exhausted_is_telemetry() -> None:
    issue = ProgramIssue(code="semantic_compile_exhausted", severity="error", claim_id="bad")
    decision = classify_failure_scope(issue, ClaimDependencyGraph())
    assert decision.blocking is False


def test_repeated_fingerprint_stops_without_new_accepted_claim() -> None:
    previous = CompileSnapshot(frozenset({"ok"}), frozenset({"axis|connect_network|axis"}), frozenset({"bad"}))
    current = CompileSnapshot(frozenset({"ok"}), frozenset({"axis|connect_network|axis"}), frozenset({"bad"}))
    assert detect_no_progress(previous, current).stop is True


def test_gate_does_not_block_unrelated_admitted_intervention() -> None:
    program = PlanningProgram(
        interventions=[admitted_facility],
        program_issues=[ProgramIssue(
            severity="error", code="claim_contract_invalid", claim_id="quarantined-claim",
        )],
    )
    assert evaluate_l3_gate(program).passed is True
```

- [ ] **Step 2: Implement normalized fingerprints and dependency graph**

Fingerprints retain stable code, component kind, relation template, and subject kind; strip IDs, prose, and duplicate wrapper text. The graph maps claim IDs to intervention IDs and hard relation/dependency endpoints. A claim-level issue blocks only its own admitted closure; a hard relation to a quarantined claim expands to that package/dependency closure; global artifact or empty-program errors remain program-scoped.

- [ ] **Step 3: Extend `ProgramIssue` and diagnostic conversion**

Populate `claim_id`/`claim_ids`, `root_issue_id`, and `failure_scope` at the diagnostic boundary. Preserve old serialized issues by giving new fields defaults. `semantic_compile_exhausted` receives `failure_scope="claim"` and `severity="warning"` even when the old worker string contains an error wrapper.

- [ ] **Step 4: Replace the gate's global blocking list**

Remove the duplicated early return in `gate.py`. Compute decisions, discard telemetry and quarantined-claim issues that do not touch admitted interventions, and create `program_rework` only for the resulting unsafe closure. Include `failure_scope`, `dependency_scope`, and `root_issue_id` in pending-request context.

- [ ] **Step 5: Integrate the no-progress breaker into the worker loop**

After each local repair, snapshot accepted IDs and normalized fingerprints. If the same fingerprint repeats with no accepted-ID increase and no closure shrink, stop provider repair, quarantine the affected claim/relation, append `WARNING[semantic_compile_no_progress]`, and continue with unaffected claims. Change the final `semantic_compile_exhausted` diagnostic to `WARNING[...]` and never add it to `blocking` feedback.

- [ ] **Step 6: Run failure-scope and gate tests**

Run: `python -m pytest -q -o addopts='' backend/tests/core/test_l3_failure_scope.py backend/tests/core/test_l3_classification_gate.py backend/tests/core/test_l3_program_target_compaction.py backend/tests/core/test_program_semantic_repair.py`

Expected: claim-local errors no longer create whole-program rework, while global integrity errors still fail closed.

---

### Task 4: Simplify the L3 prompts around semantic intent and candidate selection

**Files:**
- Modify: `backend/app/infrastructure/llm/prompts/detailed.py`
- Modify: `backend/app/domain/program/worker.py` local repair prompt and revision feedback wording
- Update: `backend/tests/core/test_l3_claim_prompt_boundary.py`
- Update: `backend/tests/core/test_l3_claim_contract_closure.py`
- Test: `backend/tests/core/test_l3_prompt_simplification.py`

**Interfaces:**
- Keep `get_dimension_prompt(dimension_key: str, revision_instruction: str = "", **kwargs) -> str`.
- Keep `CLAIMS_OUTPUT_GUIDE`, `L3_EVIDENCE_PRIORITY_GUIDE`, `L3_EMISSION_CHECKLIST`, and `LOCATION_EVIDENCE_GUIDE` exports for callers.

- [ ] **Step 1: Write prompt tests for reduced responsibility**

```python
def test_prompt_delegates_closed_sets_to_schema_and_catalog() -> None:
    from app.infrastructure.llm.prompts.detailed import get_dimension_prompt

    prompt = get_dimension_prompt("traffic_planning", semantic_contract="道路连接")
    assert "schema 是字段和组件类型的唯一约束来源" in prompt
    assert "relation catalog 是关系候选的唯一来源" in prompt
    assert prompt.count("suggested_category=") <= 2
    assert "以下输出非法" not in prompt
    assert "serve 的 subject 只能是 facility" not in prompt
```

- [ ] **Step 2: Rewrite the static guide**

Keep only: claims-only output/no geometry; semantic role and package identity; component decomposition examples; exact evidence IDs supplied by context; missing refs become grounding requests; relation selection must use the supplied candidate set; preserve uncertainty. Remove long enum tables, typed parameter field tables, negative combinations, and repeated “必须/只能/不得” cross-field rules now enforced by the union/catalog/validator. Delete the existing two-line relation hard-rule addition and the long worker repair instruction as redundant after this rewrite.

- [ ] **Step 3: Shorten repair instructions**

The worker repair prompt should say “return only the rejected component, keep `claim_id`, choose a schema-valid component, remove unsupported relations, and leave unknown refs for grounding” plus the deterministic errors and current candidate IDs. It must not restate the full category/asset matrix.

- [ ] **Step 4: Update prompt boundary tests and run them**

Run: `python -m pytest -q -o addopts='' backend/tests/core/test_l3_prompt_simplification.py backend/tests/core/test_l3_claim_prompt_boundary.py backend/tests/core/test_l3_claim_contract_closure.py backend/tests/core/test_planning_claim_provider_adapter.py`

Expected: prompt length and repeated hard-rule count decrease, while evidence identity and claims-only boundaries remain covered.

---

### Task 5: Full regression and artifact review

**Files:**
- Review all modified files from Tasks 1–4.
- Test: `backend/tests/core/test_l3_*`, relation compiler tests, and acceptance replay tests that exercise L3 → TARGET_PROJECTION.

- [ ] **Step 1: Run the focused regression suite**

Run: `python -m pytest -q -o addopts='' backend/tests/core/test_l3_*.py backend/tests/core/test_planning_claim_provider_adapter.py backend/tests/core/test_planning_intent_graph_compiler.py backend/tests/core/test_parameterized_intent_graph_compiler.py`

- [ ] **Step 2: Run the acceptance boundary suite**

Run: `python -m pytest -q -o addopts='' backend/tests/integration/test_candidate_validation_boundary.py backend/tests/acceptance/test_simulated_l3_to_ground_stage.py backend/tests/acceptance/test_real_graph_resume_delivery.py`

- [ ] **Step 3: Run syntax and schema smoke checks**

Run: `python -m compileall -q backend/app/domain/program backend/app/infrastructure/llm/prompts backend/app/infrastructure/llm/planning_claims.py` and a small script that prints `L3ClaimOutput.model_json_schema()["properties"]["claims"]["items"]` and verifies the discriminator/oneOf fields.

- [ ] **Step 4: Review the diff and report remaining limits**

Run: `git diff --check`, `git status --short`, and `git diff --stat`. Confirm no secrets or generated run artifacts were added, accepted IDs are unchanged in replay fixtures, and any real-provider/20-seed run not performed locally is explicitly reported as open.
