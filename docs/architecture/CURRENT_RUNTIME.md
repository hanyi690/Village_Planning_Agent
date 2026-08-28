# Current Runtime

> Status: CURRENT
> Authority: Evidence-backed map of behavior present in this worktree. Target architecture belongs in `../design/00_SYSTEM_DESIGN.md` through `05_MIGRATION.md`.

## 1. Runtime composition observed in code

FastAPI is created in [`backend/app/main.py`](../../backend/app/main.py), with lifespan wiring in [`backend/app/bootstrap/lifespan.py`](../../backend/app/bootstrap/lifespan.py) and dependency composition in [`backend/app/bootstrap/composition.py`](../../backend/app/bootstrap/composition.py). The API runtime entry is [`PlanningRuntimeService`](../../backend/app/infrastructure/runtime/planning_runtime_service.py).

The root workflow is built in [`backend/app/workflow/root_graph.py`](../../backend/app/workflow/root_graph.py) and segmented in [`backend/app/workflow/segments.py`](../../backend/app/workflow/segments.py) into:

- `intent_loop`
- `cognitive`
- `spatial_chain`
- `hitl`

The current spatial sequence compiled into the graph is:

```text
TARGET_PROJECTION → GROUND → SELECT → EXECUTE → VALIDATE → RECONCILE → DELIVER
```

Repair routing is also present in code: SELECT can return to GROUND, and VALIDATE can route back toward EXECUTE, SELECT, GROUND, TARGET_PROJECTION, or L3 depending on the failure artifact carried by the state.

## 2. Current L1, retrieval, and context boundaries

Observed implementation anchors:

- [`backend/app/modules/l1/retrieval.py`](../../backend/app/modules/l1/retrieval.py) builds the L1 source index from session-owned `village_data` and explicit uploads.
- [`backend/app/modules/l1/context.py`](../../backend/app/modules/l1/context.py) runs bounded observe/validate/report passes per L1 dimension.
- [`backend/app/infrastructure/context_runtime/projection_builder.py`](../../backend/app/infrastructure/context_runtime/projection_builder.py) builds `ProjectCognitionSnapshot` and prompt-safe evidence projections.
- [`backend/app/infrastructure/evidence_runtime/facade.py`](../../backend/app/infrastructure/evidence_runtime/facade.py) and [`backend/app/infrastructure/evidence_runtime/retriever_router.py`](../../backend/app/infrastructure/evidence_runtime/retriever_router.py) route retrieval across `LOCAL_TEXT`, `REPORT`, `RAG`, `KG`, `BUNDLE`, `ARTIFACT`, `INTEGRITY`, and `EXTERNAL`.
- [`backend/app/workflow/conversation/edges.py`](../../backend/app/workflow/conversation/edges.py) still contains gate-scoped evidence retrieval wiring, including `retrieve_evidence_for_gate`.

What this proves today:

- the code has real cognition-digest and bounded-evidence projection hooks;
- the code has multiple typed requirement producers and a shared retrieval service;
- dense RAG is optional rather than required for all evidence calls.

What it does not prove:

- every production evidence call in every stage is already routed through one unified admission path;
- every prompt in every stage already carries the same named projection contract;
- every retriever and call site has fresh runtime verification in the current worktree.

Those limits remain `PARTIAL` and are tracked only in [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md).

### 2.1 Current L1/L2/L3 model-call shape

The current worktree separates semantic and report calls, but the semantic transaction size differs substantially by layer:

| Layer | Current semantic call | Current post-call behavior |
|---|---|---|
| L1 | `l1.observe` processes a bounded source page and returns an observation array through `L1ObservationProviderOutput`. | Local code validates source quotes, compiles typed observations/facts, then makes a separate structured `l1.report` call. Observe pages and report share the dimension call cursor/budget. |
| L2 | One `l2.decision` call returns a complete strict `L2DecisionSet` containing objectives, metrics, strategies, priorities, spatial structures, conflicts, evidence gaps and their cross-references. | Closed-set errors can trigger one complete decision-set reask, followed by a separate structured `l2.report` call. Same-layer decision context accumulates along the four L2 wave dimensions. |
| L3 | One `l3.claims` call returns a small provider envelope of rough, non-executable intent claims: family, statement, role, closed refs, location hints, grounding requirements and uncertainty. | Local code closes refs against the YAML vocabulary and L1 fact catalog, converts claims deterministically, records an empty/pending evidence state when needed, and builds display text deterministically from validated claims. There is no second provider summary call. Detailed planning remains downstream of `ScenarioSet`. |

The dependency renderer removes raw/report/audit keys and has consumer-specific decision/claim table projections with cross-dependency merge. L3 receives one canonical typed L1 fact table plus a bounded evidence projection; packet candidate/relation rows stay in the retrieval/grounding plane. `context_runtime/manager.py` owns context construction and `context_runtime/table_renderer.py` owns the bounded table wire format. Context trimming is scoped to the current run input; prior session checkpoints are not evidence sources.

`LLMManager` admits calls using the initial message character count and records safe call metadata. Explicit schema retry counts now pass through unchanged; worker-level semantic reasks and workflow-level dimension retries remain separate additional retry layers and still need item-level amplification accounting.

