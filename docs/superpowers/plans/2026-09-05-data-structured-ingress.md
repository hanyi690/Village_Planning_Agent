# DATA Structured Ingress and LLM Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the real DATA upload ingress usable for explicitly typed current data while centralizing structured-output and reasoning protocol handling without weakening fail-closed handling for undeclared or contradictory inputs.

**Architecture:** The shared structured runtime owns provider response normalization, reasoning separation, bounded repeated calls, retries, failure classification, and audit metadata. DATA retains only temporal-role semantics and admission policy. An explicit upload channel such as `village_data -> current_evidence` is a typed admission declaration; LLM temporal classification becomes a bounded conflict/audit signal for typed uploads and remains the only possible positive classifier for unclassified uploads, which stay quarantined unless explicitly declared.

**Tech Stack:** Python 3, Pydantic v2, asyncio, Instructor/LangChain OpenAI-compatible adapters, pytest, FastAPI upload/session path.

## Global Constraints

- Do not infer semantic layer identity or temporal role from filenames, field names, or business attributes.
- Preserve fail-closed behavior for unclassified uploads, explicit planned outputs, parse failures, unresolved CRS, invalid geometry, unsupported media, and budget violations.
- Preserve raw provider reasoning as opaque continuation metadata only; it must never become DATA, WM, or Evidence facts.
- Preserve the existing `DataAdmissionReceipt` and immutable DATA artifact lineage.
- Preserve the existing MiniMax provider adapter path; provider-specific reasoning transport belongs in the shared runtime.
- Every code change must have a focused regression test before implementation and a full relevant test run after implementation.

---

### Task 1: Define the shared structured-call and reasoning result contract

**Files:**
- Create: `backend/app/infrastructure/structured_runtime/contracts.py`
- Modify: `backend/app/infrastructure/structured_runtime/__init__.py`
- Test: `tests/test_structured_runtime_contracts.py`

**Interfaces:**
- Produces immutable `StructuredPassResult` and `StructuredConsensusResult` models containing typed output, pass status, provider/model, finish reason, reasoning metadata, and failure metadata.
- Does not contain DATA role names or planning-domain semantics.

- [ ] **Step 1: Write the failing contract tests**

  Add tests that construct successful and failed pass results, assert frozen/strict validation, verify reasoning content is represented only by metadata/digest/length, and verify consensus results retain per-pass diagnostics without storing raw prompt content.

- [ ] **Step 2: Run the focused tests to verify failure**

  Run: `pytest -q tests/test_structured_runtime_contracts.py`

  Expected: FAIL because the shared contract module does not exist.

- [ ] **Step 3: Implement the contracts**

  Add strict Pydantic models with fields for `status`, `typed_output`, `provider_name`, `model_id`, `finish_reason`, `reasoning_present`, `reasoning_channel`, `reasoning_length`, `reasoning_digest`, `failure_code`, `failure_kind`, and safe scalar metadata. Add the models to the structured runtime exports.

