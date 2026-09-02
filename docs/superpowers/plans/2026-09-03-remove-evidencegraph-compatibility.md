# Remove Legacy EvidenceGraph Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete Bundle/BSM-centered `EvidenceGraph` compatibility boundary so the active Evidence, DATA, GROUND, and WM paths use the new typed acquisition, sufficiency, proposal, and opaque DATA-reference contracts only.

**Architecture:** Evidence remains the read-only business façade that produces `EvidencePacket` and cognition proposals. DATA remains the authority for admitted resources, representations, and geometry refs; WM remains the authority for cognition state and transaction commit. The old session graph, Bundle geometry enrichment, BSM-specific tools, and graph-backed GROUND fallback are removed rather than retained as migration shims.

**Tech Stack:** Python 3, FastAPI/LangGraph runtime, Pydantic contracts, pytest, git.

## Global Constraints

- Follow `docs/design/04_EVIDENCE.md`: `Observation → CandidateEvidence → ConflictSet → Coverage → Sufficiency → EvidencePacket/EvidenceGap/CognitionProposal`.
- Follow `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md` and `docs/design/08_COGNITIVE_WORLD_MODEL_MIGRATION.md`: DATA owns resource/representation/geometry authority; WM owns cognition and commit.
- Do not add compatibility behavior for removed `EvidenceGraph`, Bundle, or BSM interfaces.
- Do not let Evidence write WM directly; retain proposal handoff and the existing WM cognition transaction boundary.
- Preserve the current DATA catalog admission and `data_geometry_by_ref` path.
- Use `apply_patch` for edits and keep unrelated user changes untouched.

---

### Task 1: Lock the new boundary with audit tests

**Files:**
- Create: `tests/test_evidencegraph_removal.py`
- Test: existing Evidence and WM proposal tests discovered by `rg`

**Interfaces:**
- Consumes: `app.modules.evidence.application.retrieve_evidence`, the DATA geometry tool, and the access-tool registry.
- Produces: executable assertions that the removed graph/tool symbols are absent while the new Evidence/DATA path remains importable.

- [x] **Step 1: Write failing assertions**

  Assert that importing `app.infrastructure.evidence_runtime.evidence_graph` fails, that `query_evidence_graph` and `query_facility_bsms` are not registered access tools, and that `data_geometry_by_ref` remains registered. Assert that the Evidence application and WM proposal contracts import successfully.

- [x] **Step 2: Run the focused test**

  Run: `pytest -q tests/test_evidencegraph_removal.py`
  Expected: FAIL until the old module and exports are removed.

- [x] **Step 3: Keep the test focused on public architecture**

  Do not assert implementation details of the new sufficiency evaluator; existing EV-02 tests cover those semantics. The new test only prevents the deleted compatibility surface from silently returning.

### Task 2: Remove graph construction and Bundle enrichment from Evidence runtime

**Files:**
- Modify: `backend/app/infrastructure/context_runtime/manager.py`
- Modify: `backend/app/infrastructure/context_runtime/runtime.py`
- Modify: `backend/app/workflow/layers/context_bootstrap.py`
- Modify: `backend/app/infrastructure/evidence_runtime/source_semantic_runtime.py`
- Modify: `backend/app/infrastructure/evidence_runtime/facade.py`
- Delete: `backend/app/infrastructure/evidence_runtime/evidence_graph.py`
- Modify: `backend/app/infrastructure/evidence_runtime/__init__.py`

**Interfaces:**
- Consumes: typed context hydration, V2 DATA catalog/world-model ports, and canonical Evidence retrieval.
- Produces: no `context.evidence_graph` state and no graph-generated Bundle candidate enrichment; Evidence retrieval continues to return the packet/bundle/proposal objects already defined by EV-01/EV-02/EV-03.

- [x] **Step 1: Remove graph hydration and state fields**

  Delete graph construction, graph keys, `has_evidence_graph` summary fields, and bootstrap log/dedup logic. Keep L1 facts as typed context inputs for the canonical Evidence acquisition path.

- [x] **Step 2: Remove graph enrichment branches**

  Delete `_enrich_local_spatial_graph` and its call sites/imports. Remove graph-specific diagnostics and prompt rendering. Keep packet pagination and DATA opaque-ref instructions.

- [x] **Step 3: Delete the graph module and lazy export**

  Delete `evidence_graph.py` and remove its package export so no runtime import path can recreate it.

- [x] **Step 4: Run focused Evidence tests**

  Run: `pytest -q tests -k "evidence or sufficiency or proposal or cognition" --ignore=tests/test_data_change_set_boundary.py`
  Expected: new Evidence retrieval, sufficiency, proposal, and WM handoff tests pass; failures identify remaining graph assumptions.

### Task 3: Remove old graph/BSM LLM tools and update prompts

**Files:**
- Modify: `backend/app/infrastructure/llm/tools/access/evidence.py`
- Modify: `backend/app/infrastructure/llm/tools/access/__init__.py`
- Modify: `backend/app/infrastructure/llm/tools/access/README.md`
- Modify: `backend/app/workflow/conversation/node.py`
- Modify: relevant tool tests found by `rg`

