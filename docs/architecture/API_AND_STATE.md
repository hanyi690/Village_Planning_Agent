# API and State

> Status: CURRENT
> Authority: Current HTTP, SSE, and workflow-state ownership map. Field-level contracts live in generated schema and Pydantic models.

## 1. External contract owners

The current field-level API contracts are:

- OpenAPI: [`docs/contracts/openapi-v1.json`](../contracts/openapi-v1.json)
- SSE schema: [`docs/contracts/sse-events-v1.schema.json`](../contracts/sse-events-v1.schema.json)

FastAPI route aggregation lives in [`backend/app/api/routes.py`](../../backend/app/api/routes.py) and [`backend/app/api/v1/routes/__init__.py`](../../backend/app/api/v1/routes/__init__.py). This document does not duplicate endpoint tables; it points to the generated contract and the owning route modules.

## 2. Application boundary in the current code

Current API routes fan into three application layers:

- `backend/app/application/commands/` for create, resume, and human-decision writes
- `backend/app/application/queries/` for state, artifacts, delivery, evidence, history, and layers
- `backend/app/application/projections/` for response shaping

[`PlanningRuntimeService`](../../backend/app/infrastructure/runtime/planning_runtime_service.py) remains the runtime entry for session execution and resume.

For target ownership rules and projection invariants, use:

- [`../design/01_CONTRACTS_AND_INVARIANTS.md`](../design/01_CONTRACTS_AND_INVARIANTS.md)
- [`../design/02_EVIDENCE_AND_GROUNDING.md`](../design/02_EVIDENCE_AND_GROUNDING.md)
- [`../design/03_PLANNING_EXECUTION.md`](../design/03_PLANNING_EXECUTION.md)

## 3. SSE and persisted event ownership

Internal event vocabulary is declared in [`backend/app/contracts/events.py`](../../backend/app/contracts/events.py). Current persistence and publication are separated:

- repository: [`backend/app/infrastructure/events/repository.py`](../../backend/app/infrastructure/events/repository.py)
- live SSE publisher: [`backend/app/infrastructure/events/sse_publisher.py`](../../backend/app/infrastructure/events/sse_publisher.py)

The route layer projects those events outward; it is not the source of truth for event semantics.

## 4. Workflow state versus typed artifacts

[`backend/app/workflow/state.py`](../../backend/app/workflow/state.py) defines `WorkflowState` as control-plane state. It currently carries:

- stage and routing fields
- interrupt and terminal references
- lightweight runtime projections such as `delivery_status`
- typed `artifact_refs`
- diagnostics and reducer-managed control metadata

Current business artifacts should stay out of free-form state and be persisted by ref. In the current worktree that already includes `scoped_grounding_problem`, `ScenarioSet`, `approved_execution_input`, `execution_plan`, and `validation_certificate`.

The semantic owner and lifecycle rules for those artifacts are defined in the canonical design docs, especially [`../design/03_PLANNING_EXECUTION.md`](../design/03_PLANNING_EXECUTION.md) and [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md).

## 5. Resume and human-review operations

Human review remains a first-class runtime path:

- commands are issued from `backend/app/application/commands/`
- interrupt expectations are checked in [`PlanningRuntimeService.resume_from_interrupt`](../../backend/app/infrastructure/runtime/planning_runtime_service.py)
- HITL routing is compiled into the `hitl` segment in the workflow graph

Current SELECT-scoped deferral and approval flow uses `DeferralLedger`, scoped problem regeneration, fresh `ScenarioSet` derivation, and new approval artifacts rather than mutating an old approved input in place.

## 6. Delivery and layer projections

Current outward delivery/layer views are shaped from typed artifacts in:

- [`backend/app/application/projections/delivery.py`](../../backend/app/application/projections/delivery.py)
- [`backend/app/api/v1/routes/map_layers.py`](../../backend/app/api/v1/routes/map_layers.py)
- [`backend/app/api/v1/routes/source_layers.py`](../../backend/app/api/v1/routes/source_layers.py)

The runtime exposes `delivery_status` and `statutory_complete` through API contracts. `/map-layers` is the current session delivery projection. `/source-layers` is a read-only source-context projection and is not a planning-result endpoint.

## 7. Verification entry points

Useful current checks are:

```powershell
rg -n "include_router" backend/app/api backend/app/main.py -g '*.py'
python -m pytest backend/tests/contracts/test_documentation_convergence.py -q
```

When the API shape changes, regenerate and compare the schema; do not hand-edit `docs/contracts/openapi-v1.json`.
