# Operations

> Status: CURRENT
> Authority: Current local startup, configuration categories, degraded-operation expectations, and verification entry points.

## 1. Local startup path

The shortest documented local startup remains:

```powershell
pip install -r requirements.txt
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The frontend is started from `frontend/` via its package manifest. Health endpoints remain `/health` and `/api/health`, with exact response fields defined by code and generated schema rather than by this document.

FastAPI startup wiring is owned by [`backend/app/bootstrap/lifespan.py`](../../backend/app/bootstrap/lifespan.py) and [`backend/app/bootstrap/composition.py`](../../backend/app/bootstrap/composition.py).

## 2. Configuration categories actually in play

Current configuration responsibilities are split across:

- application/API settings
- persistence and checkpoint stores
- LLM provider settings
- dense RAG/embedding settings
- evidence and external-search settings
- spatial/KG/data-snapshot settings
- workflow retry, HITL, validation, and replay budgets

The source of truth is the current settings and composition code, primarily [`backend/app/core/settings.py`](../../backend/app/core/settings.py), `backend/app/config/`, and the bootstrap layer. This document intentionally does not duplicate secret names or complete env-var inventories.

## 3. Degraded operation that the current runtime is expected to handle

Current behavior should distinguish channel-specific degradation rather than collapsing the whole workflow:

| Failure | Current expected behavior |
|---|---|
| embedding or professional RAG unavailable | continue local text, report, KG, bundle, artifact, and history retrieval where available; expose the missing dense channel honestly |
| external search unavailable | keep local/project evidence paths and surface the missing external coverage |
| KG unavailable | keep bundle- and artifact-backed retrieval where possible; do not invent geometry or identity from names alone |
| bundle or snapshot unavailable | stop executable grounding rather than deriving geometry from reports |
| solver timeout or bounded failure | return bounded diagnostic output, not a fake optimal decision |
| worker failure | abort formal commit and preserve diagnostics |
| validation failure | route back to the responsible stage or human review instead of mutating the validated result in place |

Current dense-RAG ownership is in [`backend/app/infrastructure/rag/service.py`](../../backend/app/infrastructure/rag/service.py) and [`vector_store.py`](../../backend/app/infrastructure/rag/vector_store.py). Current retrieval fallbacks live under [`backend/app/evidence/retrieval/`](../../backend/app/evidence/retrieval/).

## 4. LLM failure handling now worth monitoring

The runtime still needs to distinguish structured-call failures such as:

- context overflow
- output truncation
- missing tool call
- schema invalid
- timeout

The current worktree keeps those as typed diagnostics and avoids storing raw provider prompt/response text in logs, SSE, or workflow state. The normative boundary for what LLM calls may see belongs in [`../adr/008-final-llm-context-evidence-boundary.md`](../adr/008-final-llm-context-evidence-boundary.md); the current migration status of that boundary belongs in [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md).

## 5. Verification commands used in practice

Quick contract/core verification:

```powershell
python -m pytest backend/tests/contracts backend/tests/core -q
```

Focused documentation convergence check:

```powershell
python -m pytest backend/tests/contracts/test_documentation_convergence.py -q
```

Patch hygiene:

```powershell
git diff --check
```

Passing these checks proves only their own scope. Release-level target acceptance stays defined in [`../design/04_EVALUATION_AND_ACCEPTANCE.md`](../design/04_EVALUATION_AND_ACCEPTANCE.md).

## 6. Operational release reminder

Before treating a build as operationally ready, verify at least:

- generated API contracts still match code
- degraded retrieval paths fail honestly
- checkpoint and resume remain usable
- artifact lineage remains queryable
- execution failures do not produce formal delivery

This file stays intentionally operational. Design intent and target acceptance criteria live in the canonical design set, not here.
