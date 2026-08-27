# LLM-Native SELECT and Constrained EXECUTE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the `PlanningDeliberationGraph` and `ConstrainedMaterializationGraph` defined in `docs/design/03_PLANNING_EXECUTION.md` without weakening closed-set identity, hard-constraint, approval, atomic-commit, or replay guarantees.

**Architecture:** SELECT becomes an artifact-backed LangGraph child graph in which LLM nodes frame cases, propose closed-set scenarios, plan deterministic tools, and critique observed results; existing optimizers become registered tools. EXECUTE gains an approved outcome envelope and an artifact-backed recipe/observation/recovery loop, while deterministic validators retain authority over equivalence and atomic commit.

**Tech Stack:** Python 3, Pydantic V2, LangGraph, existing structured LLM runner, pytest, existing artifact/checkpoint infrastructure, existing GIS/network/solver adapters.

## Global Constraints

- L1 remains the only semantic producer from raw session reports.
- LLM outputs never contain new runtime IDs, source IDs, coordinates, WKT, GeoJSON, free SQL, free code, or direct write bodies.
- Formal scenarios require deterministic tool observations and hard-constraint validation.
- EXECUTE recovery may change method only; it may not change the approved outcome.
- Model calls, tool calls, validation, artifact commit, and atomic commit remain separate nodes.
- State/checkpoints contain immutable refs and serializable ledgers, not provider clients, geometries, locks, or mutable runtime objects.
- Preserve existing user changes and LF line endings; Python uses 4 spaces and double quotes.

---

### Task 1: Add deliberation and outcome-envelope contracts

**Files:**
- Create: `backend/app/contracts/planning/deliberation.py`
- Create: `backend/app/contracts/workflow/materialization_recipe_contracts.py`
- Modify: `backend/app/contracts/planning/scenario.py`
- Modify: `backend/app/contracts/planning/approval.py`
- Test: `backend/tests/contracts/test_planning_deliberation_contracts.py`
- Test: `backend/tests/contracts/test_materialization_recipe_contracts.py`

**Interfaces:**
- Produces: `DecisionCase`, `ScenarioPrototype`, `DecisionToolActionProposal`, `DecisionDeliberationAudit`, `ApprovedOutcomeEnvelope`, `MaterializationCase`, `MaterializationActionProposal`, `ExecutionObservation`, `RecoveryProposal`.
- Preserves: existing `ScenarioSet`, `PlanningScenario`, `ApprovedExecutionInput` readers during a bounded migration window; new runs must write the new fields.

- [ ] **Step 1: Write failing closed-set and envelope tests**

```python
def test_scenario_prototype_rejects_runtime_identity_fields() -> None:
    with pytest.raises(ValidationError):
        ScenarioPrototype.model_validate({**valid_prototype(), "coordinates": [1, 2]})

def test_outcome_envelope_requires_geometry_and_recipe_policy() -> None:
    with pytest.raises(ValidationError):
        ApprovedOutcomeEnvelope.model_validate({"selected_candidate_ids": ["c1"]})
```

- [ ] **Step 2: Run contract tests and verify they fail**

Run: `pytest -q -o addopts='' backend/tests/contracts/test_planning_deliberation_contracts.py backend/tests/contracts/test_materialization_recipe_contracts.py`

- [ ] **Step 3: Implement strict Pydantic V2 contracts**

```python
class ScenarioPrototype(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prototype_id: str
    selected_candidate_ids: list[str]
    tool_action_refs: list[str]
    input_digest: str

class ApprovedOutcomeEnvelope(BaseModel):
    selected_candidate_ids: list[str]
    approved_geometry_refs: list[str]
    allowed_recipe_ids: list[str]
    allowed_repair_classes: list[str]
    tolerance_policy: dict[str, float]
    envelope_digest: str
```

- [ ] **Step 4: Run tests and commit**

Run the command from Step 2 plus `backend/tests/contracts/test_scenario_set_contracts.py backend/tests/contracts/test_approval_and_validation_certificates.py`.

Commit: `git commit -m "feat: add deliberation and execution envelope contracts"`