### 2.2 Current fresh-run evidence

The current fresh session `explore_kgenrich_28748410` was created from the current
金田村 input and rebuilt its session KG with 35,511 triples. It completed all 12
L1 dimensions, persisted and validated `L1Snapshot`, then completed all four L2
dimensions and persisted `L2Strategy`. Its L2 gate correctly returned `EXPLORE`.

The first EXPLORE dispatch exposed a facade import error before retrieval ran; the
run was stopped before repeating provider calls. The public
`gate_evidence_digest` boundary and the workflow import were then corrected. A
bounded current-session production retrieval subsequently queried
`local_text/report/kg/bundle/artifact`, returned two results with
`source_exhausted`, and preserved unresolved requirements plus the gap-loop trace.
No prior session checkpoint or history record was used as business input.

## 3. Current planning and execution artifacts observed in code

Current typed artifacts are present and wired into workflow state by ref:

- `PlanningProgram` / L3 contracts in [`backend/app/contracts/l3/l3_contracts.py`](../../backend/app/contracts/l3/l3_contracts.py)
- `IntentCompilationResult` in TARGET_PROJECTION under [`backend/app/modules/target_projection/stage.py`](../../backend/app/modules/target_projection/stage.py)
- [`GroundedPlanningProblem`](../../backend/app/contracts/ground/grounded_problem.py)
- [`ScenarioSet`](../../backend/app/contracts/select/scenario.py)
- [`ApprovedExecutionInput`](../../backend/app/contracts/select/approval.py)
- `ExecutionPlan` and execution result contracts in [`backend/app/contracts/execute/execution_plan_contracts.py`](../../backend/app/contracts/execute/execution_plan_contracts.py)
- [`ValidationCertificate`](../../backend/app/contracts/validation/validation_certificate_contracts.py)

Observed stage boundaries:

- GROUND persists typed grounding/problem artifacts and carries unresolved/deferred findings forward.
- SELECT persists a `ScenarioSet`, can persist an approval-bound `ExecutionPlan`, and derives [`ApprovedExecutionInput`](../../backend/app/contracts/select/approval.py) for executable paths.
- EXECUTE refuses to proceed when approval, scenario lineage, or plan digest does not match.
- VALIDATE and RECONCILE read typed artifacts back by ref instead of recomputing authority from free-form state.
- DELIVER publishes `delivery_status` and `statutory_complete` from the final manifest path.

The current code is stricter than the older compatibility paths, but the end-to-end surface is still only partially verified for all target types and solver backends.

## 4. State and delivery behavior observed in code

[`backend/app/workflow/state.py`](../../backend/app/workflow/state.py) keeps `WorkflowState` as a control-plane object with stage, routing, diagnostics, lightweight runtime fields, and artifact refs. Typed runtime products such as `scoped_grounding_problem`, `ScenarioSet`, [`ApprovedExecutionInput`](../../backend/app/contracts/select/approval.py), and [`ValidationCertificate`](../../backend/app/contracts/validation/validation_certificate_contracts.py) are persisted separately and referenced from state.

Current delivery-facing status fields are visible in:

- [`backend/app/api/v1/contracts.py`](../../backend/app/api/v1/contracts.py)
- [`backend/app/workflow/terminal.py`](../../backend/app/workflow/terminal.py)
- [`backend/app/workflow/runtime_adapter.py`](../../backend/app/workflow/runtime_adapter.py)
- [`backend/app/workflow/delivery/aggregate.py`](../../backend/app/workflow/delivery/aggregate.py)

The runtime currently distinguishes `complete`, `partial`, and `diagnostic_only` delivery outcomes. `statutory_complete` is carried explicitly and is not inferred from stage completion alone.

## 5. Real-run evidence kept as evidence, not as target claims

The current fresh-run evidence is intentionally limited to the latest run and its
bounded runtime follow-up. It proves that L1/L2 artifacts can be produced and
reloaded through the current architecture, and that an unresolved L2 gate can be
converted into bounded evidence retrieval. It does not prove L3 or downstream
completion; those stages remain unverified until the current evidence gaps close.

## 6. Explicit current partial boundaries

The current worktree still has evidence-backed limits:

- dense recall depends on configured embedding infrastructure and can be unavailable without disabling the whole workflow;
- cognition and prompt-boundary hooks exist, but not every retrieval or LLM call path has fresh proof of uniform enforcement;
- current grounding and solver paths are stronger for parcel-style bounded scenarios than for all road, coverage, topology, and mixed-worker cases;
- approval-bound execution is enforced in code, but full execution-surface verification remains narrower than the target design;
- delivery can truthfully emit `partial`, so successful stage progression must not be read as whole-village completion.

The status words for those limits belong in [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md), not here.

## 7. Compatibility boundaries still visible in code

The old single-scenario solver is no longer a production entry point. The active
execution boundary is the typed `staging ChangeSet`: EXECUTE treats duplicates,
omissions, and unexpected outputs as commit blockers instead of converting them
into a partial formal result.

For target rules and normative boundaries, use the canonical design set in
`docs/design/`. This file stays limited to current code evidence and current-run
evidence.