- [ ] **Step 4: Run the focused tests to verify success**

  Run: `pytest -q tests/test_structured_runtime_contracts.py`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/infrastructure/structured_runtime/contracts.py backend/app/infrastructure/structured_runtime/__init__.py tests/test_structured_runtime_contracts.py
  git commit -m "feat(data): define shared structured call result contracts"
  ```

### Task 2: Centralize bounded repeated structured calls and reasoning normalization

**Files:**
- Create: `backend/app/infrastructure/structured_runtime/consensus.py`
- Modify: `backend/app/infrastructure/structured_runtime/parser.py`
- Modify: `backend/app/infrastructure/structured_runtime/facade.py`
- Modify: `backend/app/infrastructure/structured_runtime/__init__.py`
- Test: `tests/test_structured_runtime_consensus.py`

**Interfaces:**
- Produces `run_structured_consensus(spec, messages, passes=2, validator=None, ...) -> StructuredConsensusResult`.
- Calls the existing manager/parser boundary and never decides whether a DATA role is current or planned.

- [ ] **Step 1: Write the failing consensus tests**

  Add deterministic injected-LLM tests for: two valid typed passes; one provider failure; schema-invalid output; same role with different valid domain reason codes; and reasoning metadata normalization. Assert that provider failures and semantic disagreement are distinguishable.

- [ ] **Step 2: Run the focused tests to verify failure**

  Run: `pytest -q tests/test_structured_runtime_consensus.py`

  Expected: FAIL because `run_structured_consensus` does not exist.

- [ ] **Step 3: Implement the shared executor**

  Use the existing `run_structured`/manager call for each bounded pass. Capture safe per-pass status and `structured_failure_observation` data. Normalize provider reasoning into metadata and keep typed payload separate. Do not log raw reasoning or raw provider content. Return a consensus result even when one or more passes fail.

- [ ] **Step 4: Verify the focused tests**

  Run: `pytest -q tests/test_structured_runtime_consensus.py`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/infrastructure/structured_runtime backend/app/infrastructure/structured_runtime/consensus.py tests/test_structured_runtime_consensus.py
  git commit -m "feat(data): centralize structured consensus and reasoning handling"
  ```

### Task 3: Move temporal-role pass execution onto the shared runtime

**Files:**
- Modify: `backend/app/data/ingestion/temporal_role_classifier.py`
- Test: `tests/test_temporal_role_classifier.py`

**Interfaces:**
- Consumes `run_structured_consensus` from the shared runtime.
- Produces the existing `SourceTemporalRoleDecision`, enriched with deterministic pass diagnostics where the contract permits.
- Keeps role/reason compatibility and confidence policy in DATA.

- [ ] **Step 1: Add regression tests for role consensus semantics**

  Test that equal `selected_role` values with different valid reason codes are not rejected solely for textual reason mismatch; test that different roles remain ambiguous; test that provider failure remains provider failure; and test that unclassified input never gets upgraded by a weak or ambiguous result.

- [ ] **Step 2: Run the focused tests to verify failure**

  Run: `pytest -q tests/test_temporal_role_classifier.py`

  Expected: FAIL against the current exact role-plus-reason consensus implementation or missing shared executor integration.

- [ ] **Step 3: Refactor the classifier**

  Replace its local two-pass loop with the shared consensus runtime. Keep `_proposal_valid` as the DATA-level validator. Reduce consensus by role first, require each reason code to be valid for that role, and retain a canonical reason plus pass diagnostics. Do not use provider reasoning text as evidence.

- [ ] **Step 4: Run the focused tests**

  Run: `pytest -q tests/test_temporal_role_classifier.py tests/test_data_admission_mvp.py -k "temporal or classifier or upload"`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/data/ingestion/temporal_role_classifier.py tests/test_temporal_role_classifier.py
  git commit -m "refactor(data): use shared runtime for temporal role consensus"
  ```

### Task 4: Make the real typed upload ingress deterministic and observable

**Files:**
- Modify: `backend/app/data/ingestion/source_admission.py`
- Modify: `backend/app/data/ingestion/upload.py`
- Modify: `backend/app/contracts/data/temporal_role_contracts.py`
- Test: `tests/test_real_upload_ingress.py`

**Interfaces:**
- Consumes explicit `input_role` supplied by the typed session channel.
- Produces an admitted `DataAdmissionReceipt` for deterministic-current uploads when parse/CRS/geometry/policy checks pass, while retaining LLM audit metadata.

- [ ] **Step 1: Write the real-ingress regression tests**

  Exercise `process_uploaded_file` with an in-memory GeoJSON upload and explicit `input_role="current_evidence"`. Stub the temporal provider as ambiguous and assert the upload still reaches the DATA facade after deterministic checks. Add tests asserting role-less uploads remain quarantined and explicit planned-output uploads remain rejected. Assert `source_digest` is passed into the temporal profile.

- [ ] **Step 2: Run the focused tests to verify failure**

  Run: `pytest -q tests/test_real_upload_ingress.py`

  Expected: FAIL because ambiguous temporal classification currently forces quarantine and the upload call does not pass the content digest to the classifier.

- [ ] **Step 3: Implement the typed-channel policy**

  Preserve deterministic planned-output conflict rejection. For an explicit `current_evidence` or typed control channel, allow DATA admission to proceed when parse, budget, CRS, geometry, and capability checks pass; record temporal classifier status as audit metadata. For an unclassified upload, preserve quarantine. Pass `source_digest` from `process_uploaded_file` into `assess_uploaded_source_admission`.

- [ ] **Step 4: Run the focused tests**

  Run: `pytest -q tests/test_real_upload_ingress.py tests/test_data_admission_mvp.py tests/test_jintian_data_e2e_acceptance.py -k "upload or admission or repaired_surface or complete_p0"`

  Expected: PASS.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/data/ingestion/source_admission.py backend/app/data/ingestion/upload.py backend/app/contracts/data/temporal_role_contracts.py tests/test_real_upload_ingress.py
  git commit -m "fix(data): unblock explicitly typed real upload ingress"
  ```