### Task 2: Build SELECT state, adapters, and deterministic case compiler

**Files:**
- Create: `backend/app/domain/select/subgraph_state.py`
- Create: `backend/app/domain/select/nodes/admit.py`
- Create: `backend/app/domain/select/nodes/cases.py`
- Create: `backend/app/domain/select/nodes/baselines.py`
- Test: `backend/tests/core/test_select_deliberation_admission.py`
- Test: `backend/tests/core/test_select_decision_case_compiler.py`

**Interfaces:**
- Consumes: current `GroundedPlanningProblem` artifact ref and fingerprint.
- Produces: `PlanningDeliberationState` containing refs only and stable `DecisionCase` artifacts.

- [ ] **Step 1: Write failing admission, replay, and grouping tests**

```python
def test_case_compiler_keeps_shared_resource_targets_together() -> None:
    cases = compile_decision_cases(shared_parcel_problem())
    assert cases[0].target_refs == ["target:a", "target:b"]

def test_admit_reuses_committed_same_fingerprint() -> None:
    result = admit_problem(replayed_invocation())
    assert result.exit_status == "reused"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q -o addopts='' backend/tests/core/test_select_deliberation_admission.py backend/tests/core/test_select_decision_case_compiler.py`

- [ ] **Step 3: Implement ref-only state, fingerprint admission, deterministic grouping, and baselines**

```python
def compile_decision_cases(problem: GroundedPlanningProblem) -> list[DecisionCase]:
    groups = group_by_explicit_relations_and_resources(problem)
    return [build_case(group, problem.fingerprint) for group in groups]
```

- [ ] **Step 4: Run focused and existing readiness tests; commit**

Run Step 2 plus `backend/tests/core/test_solver_readiness.py backend/tests/core/test_select_gate_deferred_targets.py`.

Commit: `git commit -m "feat: compile stable SELECT decision cases"`

### Task 3: Add SELECT LLM proposal nodes and deterministic tool registry

**Files:**
- Create: `backend/app/domain/select/nodes/frame.py`
- Create: `backend/app/domain/select/nodes/propose.py`
- Create: `backend/app/domain/select/nodes/proposal_validation.py`
- Create: `backend/app/domain/select/tools/registry.py`
- Modify: `backend/app/domain/allocation/scenario_optimizer.py`
- Modify: `backend/app/domain/allocation/solver_portfolio.py`
- Test: `backend/tests/core/test_select_closed_set_proposals.py`
- Test: `backend/tests/core/test_select_tool_registry.py`

**Interfaces:**
- Produces: validated `ScenarioPrototype` and idempotent `DecisionToolActionProposal` refs.
- Tool protocol: `execute(action, problem_ref) -> DecisionToolObservation`.

- [ ] **Step 1: Write negative tests for invented IDs, stale digests, free payloads, and unknown tools**

```python
def test_validator_rejects_candidate_outside_problem_domain() -> None:
    result = validate_prototype(prototype(ids=["invented"]), closed_ids={"c1"})
    assert result.status == "rejected"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q -o addopts='' backend/tests/core/test_select_closed_set_proposals.py backend/tests/core/test_select_tool_registry.py`

- [ ] **Step 3: Implement structured LLM runners and registry adapters**

```python
class DecisionTool(Protocol):
    capability: str
    async def execute(self, action: DecisionToolActionProposal) -> DecisionToolObservation: ...
```

Register existing parcel/network/Pareto backends without changing their deterministic semantics.

- [ ] **Step 4: Run existing optimizer/portfolio suites; commit**

Run Step 2 plus `backend/tests/core/test_scenario_optimizer.py backend/tests/core/test_solver_portfolio_slice1.py backend/tests/core/test_relation_aware_scenario_solver.py`.

Commit: `git commit -m "feat: add closed-set SELECT proposals and tools"`

### Task 4: Complete the deliberation loop and wire the SELECT stage