**Interfaces:**
- Consumes: canonical Evidence retrieval and `data_geometry_by_ref`.
- Produces: one Evidence access contract plus DATA geometry inspection; no graph query or BSM-specific tool schema.

- [x] **Step 1: Delete `query_evidence_graph*` and `query_facility_bsms*`**

  Remove the functions, tool registration, metadata, exports, and BSM-shaped response fields. Retain shared pagination only if it is used by the remaining Evidence access tool; otherwise remove it as dead code.

- [x] **Step 2: Update agent instructions**

  Replace graph/BSM wording with EvidencePacket candidate refs, requirement-driven sufficiency, and DATA geometry refs. The prompt must not instruct the model to call a removed tool.

- [x] **Step 3: Run tool registry tests**

  Run: `pytest -q tests -k "tool or access or geometry_by_ref" --ignore=tests/test_data_change_set_boundary.py`
  Expected: DATA geometry access remains available and deleted names are absent.

### Task 4: Remove graph-backed GROUND compatibility and dead identity/index modules

**Files:**
- Delete: `backend/app/infrastructure/ground_runtime/compatibility.py`
- Modify: `backend/app/modules/ground/application.py`
- Modify: `backend/app/modules/ground/reference_resolution.py`
- Modify: `backend/app/modules/ground/stage.py`
- Modify: `backend/app/spatial/grounding/resolver.py`
- Modify: `backend/app/spatial/grounding/grounding.py`
- Modify: `backend/app/spatial/relations/reference_features.py`
- Delete only after import audit: `backend/app/infrastructure/evidence_runtime/index/place_evidence_index.py`, `backend/app/infrastructure/evidence_runtime/index/evidence_scorer.py`, `backend/app/infrastructure/evidence_runtime/index/resolution_coverage.py`, and graph-only model/store files.

**Interfaces:**
- Consumes: GROUND’s V2 catalog/world-model resolver and typed EvidencePacket refs.
- Produces: GROUND either resolves through the new catalog/WM path or returns a typed unresolved result; it never falls back to Bundle/BSM graph state.

- [x] **Step 1: Map every old adapter import**

  Confirm with `rg` that each deleted identity/index symbol has no surviving production or test caller. Do not delete a file while an active DATA/WM path still imports it.

- [x] **Step 2: Remove graph initialization and adapter imports**

  Delete legacy branches that construct `EvidenceGraph`, `BindingStore`, or `ObservationStore`. Use the existing V2 resolver inputs and preserve fail-closed unresolved outcomes where no typed candidate is available.

- [x] **Step 3: Remove dead graph/index code**

  Delete only files proven unreachable after the previous step. Remove comments and type references that describe the old boundary.

- [x] **Step 4: Run GROUND and relation tests**

  Run: `pytest -q tests -k "ground or grounding or relation or reference" --ignore=tests/test_data_change_set_boundary.py`
  Expected: V2 DATA/WM resolution behavior passes without graph compatibility imports.

### Task 5: Final design audit, verification, and commit

**Files:**
- Modify: `docs/design/04_EVIDENCE.md` only if its implementation inventory still names removed compatibility code.
- Modify: `docs/design/07_COGNITIVE_WORLD_MODEL_AND_DYNAMIC_GIS.md` only if it contains stale graph references.
- Modify: `docs/design/08_COGNITIVE_WORLD_MODEL_MIGRATION.md` only to distinguish historical migration text from active implementation, without restoring compatibility code.

**Interfaces:**
- Consumes: the complete repository after Tasks 1–4.
- Produces: a clean, tested branch and a commit describing removal of the obsolete EvidenceGraph boundary.

- [x] **Step 1: Search for forbidden active references**

  Run `rg -n "EvidenceGraph|query_evidence_graph|query_facility_bsms|Bundle geometry|feature_bsm|BindingStore|ObservationStore|PlaceEvidenceIndex" backend tests docs/design` and classify every remaining hit as removed, historical documentation, or a real active dependency. Remove real active dependencies.

- [x] **Step 2: Run verification**

  Run `python -m compileall -q backend`, focused tests, and `pytest -q tests --ignore=tests/test_data_change_set_boundary.py`.

- [x] **Step 3: Review the diff**

  Run `git diff --check`, `git status --short`, and inspect the staged diff for accidental changes to DATA admission, Evidence sufficiency, proposal compilation, or WM transaction code.

- [x] **Step 4: Commit**

  Run: `git add backend tests docs/superpowers/plans/2026-09-03-remove-evidencegraph-compatibility.md docs/design && git commit -m "refactor(evidence): remove legacy evidence graph boundary"`

## Self-review

- The design requirement “EvidenceGraph is absent from the new design” is covered by Tasks 2–5.
- The user requirement “do not retain historical compatibility” is covered by Tasks 2–4.
- The required DATA/WM behavior is protected by Tasks 1, 2, 4, and 5.
- EV-02 absence remains in the existing sufficiency evaluator; this plan does not move absence earlier or implement proposal-side WM writes.