### Task 5: Document the unified LLM boundary and run the full DATA acceptance gate

**Files:**
- Modify: `backend/app/infrastructure/structured_runtime/README.md`
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/superpowers/plans/2026-09-05-data-structured-ingress.md`
- Test: `tests/test_data_p1_p2_docs.py`

**Interfaces:**
- Documents the shared structured/reasoning boundary, typed upload policy, failure classes, and DATA/WM/Evidence consumption rule.

- [ ] **Step 1: Add documentation assertions**

  Assert the design docs mention `StructuredConsensusRuntime`, provider reasoning normalization, explicit upload intent, provider failure versus semantic disagreement, and the rule that WM/Evidence consume normalized DATA geometry.

- [ ] **Step 2: Update the documentation**

  Explain that common runtime mechanics are centralized while temporal role semantics remain in DATA. State that raw reasoning is not a fact source and that unclassified uploads remain quarantined.

- [ ] **Step 3: Run the full relevant verification**

  Run: `pytest -q tests/test_structured_runtime_contracts.py tests/test_structured_runtime_consensus.py tests/test_temporal_role_classifier.py tests/test_real_upload_ingress.py tests/test_data_admission_mvp.py tests/test_data_admission_p1.py tests/test_jintian_topology_policy.py tests/test_jintian_data_e2e_acceptance.py tests/test_data_p1_p2_docs.py`

  Expected: all selected tests pass, including real Jintian DATA → WM/Evidence consumption.

- [ ] **Step 4: Run the broader suite and inspect the diff**

  Run: `pytest -q`, `git diff --check`, and `git status --short`.

  Expected: full suite passes; any whitespace warning is reviewed rather than silently ignored; worktree contains only intended changes.

- [ ] **Step 5: Commit**

  ```bash
  git add backend/app/infrastructure/structured_runtime/README.md docs/design/DATA_EXECUTABLE_DESIGN.md docs/superpowers/plans/2026-09-05-data-structured-ingress.md tests/test_data_p1_p2_docs.py
  git commit -m "docs(data): document unified structured ingress boundary"
  ```

## Self-Review

- Explicit upload intent is provided by the typed session channel, not guessed from filenames or fields.
- Raw source geometry and raw provider reasoning remain immutable/auditable and are not promoted to downstream facts.
- Provider transport failure, schema failure, and semantic role disagreement remain separately observable.
- Unclassified and contradictory uploads remain fail-closed.
- The plan includes a real `process_uploaded_file` acceptance path, not only direct `DataAdmissionRequest` construction.
- The plan ends with DATA-to-WM/Evidence acceptance and full-suite verification.
