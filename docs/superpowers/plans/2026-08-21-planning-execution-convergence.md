# Planning Execution Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the transitional double-selection path and single-winner bounded product search with one authoritative multi-scenario planning contract, a formal solver boundary, immutable execution input, and independent validation certificates.

**Architecture:** GROUND owns candidate recall and constraint inputs. A `ScenarioOptimizer` produces a `ScenarioSet` containing feasible alternatives, objective vectors, bounds, findings, and a recommendation; SELECT projects this one result to compatibility contracts during migration. EXECUTE accepts only an approved scenario snapshot, and VALIDATE certifies the materialized result against the same problem, evidence, bundle, and solver digests.

**Tech Stack:** Python 3.12, Pydantic V2, OR-Tools CP-SAT, Shapely, LangGraph orchestration, pytest.

## Global Constraints

- GROUND never selects the final scenario.
- The solver never creates coordinates, source BSMs, or source membership.
- EXECUTE never re-selects, re-scores, or silently drops an approved candidate.
- A scenario marked complete has zero violated, unresolved, deferred, or not-evaluable hard constraints.
- An infeasible result is a valid planning result when it includes a machine-readable conflict explanation.
- Preserve deterministic fingerprints for the same problem, source snapshots, solver configuration, and approval.
- Keep `SiteSelectionDecision` only as a migration projection until all consumers use `ScenarioSet`; do not maintain two independent decision engines.
- Do not remove compatibility contracts until repository-wide call-site search and acceptance tests prove they are unused.
- Keep Python indentation at 4 spaces, frontend indentation at 2 spaces, and line endings LF.
- Do not commit unrelated worktree changes.

---

## Target File Structure

```text
backend/app/contracts/planning/
├── scenario.py
├── scenario_set.py
├── solver.py
└── validation_certificate.py

backend/app/domain/allocation/
├── candidate_preparation.py
├── cp_sat_optimizer.py
├── scenario_projection.py
└── scenario_solver.py

backend/app/domain/materialization/
├── approved_execution.py
└── atomic_commit.py
```

### Task 1: Add ScenarioSet and solver-result contracts

**Files:**
- Create: `backend/app/contracts/planning/scenario_set.py`
- Create: `backend/app/contracts/planning/solver.py`
- Modify: `backend/app/contracts/planning/__init__.py`
- Create: `backend/tests/contracts/test_scenario_set_contracts.py`

**Interfaces:**
- Consumes: existing `PlanningScenario` fingerprints and metric dictionaries.
- Produces: `ScenarioObjective`, `SolverCertificate`, and `ScenarioSet`.

- [ ] **Step 1: Write failing contract tests**

```python
import pytest
from pydantic import ValidationError

from app.contracts.planning.scenario import PlanningScenario, ScenarioFinding
from app.contracts.planning.scenario_set import ScenarioObjective, ScenarioSet
from app.contracts.planning.solver import SolverCertificate


@pytest.fixture
def make_scenario():
    def factory(scenario_id: str, status: str = "complete") -> PlanningScenario:
        return PlanningScenario(
            scenario_id=scenario_id,
            baseline_ref="baseline:test",
            problem_fingerprint="p" * 64,
            status=status,
        )

    return factory


def test_recommended_scenario_must_belong_to_set(make_scenario) -> None:
    with pytest.raises(ValidationError):
        ScenarioSet(
            scenario_set_id="set:1",
            problem_fingerprint="p" * 64,
            scenarios=[make_scenario("scenario:a")],
            recommended_scenario_id="scenario:missing",
            solver_certificate=SolverCertificate(
                status="feasible",
                solver_name="cp-sat",
                solver_version="test",
                inspected_solution_count=1,
            ),
        )


def test_complete_set_requires_a_feasible_recommendation(make_scenario) -> None:
    result = ScenarioSet(
        scenario_set_id="set:1",
        problem_fingerprint="p" * 64,
        scenarios=[make_scenario("scenario:a", status="complete")],
        recommended_scenario_id="scenario:a",
        objectives=[ScenarioObjective(name="suitability", direction="maximize", weight=1.0)],
        solver_certificate=SolverCertificate(
            status="optimal",
            solver_name="cp-sat",
            solver_version="test",
            inspected_solution_count=1,
        ),
        status="complete",
    )
    assert result.recommended_scenario.scenario_id == "scenario:a"
    assert len(result.fingerprint) == 64


def test_infeasible_set_requires_findings() -> None:
    with pytest.raises(ValidationError):
        ScenarioSet(
            scenario_set_id="set:infeasible",
            problem_fingerprint="p" * 64,
            solver_certificate=SolverCertificate(
                status="infeasible",
                solver_name="cp-sat",
                solver_version="test",
                inspected_solution_count=0,
            ),
            status="infeasible",
        )
```

