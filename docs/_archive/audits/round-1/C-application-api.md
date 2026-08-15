# Audit C: Application & API Layer (Blueprint M9)

**Scope:** `backend/app/application/` (additive) + `backend/app/api/v1/` (additive).
**Status:** Complete. Import verification passes.

## Files created

### Application queries (thin, injected read models; no FastAPI/Runtime imports)
- `app/application/queries/human_review.py`
- `app/application/queries/delivery.py`
- `app/application/queries/map_layers.py`

### Application commands
- `app/application/commands/resume_checkpoint.py`
- `app/application/commands/submit_human_decision.py`

### API transport (split `routes/` package + dependencies)
- `app/api/v1/dependencies.py`
- `app/api/v1/routes/__init__.py`
- `app/api/v1/routes/{sessions,state,events,human_review,delivery,map_layers,artifacts}.py`

## Query signatures
- `get_human_review(session_id, *, review_store: ReviewStorePort) -> dict` — `{event_id, paused_stage, items}` (+ pending/session_id).
- `get_delivery_projection(session_id, *, artifact_store: ArtifactStorePort) -> dict` — `{delivery_status, deferral_summary, manifest_ref}` (+ available/downloads).
- `get_map_layer_collection(session_id, *, snapshot_store: SnapshotStorePort) -> dict` — `{layers: [...]}`.

## Command signatures
- `ResumeCheckpointService.execute(ResumeCheckpointCommand) -> ResumeCheckpointResult` — builds a
  `ResumePlan` from a `CheckpointCursor` (values + next_nodes + pending_interrupt) via `build_resume_plan`.
  No LangGraph call. `ResumePlan` imported from canonical `app.modules.schema.contracts.resume_contracts`
  (the `app.contracts.workflow.resume` path triggers a **pre-existing** circular import in
  `app/contracts/workflow/repair.py` ↔ `app/evidence/model/relation_evidence.py`; outside scope to fix).
- `submit_human_decision(session_id, *, event_id, action, decisions)` — re-exports the existing
  CAS `SubmitHumanDecisionService` (validates event_id against active interrupt, then forwards).

## Routes package layout
- `routes/sessions.py`: POST `/api/v1/sessions` (+ resume, handler defined in `routes/__init__.py`
  so existing tests that monkeypatch `routes.resume_workflow_service` keep working).
- `routes/{state,events,human_review,delivery,map_layers,artifacts}.py`: per-resource routers.
- `routes/human_review.py`: also re-exports `resolve_human_review`/`ResolveRequest` from the legacy
  `app/api/human_review_routes.py` (not mounted — it reads Runtime directly, violating M9).
- `routes/__init__.py`: aggregates `router` and re-exports the full flat import surface
  (`stream_events`, `run_event_queries`, `resume_workflow_service`, handlers, services).
- `dependencies.py`: protocol-typed `get_planning_runtime()` (lazy adapter, no direct Runtime import).

## Important note
The `routes/` package **shadows** `app/api/v1/routes.py` (Python resolves the package first), so the
flat `routes.py` is now dead-but-present (not deleted). Handlers were relocated into the package
without logic changes; the flat file stays for the source-reading AST test. The aggregate router's
OpenAPI is byte-identical to the flat router.

## Import verification
`python -c "import app.application.queries.human_review; import app.application.queries.delivery;
import app.application.queries.map_layers; import app.application.commands.resume_checkpoint;
import app.application.commands.submit_human_decision; import app.api.v1.dependencies; print('OK')"`
→ `OK`. `app.main` imports cleanly. `tests/core`: 155/156 pass — the single failure
(`test_openapi_v1_snapshot_is_current`) is pre-existing (stale snapshot; flat router also mismatches).
