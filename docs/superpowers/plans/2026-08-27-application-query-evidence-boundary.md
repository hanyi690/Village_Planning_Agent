# Application Query Evidence Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Separate application read projections from evidence retrieval context hydration and external search provider lifecycle.

**Architecture:** Keep artifact, workflow-state, delivery, map-layer, review, and event queries in `application/queries`. Move evidence artifact reads into a narrow application query module, move context hydration into `evidence/retrieval`, and move external provider state into `infrastructure/search`. `evidence_service.retrieve_evidence` remains the only retrieval orchestrator.

**Tech Stack:** Python 3.12+, FastAPI, Pydantic, LangGraph runtime, pytest.

## Global Constraints

- Preserve existing uncommitted user changes.
- Keep LF line endings and 4-space Python indentation.
- Do not expose provider secrets.
- Maintain compatibility only where an existing production caller still requires it.

---

### Task 1: Establish the new search-provider registry

**Files:**
- Create: `backend/app/infrastructure/search/provider_registry.py`
- Modify: `backend/app/infrastructure/search/__init__.py`
- Test: `backend/tests/core/test_external_search_provider_registry.py`

- [ ] Add a registry with `configure_external_provider`, `get_active_external_provider`, and `close_external_provider`.
- [ ] Move the existing provider state semantics from `application/queries/evidence.py` without changing provider object behavior.
- [ ] Add tests for configure, read, replacement, and close/reset.
- [ ] Run `python -m pytest backend/tests/core/test_external_search_provider_registry.py -q`.

### Task 2: Split application evidence artifact reads from retrieval hydration

**Files:**
- Create: `backend/app/application/queries/evidence_artifacts.py`
- Modify: `backend/app/application/queries/evidence.py`
- Modify: `backend/app/application/queries/__init__.py`
- Test: `backend/tests/core/test_evidence_query_boundary.py`

- [ ] Move only durable evidence-artifact read helpers into `evidence_artifacts.py`.
- [ ] Remove provider globals and provider lifecycle functions from `application/queries/evidence.py`.
- [ ] Keep a temporary compatibility import only if existing callers require it, implemented as a direct re-export from infrastructure.
- [ ] Add tests proving application query imports do not initialize retrieval or provider runtime.
- [ ] Run the focused boundary tests.

### Task 3: Move retrieval context hydration behind the evidence retrieval boundary

**Files:**
- Create: `backend/app/evidence/retrieval/context_hydration.py`
- Modify: `backend/app/evidence/retrieval/evidence_service.py`
- Modify: `backend/app/infrastructure/llm/dimension_runtime.py`
- Modify: `backend/app/infrastructure/llm/tools/access/evidence.py`
- Modify: `backend/app/infrastructure/context/planning_context_factory.py`
- Tests: existing evidence retrieval and LLM evidence tests plus `backend/tests/core/test_evidence_query_boundary.py`

- [ ] Move `hydrate_evidence_context`, `hydrate_source_semantic_context`, and `prepare_evidence_context` implementation to the retrieval context module, preserving signatures.
- [ ] Update callers to import the new retrieval context module or the single `evidence_service` facade.
- [ ] Ensure hydration may read application/runtime ports but does not import `application.queries.evidence`.
- [ ] Keep `retrieve_evidence` as the only function that plans, routes, invokes retrievers, evaluates sufficiency, and assembles the result.
- [ ] Run focused evidence and LLM tests.

### Task 4: Rewire bootstrap and API callers

**Files:**
- Modify: `backend/app/bootstrap/lifespan.py`
- Modify: `backend/app/api/v1/routes/evidence.py`
- Modify: `backend/app/evidence/retrieval/evidence_service.py`
- Tests: `backend/tests/core/test_evidence_query_api.py` and import checks

- [ ] Configure and close external providers through `infrastructure.search.provider_registry`.
- [ ] Make the API route call `evidence_service.retrieve_evidence` directly for retrieval.
- [ ] Remove any route-level dependence on application evidence orchestration.
- [ ] Run `python -m pytest --collect-only -q` and the focused API tests.

### Task 5: Remove the reverse retrieval-to-application-evidence dependency

**Files:**
- Modify: all remaining files found by `rg -n "application\.queries\.evidence" backend/app`
- Modify: `backend/app/application/queries/__init__.py`
- Test: `backend/tests/core/test_stable_api_architecture.py`

- [ ] Confirm no `evidence/retrieval` module imports `application.queries.evidence`.
- [ ] Retain only application read-side projections in `application/queries`.
- [ ] Add an architectural assertion for the forbidden dependency direction.
- [ ] Run import checks, focused tests, and the default test collection.

### Task 6: Verify and document the boundary

**Files:**
- Modify: `backend/app/application/README.md`
- Modify: `backend/app/evidence/README.md`
- Modify: `backend/app/infrastructure/README.md`

- [ ] Document the new ownership of evidence artifact reads, retrieval hydration, and provider lifecycle.
- [ ] Run `python -m compileall -q backend/app`.
- [ ] Run frontend-independent backend checks available in the repository.
- [ ] Report any remaining failures separately from this refactor.