**Files:**
- Create: `backend/app/domain/select/subgraph.py`
- Create: `backend/app/domain/select/nodes/evaluate.py`
- Create: `backend/app/domain/select/nodes/critic.py`
- Create: `backend/app/domain/select/nodes/assess.py`
- Create: `backend/app/domain/select/nodes/compile.py`
- Create: `backend/app/domain/select/nodes/persist.py`
- Modify: `backend/app/workflow/stages/select.py`
- Modify: `backend/app/workflow/plan_state/state.py`
- Test: `backend/tests/core/test_select_deliberation_subgraph.py`
- Test: `backend/tests/core/test_select_deliberation_replay.py`

**Interfaces:**
- Produces: authoritative `ScenarioSet`, audit refs, certificates, or a typed upstream request.

- [ ] **Step 1: Write failing observation-driven, critic, zero-gain, and replay tests**

```python
async def test_critic_requests_new_metric_before_recommendation() -> None:
    result = await graph.ainvoke(problem_without_fairness_observation())
    assert result["round_number"] == 2
    assert result["scenario_set_ref"]
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q -o addopts='' backend/tests/core/test_select_deliberation_subgraph.py backend/tests/core/test_select_deliberation_replay.py`

- [ ] **Step 3: Implement the graph with separate model/tool/evaluate/commit nodes**

```python
def build_select_subgraph() -> CompiledStateGraph:
    graph = StateGraph(PlanningDeliberationState)
    graph.add_node("propose", propose_scenarios_and_tools)
    graph.add_node("execute_tools", execute_decision_tools)
    graph.add_node("evaluate", evaluate_scenarios)
    graph.add_node("critic", critic)
    graph.add_node("persist", persist_and_gate)
    return graph.compile()
```

- [ ] **Step 4: Run SELECT, scenario authority, and crash/resume suites; commit**

Run Step 2 plus `backend/tests/contracts/test_single_scenario_authority.py backend/tests/core/test_subgraph_crash_resume.py`.

Commit: `git commit -m "feat: add LLM-native SELECT deliberation graph"`

### Task 5: Freeze ApprovedOutcomeEnvelope and register materialization recipes

**Files:**
- Modify: `backend/app/domain/allocation/approval_input.py`
- Modify: `backend/app/domain/materialization/approved_plan_builder.py`
- Create: `backend/app/domain/materialization/recipes/registry.py`
- Create: `backend/app/domain/materialization/equivalence.py`
- Test: `backend/tests/core/test_approved_outcome_envelope.py`
- Test: `backend/tests/core/test_materialization_equivalence.py`

**Interfaces:**
- Produces: envelope-bound recipe capabilities and `EquivalenceResult`.

- [ ] **Step 1: Write failing stale-envelope and non-equivalent recovery tests**

```python
def test_equivalence_rejects_changed_candidate() -> None:
    result = check_equivalence(envelope("c1"), staged(candidate_id="c2"))
    assert not result.accepted
```

- [ ] **Step 2: Run tests, implement canonical envelope digest and equivalence checks, rerun tests**

Run: `pytest -q -o addopts='' backend/tests/core/test_approved_outcome_envelope.py backend/tests/core/test_materialization_equivalence.py backend/tests/core/test_execute_approval_boundary.py`

- [ ] **Step 3: Commit**

Commit: `git commit -m "feat: freeze approved outcome envelope"`

### Task 6: Build the constrained EXECUTE observation/recovery graph

**Files:**
- Create: `backend/app/domain/execute/subgraph.py`
- Create: `backend/app/domain/execute/subgraph_state.py`
- Create: `backend/app/domain/execute/nodes/plan.py`
- Create: `backend/app/domain/execute/nodes/observe.py`
- Create: `backend/app/domain/execute/nodes/diagnose.py`
- Create: `backend/app/domain/execute/nodes/recover.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/domain/materialization/task_scheduler.py`
- Modify: `backend/app/domain/materialization/atomic_commit.py`
- Test: `backend/tests/core/test_execute_constrained_subgraph.py`
- Test: `backend/tests/core/test_execute_recovery_replay.py`

**Interfaces:**
- Consumes: executable `ApprovedExecutionInput` with envelope.
- Produces: committed or aborted `ExecutionStaging`, execution audit refs, and typed return route.