- [ ] **Step 2: Run the tests and verify the contracts are missing**

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_scenario_set_contracts.py
```

Expected: collection FAIL.

- [ ] **Step 3: Implement solver contracts**

Use these fields:

```python
from typing import Literal
from pydantic import BaseModel, Field


class ScenarioObjective(BaseModel):
    name: str = Field(min_length=1)
    direction: Literal["minimize", "maximize"]
    weight: float = 1.0
    unit: str = ""


class SolverCertificate(BaseModel):
    status: Literal["optimal", "feasible", "infeasible", "bounded", "failed"]
    solver_name: str = Field(min_length=1)
    solver_version: str = Field(min_length=1)
    inspected_solution_count: int = Field(ge=0)
    objective_bound: float | None = None
    wall_time_seconds: float = Field(default=0.0, ge=0.0)
    model_fingerprint: str = ""
    configuration_fingerprint: str = ""
```

- [ ] **Step 4: Implement ScenarioSet validation and fingerprinting**

Use these fields:

```python
class ScenarioSet(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    scenario_set_id: str = Field(min_length=1)
    problem_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_snapshot_digest: str = ""
    bundle_snapshot_digest: str = ""
    objectives: list[ScenarioObjective] = Field(default_factory=list)
    scenarios: list[PlanningScenario] = Field(default_factory=list)
    pareto_scenario_ids: list[str] = Field(default_factory=list)
    recommended_scenario_id: str = ""
    solver_certificate: SolverCertificate
    findings: list[ScenarioFinding] = Field(default_factory=list)
    status: Literal["draft", "partial", "complete", "infeasible", "failed"] = "draft"
    fingerprint: str = ""
```

The model validator must sort scenarios by ID, reject duplicate IDs, require the recommendation and Pareto IDs to exist, require a complete recommendation when set status is complete, require at least one finding when status is infeasible/failed, and calculate SHA-256 from canonical JSON excluding `created_at` and `fingerprint`.

Add this property because all later tasks use it as the single recommendation lookup:

```python
@property
def recommended_scenario(self) -> PlanningScenario:
    for scenario in self.scenarios:
        if scenario.scenario_id == self.recommended_scenario_id:
            return scenario
    raise ValueError("recommended scenario is unavailable")
```

- [ ] **Step 5: Run contract tests**

```powershell
pytest -q -o addopts='' tests/contracts/test_scenario_set_contracts.py tests/core/test_scenario_fingerprint_determinism.py
```

Expected: PASS.

- [ ] **Step 6: Commit ScenarioSet contracts**

```powershell
git add backend/app/contracts/planning/scenario_set.py backend/app/contracts/planning/solver.py backend/app/contracts/planning/__init__.py backend/tests/contracts/test_scenario_set_contracts.py
git commit -m "feat: define auditable multi-scenario planning contracts"
```

### Task 2: Introduce a formal optimizer port and CP-SAT implementation

**Files:**
- Create: `backend/app/contracts/ports/scenario_optimizer.py`
- Modify: `backend/app/contracts/ports/__init__.py`
- Create: `backend/app/domain/allocation/cp_sat_optimizer.py`
- Modify: `backend/app/domain/allocation/scenario_solver.py`
- Create: `backend/tests/core/test_cp_sat_scenario_optimizer.py`

**Interfaces:**
- Consumes: `GroundedPlanningProblem`, `RelationEvaluationContext`, objective definitions, and a scenario limit.
- Produces: `ScenarioSet` with feasible alternatives and a solver certificate.

- [ ] **Step 1: Write failing optimizer tests**

```python
import pytest

from app.contracts.planning.constraint_factor import ConstraintFactor
from app.contracts.planning.relation_parameters import DistanceParameters
from app.contracts.spatial.candidate_geometry import CandidateGeometry
from app.contracts.spatial.grounded_problem import GroundedCandidateDomain, GroundedPlanningProblem
from app.domain.allocation.cp_sat_optimizer import CpSatScenarioOptimizer
from app.domain.relations.service import RelationEvaluationContext


def candidate(candidate_id: str, target_id: str, x: float, score: float) -> CandidateGeometry:
    return CandidateGeometry(
        candidate_id=candidate_id,
        target_id=target_id,
        kind="point",
        role="execution_geometry",
        wkt=f"POINT ({x} 0)",
        crs="EPSG:3857",
        source_ref=f"source:{candidate_id}",
        evidence_refs=[f"evidence:{candidate_id}"],
        suitability_components={"suitability": score},
    )


@pytest.fixture
def relation_context() -> RelationEvaluationContext:
    return RelationEvaluationContext(scenario_id="scenario:test", metric_crs="EPSG:3857")


@pytest.fixture
def simple_two_target_problem() -> GroundedPlanningProblem:
    return GroundedPlanningProblem(
        candidate_domains=[
            GroundedCandidateDomain(target_id="a", candidate_ids=["a1", "a2"]),
            GroundedCandidateDomain(target_id="b", candidate_ids=["b1", "b2"]),
        ],
        candidate_geometries=[
            candidate("a1", "a", 0.0, 0.9),
            candidate("a2", "a", 10.0, 0.8),
            candidate("b1", "b", 20.0, 0.7),
            candidate("b2", "b", 30.0, 0.6),
        ],
    )


@pytest.fixture
def hard_conflict_problem() -> GroundedPlanningProblem:
    factor = ConstraintFactor(
        factor_id="factor:near-hard",
        kind="near",
        evaluator_key="near",
        subject_ref="a",
        object_ref="b",
        hard=True,
        parameters=DistanceParameters(max_distance_m=10, metric="euclidean"),
    )
    return GroundedPlanningProblem(
        candidate_domains=[
            GroundedCandidateDomain(target_id="a", candidate_ids=["a1"]),
            GroundedCandidateDomain(target_id="b", candidate_ids=["b1"]),
        ],
        candidate_geometries=[
            candidate("a1", "a", 0.0, 0.5),
            candidate("b1", "b", 100.0, 0.5),
        ],
        constraint_factors=[factor],
    )


def test_optimizer_returns_multiple_feasible_alternatives(simple_two_target_problem, relation_context) -> None:
    result = CpSatScenarioOptimizer().solve(
        simple_two_target_problem,
        scenario_set_id="set:alternatives",
        evaluator_context=relation_context,
        max_scenarios=3,
    )
    assert result.status in {"complete", "partial"}
    assert 2 <= len(result.scenarios) <= 3
    assert result.recommended_scenario_id in {item.scenario_id for item in result.scenarios}


def test_optimizer_returns_infeasible_certificate(hard_conflict_problem, relation_context) -> None:
    result = CpSatScenarioOptimizer().solve(
        hard_conflict_problem,
        scenario_set_id="set:conflict",
        evaluator_context=relation_context,
        max_scenarios=3,
    )
    assert result.status == "infeasible"
    assert result.solver_certificate.status == "infeasible"
    assert any(item.code == "NO_HARD_FEASIBLE_SCENARIO" for item in result.findings)
```

- [ ] **Step 2: Define the optimizer port**

```python
from typing import Any, Protocol


class ScenarioOptimizer(Protocol):
    def solve(
        self,
        problem: GroundedPlanningProblem,
        *,
        scenario_set_id: str,
        evaluator_context: Any,
        max_scenarios: int = 5,
    ) -> ScenarioSet:
        raise NotImplementedError
```

- [ ] **Step 3: Build the CP-SAT cardinality model**

For every selectable candidate, create one BoolVar. Add exact cardinality constraints:

```python
if domain.selection_mode == "all_members":
    for candidate_id in candidate_ids:
        model.add(vars_by_candidate[candidate_id] == 1)
elif domain.selection_mode == "choose_one":
    model.add_exactly_one(vars_by_candidate[candidate_id] for candidate_id in candidate_ids)
else:
    model.add(sum(vars_by_candidate[candidate_id] for candidate_id in candidate_ids) >= 1)
```

Add pairwise exclusion for exclusive candidates whose Shapely intersection area is greater than `1e-12`:

```python
model.add(vars_by_candidate[left_id] + vars_by_candidate[right_id] <= 1)
```

Scale deterministic candidate suitability to integer coefficients with `round(score * 10000)` and maximize the sum. Preserve candidate IDs as the deterministic tie-break order when objective values are equal.

- [ ] **Step 4: Evaluate relational hard constraints and add no-good cuts**

After each CP-SAT assignment:

1. Build scenario features with the existing `build_scenario_features`.
2. Evaluate relation and network factors with the existing relation evaluators.
3. If a hard relation is violated or unresolved, add a no-good cut over the selected BoolVars.
4. If all hard relations are satisfied, append the scenario.
5. Add a no-good cut for the accepted assignment and continue until `max_scenarios`, infeasibility, or the configured time limit.

Use this cut:

```python
model.add(sum(vars_by_candidate[candidate_id] for candidate_id in selected_ids) <= len(selected_ids) - 1)
```

Mark the set `partial` and the certificate `bounded` when the time or inspected-solution limit is reached before proving exhaustion.

- [ ] **Step 5: Keep `solve_scenario` as a compatibility wrapper**

Implement:

```python
def solve_scenario(
    problem: GroundedPlanningProblem,
    *,
    scenario_id: str,
    evaluator_context: RelationEvaluationContext,
    max_scenarios: int = 1,
) -> PlanningScenario:
    result = CpSatScenarioOptimizer().solve(
        problem,
        scenario_set_id=f"set:{scenario_id}",
        evaluator_context=evaluator_context,
        max_scenarios=max_scenarios,
    )
    if result.recommended_scenario_id:
        return result.recommended_scenario
    return build_planning_scenario(
        scenario_id=scenario_id,
        problem=problem,
        findings=list(result.findings),
        metrics={"selected_candidate_count": 0.0},
        status="failed",
    )
```

Remove the old `max_scenarios != 1` failure branch after the new tests pass.

- [ ] **Step 6: Run solver tests**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_cp_sat_scenario_optimizer.py tests/core/test_relation_aware_scenario_solver.py tests/core/test_multi_member_scenario_selection.py tests/core/test_scenario_hard_relation_feasibility.py tests/core/test_scenario_fingerprint_determinism.py
```

Expected: PASS.

- [ ] **Step 7: Commit the optimizer**

```powershell
git add backend/app/contracts/ports/scenario_optimizer.py backend/app/contracts/ports/__init__.py backend/app/domain/allocation/cp_sat_optimizer.py backend/app/domain/allocation/scenario_solver.py backend/tests/core/test_cp_sat_scenario_optimizer.py
git commit -m "feat: solve auditable planning alternatives with cp-sat"
```

### Task 3: Make ScenarioSet the sole authoritative SELECT result

**Files:**
- Create: `backend/app/domain/allocation/candidate_preparation.py`
- Create: `backend/app/domain/allocation/scenario_projection.py`
- Modify: `backend/app/domain/allocation/select_service.py`
- Modify: `backend/app/workflow/stages/select.py`
- Modify: `backend/app/workflow/stage_adapter.py`
- Create: `backend/tests/core/test_select_scenario_authority.py`

**Interfaces:**
- Consumes: GroundingResult, typed planning intent, suitability, allocation evidence, and `ScenarioSet`.
- Produces: one persisted `scenario_set` artifact and a compatibility `SiteSelectionDecision` projected from its recommended scenario.

- [ ] **Step 1: Write a failing authority test**

```python
def test_site_selection_is_projection_of_recommended_scenario(select_stage_result, artifact_store) -> None:
    scenario_set = artifact_store.load(select_stage_result["artifact_refs"]["scenario_set"])
    decision = artifact_store.load(select_stage_result["artifact_refs"]["site_selection"])
    selected_by_target = {
        item.target_id: item.candidate_ids
        for item in scenario_set.recommended_scenario.target_selections
    }
    projected_by_target = {
        item.target_id: list(item.target_binding.get("candidate_ids", []))
        for item in decision.target_assignments
        if item.status == "placed"
    }
    assert projected_by_target == selected_by_target
```

- [ ] **Step 2: Extract candidate preparation from `select_aggregate`**

Create:

```python
@dataclass(frozen=True)
class PreparedSelection:
    problem: GroundedPlanningProblem
    suitability_surface: SuitabilitySurface
    demand_portfolio: DemandPortfolio
    portfolio_decision: PortfolioDecision
    diagnostics: tuple[str, ...] = ()


def prepare_selection_problem(
    grounding: GroundingResult,
    plan_intent: Any,
    context: PlanningContext,
    suitability_surface: SuitabilitySurface,
    zone_allocation: object,
    site_allocation: object,
) -> PreparedSelection:
    refined = refine_grounded_problem(grounding.problem, suitability_surface)
    return PreparedSelection(
        problem=refined,
        suitability_surface=suitability_surface,
        demand_portfolio=derive_demand_portfolio(plan_intent),
        portfolio_decision=build_portfolio_decision_from_surface(plan_intent, suitability_surface),
    )
```

Move only evidence/candidate preparation into this module; do not carry forward the old winner selection.

- [ ] **Step 3: Project the recommended scenario to the legacy decision contract**

Create:

```python
def project_site_selection(
    prepared: PreparedSelection,
    scenario_set: ScenarioSet,
) -> tuple[SiteSelectionDecision, list[LandDesignBrief]]:
    scenario = scenario_set.recommended_scenario
    decision = build_empty_site_selection(prepared)
    apply_scenario_selections(decision, prepared.problem, scenario)
    return decision, build_implementation_briefs(decision, scenario)
```

The projection may format legacy fields but may not score or choose candidates.

- [ ] **Step 4: Update SELECT orchestration**

The stage order becomes:

```text
calculate suitability/allocation evidence
→ prepare_selection_problem
→ ScenarioOptimizer.solve(max_scenarios=5)
→ persist scenario_set
→ choose the deterministic recommended scenario declared by ScenarioSet
→ project compatibility SiteSelectionDecision/briefs
→ persist compatibility artifacts
```

Add `ScenarioSet: "scenario_set"` to the authoritative artifact-key registry and retain `PlanningScenario: "planning_scenario"` as a temporary alias pointing at the recommendation.

- [ ] **Step 5: Turn `select_aggregate` into a deprecated adapter**

Keep its public signature for existing direct tests, but implement it as candidate preparation plus one-scenario solve plus projection. Add a `DeprecationWarning` with `stacklevel=2`; no workflow code may call it.

- [ ] **Step 6: Run SELECT tests**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_select_scenario_authority.py tests/core/test_select_output_kind_contract.py tests/core/test_evidence_to_execution_lineage.py tests/acceptance/test_select_execute_grounding_e2e.py
```

Expected: PASS and workflow code contains no call to `select_aggregate`.

- [ ] **Step 7: Commit SELECT convergence**

```powershell
git add backend/app/domain/allocation/candidate_preparation.py backend/app/domain/allocation/scenario_projection.py backend/app/domain/allocation/select_service.py backend/app/workflow/stages/select.py backend/app/workflow/stage_adapter.py backend/tests/core/test_select_scenario_authority.py
git commit -m "refactor: make scenario set authoritative in select"
```

### Task 4: Require an approved immutable scenario for EXECUTE

**Files:**
- Create: `backend/app/contracts/planning/approved_execution.py`
- Create: `backend/app/domain/materialization/approved_execution.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/application/interrupts.py`
- Create: `backend/tests/core/test_approved_scenario_execution.py`

**Interfaces:**
- Consumes: ScenarioSet fingerprint, selected Scenario fingerprint, problem/evidence/bundle digests, and approval metadata.
- Produces: `ApprovedExecutionInput` that is the only spatial selection input accepted by EXECUTE.

- [ ] **Step 1: Write failing immutable-input tests**

```python
import pytest

from app.domain.materialization.approved_execution import verify_approved_execution


def test_execution_rejects_scenario_fingerprint_mismatch(approved_input, scenario_set) -> None:
    approved_input.scenario_fingerprint = "0" * 64
    with pytest.raises(ValueError, match="scenario fingerprint"):
        verify_approved_execution(approved_input, scenario_set)


def test_execution_rejects_unapproved_recommendation(approved_input, scenario_set) -> None:
    approved_input.approved_scenario_id = "scenario:other"
    with pytest.raises(ValueError, match="approved scenario"):
        verify_approved_execution(approved_input, scenario_set)
```

- [ ] **Step 2: Implement the immutable input contract**

```python
class ApprovedExecutionInput(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    scenario_set_id: str = Field(min_length=1)
    scenario_set_fingerprint: str = Field(min_length=64, max_length=64)
    approved_scenario_id: str = Field(min_length=1)
    scenario_fingerprint: str = Field(min_length=64, max_length=64)
    problem_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_snapshot_digest: str = ""
    bundle_snapshot_digest: str = ""
    approval_kind: Literal["automatic_policy", "human"]
    approved_by: str = Field(min_length=1)
```

- [ ] **Step 3: Implement verification**

`verify_approved_execution` must compare every ID/fingerprint/digest to the loaded ScenarioSet and recommendation/approved scenario, reject partial or failed scenarios with unresolved hard relations, and return the exact `PlanningScenario` object on success.

- [ ] **Step 4: Update approval and EXECUTE orchestration**

At automatic-policy or human approval, persist `ApprovedExecutionInput`. EXECUTE loads `scenario_set` and `approved_execution`, verifies them, and builds worker tasks from the returned scenario. It may still emit compatibility `SiteSelectionDecision` metadata, but it may not read that decision to choose geometry.

- [ ] **Step 5: Run approval and execution tests**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_approved_scenario_execution.py tests/core/test_evidence_to_execution_lineage.py tests/acceptance/test_select_execute_grounding_e2e.py tests/acceptance/test_complete_execution_render.py
```

Expected: PASS.

- [ ] **Step 6: Commit immutable execution input**

```powershell
git add backend/app/contracts/planning/approved_execution.py backend/app/domain/materialization/approved_execution.py backend/app/workflow/stages/execute.py backend/app/application/interrupts.py backend/tests/core/test_approved_scenario_execution.py
git commit -m "feat: bind execute to an approved immutable scenario"
```

### Task 5: Add atomic materialization and validation certificates

**Files:**
- Create: `backend/app/contracts/planning/validation_certificate.py`
- Create: `backend/app/domain/materialization/atomic_commit.py`
- Modify: `backend/app/workflow/stages/execute.py`
- Modify: `backend/app/workflow/stages/validate.py`
- Modify: `backend/app/domain/validation/validate.py`
- Create: `backend/tests/core/test_atomic_execution_commit.py`
- Create: `backend/tests/core/test_validation_certificate.py`

**Interfaces:**
- Consumes: all worker results, approved execution input, PlannedState, and validation findings.
- Produces: either one committed PlannedState revision plus `ValidationCertificate`, or no committed revision plus diagnostics.

- [ ] **Step 1: Write atomicity tests**

```python
def test_worker_failure_does_not_commit_partial_planned_state(fake_store, execution_batch) -> None:
    execution_batch.worker_results[1].status = "failed"
    result = commit_execution_batch(fake_store, execution_batch)
    assert result.status == "failed"
    assert fake_store.named_ref("planned_state") is None


def test_successful_batch_commits_once(fake_store, execution_batch) -> None:
    result = commit_execution_batch(fake_store, execution_batch)
    assert result.status == "committed"
    assert fake_store.write_count("planned_state") == 1
```

- [ ] **Step 2: Implement an in-memory execution batch before persistence**

Use:

```python
@dataclass
class ExecutionBatch:
    approved_input: ApprovedExecutionInput
    worker_results: list[WorkerResult]
    parcel_changes: list[ParcelChange]
    diagnostics: list[str]
```

`commit_execution_batch` validates worker success, selected-to-materialized target coverage, duplicate feature IDs, scenario fingerprints, and bundle/evidence digests before calling the artifact-store write once.

- [ ] **Step 3: Define ValidationCertificate**

Use:

```python
class ValidationCertificate(ContractMeta):
    schema_version: Literal["1.0"] = "1.0"
    run_id: str = Field(min_length=1)
    scenario_set_fingerprint: str = Field(min_length=64, max_length=64)
    scenario_fingerprint: str = Field(min_length=64, max_length=64)
    planned_state_fingerprint: str = Field(min_length=64, max_length=64)
    evidence_snapshot_digest: str = ""
    bundle_snapshot_digest: str = ""
    hard_constraint_violation_count: int = Field(ge=0)
    unresolved_hard_constraint_count: int = Field(ge=0)
    selected_target_count: int = Field(ge=0)
    materialized_target_count: int = Field(ge=0)
    lineage_complete: bool
    status: Literal["passed", "partial", "failed"]
    finding_ids: list[str] = Field(default_factory=list)
```

The validator must reject `status="passed"` unless both hard counts are zero, selected and materialized counts match, and `lineage_complete` is true.

- [ ] **Step 4: Persist and route from the certificate**

VALIDATE persists `validation_certificate` alongside the detailed ValidationReport. Routing to RECONCILE requires `certificate.status == "passed"`; partial/failed certificates follow typed repair or human-review routes.

- [ ] **Step 5: Run materialization and validation tests**

```powershell
cd backend
pytest -q -o addopts='' tests/core/test_atomic_execution_commit.py tests/core/test_validation_certificate.py tests/core/test_validation_lineage_compile.py tests/core/test_validation_producer_lineage.py tests/core/test_validate_iteration_feedback.py
```

Expected: PASS.

- [ ] **Step 6: Commit atomic execution and certificates**

```powershell
git add backend/app/contracts/planning/validation_certificate.py backend/app/domain/materialization/atomic_commit.py backend/app/workflow/stages/execute.py backend/app/workflow/stages/validate.py backend/app/domain/validation/validate.py backend/tests/core/test_atomic_execution_commit.py backend/tests/core/test_validation_certificate.py
git commit -m "feat: validate and commit execution atomically"
```

### Task 6: Add planning benchmarks and retire the old selection engine

**Files:**
- Create: `backend/tests/fixtures/planning_benchmark/problems.json`
- Create: `backend/tests/characterization/test_planning_benchmark.py`
- Modify: `backend/tests/acceptance/test_select_execute_grounding_e2e.py`
- Modify: `backend/tests/acceptance/test_complete_execution_render.py`
- Remove after call-site proof: `backend/app/domain/allocation/select_service.py` winner-selection branches superseded by `candidate_preparation.py` and `scenario_projection.py`
- Modify: `docs/design/04_EVALUATION_AND_ACCEPTANCE.md`
- Modify: `docs/design/05_MIGRATION.md`

**Interfaces:**
- Consumes: benchmark grounded problems with expected feasible/infeasible status and acceptable candidate sets.
- Produces: scenario feasibility, hard-constraint, diversity, materialization, and replay metrics.

- [ ] **Step 1: Add at least 15 benchmark problems**

Cover:

```text
choose-one facility
all-members source collection
exclusive polygon overlap
hard distance constraint
soft distance preference
network capacity
candidate-only geometry
missing geometry
infeasible hard conflict
multiple Pareto alternatives
deterministic tie
source snapshot mismatch
execution worker failure
validation repair
resume/replay
```

- [ ] **Step 2: Add benchmark assertions**

```python
assert metrics["hard_constraint_violation_count"] == 0
assert metrics["infeasible_classification_accuracy"] == 1.0
assert metrics["selected_to_materialized_coverage"] == 1.0
assert metrics["lineage_completeness"] == 1.0
assert metrics["replay_fingerprint_stability"] == 1.0
assert metrics["alternative_case_mean_scenario_count"] >= 2.0
```

- [ ] **Step 3: Prove old winner-selection code is unused**

Run:

```powershell
rg -n "select_aggregate\(|_select_project|_select_facility|selected_score=" backend/app backend/tests --glob '*.py'
```

Expected: only an explicitly marked compatibility test may call `select_aggregate`; workflow and new acceptance tests do not.

- [ ] **Step 4: Remove superseded winner-selection branches**

Delete only functions whose behavior is now owned by `CpSatScenarioOptimizer` or `scenario_projection.py`. Preserve reusable suitability, candidate, service-area, and source-binding calculations by moving them to `candidate_preparation.py` before deletion.

- [ ] **Step 5: Run the planning acceptance suite**

```powershell
cd backend
pytest -q -o addopts='' tests/contracts/test_scenario_set_contracts.py tests/core/test_cp_sat_scenario_optimizer.py tests/core/test_select_scenario_authority.py tests/core/test_approved_scenario_execution.py tests/core/test_atomic_execution_commit.py tests/core/test_validation_certificate.py tests/characterization/test_planning_benchmark.py tests/acceptance/test_select_execute_grounding_e2e.py tests/acceptance/test_complete_execution_render.py
```

Expected: PASS.

- [ ] **Step 6: Record evidence and commit the retirement**

Update `docs/design/05_MIGRATION.md` with the exact test command, measured scenario counts, solver certificate statuses, and removed call sites.

```powershell
git add backend/app/domain/allocation backend/tests/fixtures/planning_benchmark backend/tests/characterization/test_planning_benchmark.py backend/tests/acceptance/test_select_execute_grounding_e2e.py backend/tests/acceptance/test_complete_execution_render.py docs/design/04_EVALUATION_AND_ACCEPTANCE.md docs/design/05_MIGRATION.md
git commit -m "refactor: retire duplicate winner selection path"
```

### Task 7: Run full convergence verification

**Files:**
- Verify: contracts, evidence-to-ground lineage, SELECT, EXECUTE, VALIDATE, RECONCILE, DELIVER, and documentation.

**Interfaces:**
- Consumes: all implementation tasks.
- Produces: a final acceptance result and stable migration status.

- [ ] **Step 1: Run contract and core tests**

```powershell
cd backend
pytest -q -o addopts='' tests/contracts tests/core
```

Expected: PASS.

- [ ] **Step 2: Run focused acceptance and characterization tests**

```powershell
pytest -q -o addopts='' tests/characterization/test_planning_benchmark.py tests/characterization/test_evidence_benchmark.py tests/acceptance/test_select_execute_grounding_e2e.py tests/acceptance/test_complete_execution_render.py tests/acceptance/test_real_evidence_http.py tests/acceptance/test_real_spatial_stage_chain.py
```

Expected: PASS; provider-dependent skips are recorded separately and are not counted as acceptance.

- [ ] **Step 3: Verify one authoritative selection path**

```powershell
cd ..
rg -n "solve_scenario\(|solve\(" backend/app/workflow/stages/select.py backend/app/domain/allocation --glob '*.py'
rg -n "SiteSelectionDecision" backend/app/workflow/stages/execute.py
```

Expected: SELECT calls one `ScenarioOptimizer`; EXECUTE does not use `SiteSelectionDecision` to choose geometry.

- [ ] **Step 4: Verify artifact and documentation consistency**

```powershell
rg -n "scenario_set|approved_execution|validation_certificate" backend/app/workflow/stage_adapter.py docs/design docs/architecture --glob '*.py' --glob '*.md'
git diff --check -- backend/app backend/tests docs/design docs/architecture
```

Expected: all three artifacts are registered and documented; no whitespace errors.

- [ ] **Step 5: Commit final verification repairs if needed**

```powershell
git add backend/app backend/tests docs/design docs/architecture
git commit -m "test: verify planning execution convergence"
```