- [ ] **Step 1: Write failing fast-path, allowlist, recovery, atomicity, and replay tests**

```python
async def test_single_recipe_fast_path_uses_no_llm() -> None:
    result = await graph.ainvoke(simple_approved_input())
    assert result["llm_calls"] == 0
    assert result["exit_status"] == "committed"
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest -q -o addopts='' backend/tests/core/test_execute_constrained_subgraph.py backend/tests/core/test_execute_recovery_replay.py`

- [ ] **Step 3: Implement ref-only nodes and preserve atomic commit as the sole formal writer**

```python
def route_after_equivalence(state: ExecutionGraphState) -> str:
    if state["equivalence_status"] == "accepted":
        return "execute_in_staging"
    return "compile_typed_failure"
```

- [ ] **Step 4: Run execution regression suites; commit**

Run Step 2 plus `backend/tests/core/test_atomic_execution_commit.py backend/tests/core/test_execution_staging_runtime.py backend/tests/core/test_execution_task_dag_scheduler.py`.

Commit: `git commit -m "feat: add constrained materialization recovery graph"`

### Task 7: Add benchmarks, end-to-end acceptance, and retire obsolete paths

**Files:**
- Modify: `backend/tests/acceptance/test_simulated_root_graph_facility_delivery.py`
- Modify: `backend/tests/acceptance/test_simulated_root_graph_road_delivery.py`
- Modify: `backend/tests/acceptance/test_recorded_real_root_graph_replay.py`
- Create: `backend/tests/acceptance/test_llm_native_select_execute.py`
- Modify: `docs/design/05_MIGRATION.md`
- Modify: `docs/architecture/CURRENT_RUNTIME.md`

**Interfaces:**
- Verifies: two villages, five decision shapes, mixed workers, a useful critic revision, an equivalent recovery, a rejected non-equivalent recovery, 100% coverage, zero unexpected outputs, and zero repeated side effects.

- [ ] **Step 1: Add a versioned acceptance manifest and failing assertions**

```python
assert audit.rounds_with_positive_information_gain >= 1
assert staging.selected_to_materialized_coverage == 1.0
assert staging.unexpected_output_count == 0
assert replay.repeated_side_effect_count == 0
```

- [ ] **Step 2: Run focused acceptance tests, then the affected suite**

Run: `pytest -q -o addopts='' backend/tests/acceptance/test_llm_native_select_execute.py backend/tests/acceptance/test_simulated_root_graph_facility_delivery.py backend/tests/acceptance/test_simulated_root_graph_road_delivery.py backend/tests/acceptance/test_recorded_real_root_graph_replay.py`

- [ ] **Step 3: Remove production imports of obsolete SELECT projection and worker fallback paths**

Run: `rg -n "SiteSelectionDecision|scenario_worker_projection|select_service|worker.*fallback" backend/app`

Every remaining match must be a clearly labeled legacy reader or be deleted; new-run producers must be zero.

- [ ] **Step 4: Run compile, full affected tests, and documentation checks**

Run: `python -m compileall -q backend/app`

Run: `git diff --check`

- [ ] **Step 5: Record only runtime-verified evidence and commit**

Commit: `git commit -m "test: accept LLM-native planning and execution"`

## Self-review record

- Spec coverage: contracts, SELECT graph, tool portfolio, critic/information gain, approval envelope, EXECUTE recipes/recovery/equivalence, atomic commit, replay, benchmarks, and migration cleanup are each assigned to a task.
- Placeholder scan: no TBD/TODO or unspecified “add tests” steps remain.
- Type consistency: `ScenarioPrototype`, `DecisionToolActionProposal`, `ApprovedOutcomeEnvelope`, `MaterializationActionProposal`, `ExecutionObservation`, and `RecoveryProposal` names match the target design.

## Execution handoff

Plan implementation should proceed either with subagent-driven development and review after each task, or inline with the executing-plans skill and explicit checkpoints. Do not implement both SELECT and EXECUTE in one unreviewed change set.
