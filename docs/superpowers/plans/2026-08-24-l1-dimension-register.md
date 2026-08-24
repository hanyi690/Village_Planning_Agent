# L1 Dimension Register Implementation Plan

> Status: SUPERSEDED. The dual-channel L1/L3 contract and current implementation
> boundary are maintained in
> [`2026-08-24-l1-l3-planning-structured-output.md`](2026-08-24-l1-l3-planning-structured-output.md),
> [`docs/design/01_CONTRACTS_AND_INVARIANTS.md`](../../design/01_CONTRACTS_AND_INVARIANTS.md),
> and [`docs/architecture/CURRENT_RUNTIME.md`](../../architecture/CURRENT_RUNTIME.md).
> This historical task breakdown must not be used to reintroduce a fixed
> `village_data` parser or treat the loop as the product goal.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make L1 dimension outputs the authoritative producer of raw current-asset and demand registrations, with stable source-row lineage, while removing the aggregate-level raw-document parser from the authoritative path.

**Architecture:** A shared L1-only source index assigns stable source-segment IDs and raw locators before dimension analysis; it does not assign semantic row IDs. Each L1 dimension runs a bounded extract → validate → repair/continue loop: a first pass produces the dimension report and typed drafts, targeted passes complete only missing/invalid fields, and a coverage pass closes or explicitly diagnoses unresolved source evidence. The dimension persists the validated confirmations beside its report and observations. `l1_aggregate` only validates, unions, deduplicates, detects conflicts/missing coverage, and builds `L1Snapshot`; it never reads or parses `village_data`.

**Tech Stack:** Python 3, Pydantic v2, LangGraph state, SQLModel/SQLite report store, pytest, existing structured LLM runner, React/TypeScript artifact viewer.

## Global Constraints

- Raw `village_data`/`current_status` may be read and structured only inside the L1 boundary.
- `current_asset` and `demand` are distinct identities; a demand must never be emitted as `现状设施`.
- Every confirmed row must carry a stable `row_id`, source document digest, and source span/locator.
- L1 revisions must not silently delete a previously confirmed source row; use `confirmed`, `uncertain`, or `withdrawn` status.
- L1 aggregate may not reopen or regex-scan raw input; it consumes only dimension artifacts and an L1-owned source index reference.
- L2/L3/Project Bank/GROUND/EXECUTE/frontend consume L1 artifacts and never reconstruct rows from raw text.
- Existing spatial observations remain separate from source-register rows.
- Unknown source row IDs or mismatched ledger kinds fail closed for the structured row, while the narrative report may remain available with a diagnostic.

## Bounded LLM loop (required)

One provider response is not the completeness boundary. Structured output constrains shape, but source correctness, row coverage, and current-versus-demand classification are checked by deterministic L1 validators. The application owns the loop and persists a resumable cursor after every pass.

- `observe`: produce the dimension report, observations, and only the source row IDs directly relevant to the dimension.
- `register`: complete canonical fields for the selected IDs from a compact source index; do not resend the whole document when the index is sufficient.
- `validate`: compare IDs, ledger kind, source digest/span, values, units, duplicates, and dimension scope against the L1 source index.
- `repair`: re-request only rejected rows/fields with machine-readable diagnostics. A repair cannot change canonical source values or source locators.
- `coverage`: return `confirmed`, `not_applicable`, `uncertain`, or `source_exhausted` for pending IDs; unresolved rows remain diagnostics rather than fabricated facts.

The loop is intentionally bounded and idempotent: per-dimension attempt limits, a total L1 call budget, token/deadline limits, and a stable `(session, dimension, input_digest, pass, attempt)` key are required. Completed passes are skipped on resume. The model may request a pure `confirm_rows`/`repair_rows`/`audit_coverage` operation in a function-call-like schema, but the application performs validation and materialization; no model call mutates the artifact directly. L3 will use the same pattern later for claim extraction, typed-intent repair, and completeness admission, while candidate geometry and solver facts remain deterministic downstream concerns.

---

### Task 1: Define the dimension-level registration contract

**Files:**
- Modify: `backend/app/domain/assessment/observation_draft.py`
- Modify: `backend/app/contracts/domain/l1_contracts.py`
- Test: `backend/tests/core/test_l1_dimension_register_contract.py`

**Interfaces:**
- Add `L1RegisterRowDraft` with `row_id`, `ledger_kind`, `status`, optional canonical fields, and `evidence_note`.
- Add a resumable `L1DimensionPassState`/cursor containing `dimension_key`, `source_digest`, `pass`, `attempt`, `pending_row_ids`, `rejected_row_ids`, diagnostics, and call-budget counters.
- Extend `L1DimensionOutput` with `register_rows: list[L1RegisterRowDraft]`.
- Add `register_rows_by_dimension: dict[str, list[L1RegisterRow]]` and `register_diagnostics_by_dimension` to `L1Snapshot`.

- [ ] **Step 1: Write failing schema tests**

```python
def test_dimension_output_has_separate_current_and_demand_rows():
    output = L1DimensionOutput.model_validate({
        "report_body": "现状与需求",
        "observations": [],
        "register_rows": [
            {"row_id": "row-current", "ledger_kind": "current_asset", "status": "confirmed"},
            {"row_id": "row-demand", "ledger_kind": "demand", "status": "confirmed"},
        ],
    })
    assert [row.ledger_kind for row in output.register_rows] == ["current_asset", "demand"]
```

- [ ] **Step 2: Run the focused test and verify it fails because the field is absent**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_contract.py -q -o addopts=''`

- [ ] **Step 3: Add the draft model and snapshot fields**

The draft must not require the model to invent a digest or span; those are materialized from the L1 source index after the row ID is validated.

- [ ] **Step 4: Run focused schema tests**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_contract.py -q -o addopts=''`

- [ ] **Step 5: Run compile/type checks for the touched contracts**

Run: `python -m compileall backend/app/domain/assessment/observation_draft.py backend/app/contracts/domain/l1_contracts.py`

### Task 2: Move source-row indexing to the L1 dimension boundary

**Files:**
- Modify: `backend/app/domain/assessment/input_register.py`
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Modify: `backend/app/domain/assessment/aggregate.py`
- Test: `backend/tests/core/test_l1_dimension_register_producer.py`

**Interfaces:**
- Add `build_l1_source_index(input_texts) -> L1InputRegister` as an L1-only helper.
- Add `materialize_dimension_register_rows(drafts, source_index, dimension_key) -> tuple[list[L1RegisterRow], list[str]]`.
- Add a bounded `run_l1_dimension_loop(...)` that persists the pass cursor, calls the existing structured runner with small schemas, and resumes from the first incomplete pass.
- `analyze_dimension` passes a compact source-row index to the structured L1 prompt, validates returned IDs, and serializes `register_rows` beside `observations`.
- `l1_aggregate` reads only the persisted dimension `instruction` objects; the fixed-format `parse_l1_input_register` helper has been removed.

- [ ] **Step 1: Write failing producer tests**

The test must feed a canonical source index and a typed dimension response, then assert that the persisted materialized row keeps the canonical name, ledger kind, source reference, and source span even if the model supplies a different name.

```python
def test_dimension_rows_are_materialized_from_valid_source_ids():
    source = build_l1_source_index({"village_data": DEMO_SOURCE})
    segment = next(item for item in source.source_segments if "村道硬化" in item.text)
    rows, diagnostics = materialize_dimension_register_rows(
        [{"ledger_kind": "current_asset", "status": "confirmed",
          "name": "村道硬化", "source_segment_ids": [segment.segment_id],
          "source_quote": "村道硬化"}],
        source,
        "traffic",
    )
    assert not diagnostics
    assert rows[0].name == "村道硬化"
    assert rows[0].source_ref.startswith("input:village_data")
```

- [ ] **Step 2: Run the test and verify the materializer is missing or fails**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_producer.py -q -o addopts=''`

- [ ] **Step 3: Implement source-index validation and materialization**

Reject unknown `row_id`, mismatched `ledger_kind`, and duplicate conflicting statuses. Keep the narrative response but write a stable diagnostic for rejected structured rows.

- [ ] **Step 4: Replace the aggregate raw parse with dimension-row merge**

The aggregate must collect `register_rows` from the compiled dimension snapshots, populate `register_rows_by_dimension`, and produce the union register only from L1-owned source rows. If the source index is unavailable, emit a deterministic `l1_source_index_missing` diagnostic instead of reopening raw input.

- [ ] **Step 5: Run focused producer and aggregate tests**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_producer.py backend/tests/core/test_l1_input_register.py -q -o addopts=''`

### Task 3: Extend the structured L1 prompt and compiler

**Files:**
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Modify: `backend/app/data/ingestion/compiler/profiles/l1_observation.py`
- Modify: `backend/app/infrastructure/llm/prompts/analysis.py`
- Test: `backend/tests/core/test_l1_dimension_prompt_contract.py`

**Interfaces:**
- Prompt includes a compact source-row index with row IDs, kind, category, name, and locator metadata.
- Prompt requires the dimension to return only rows directly substantiated by that dimension and to preserve `current_asset` versus `demand`.
- The observe, register/repair, and coverage prompts use separate small schemas; the final instruction JSON becomes `{ "observations": [...], "register_rows": [...], "coverage": [...] }`. Compiler remains backward-incompatible for new L1 writes but can produce a bounded diagnostic for legacy list-shaped instructions during migration.

- [ ] **Step 1: Write failing prompt/compiler tests**

Assert that the prompt names `register_rows`, `row_id`, `current_asset`, `demand`, and explicitly forbids outputting a demand row as `现状设施`. Assert that compiler extracts both observations and register rows from the object-shaped instruction.

- [ ] **Step 2: Run focused prompt/compiler tests and verify failure**

Run: `python -m pytest backend/tests/core/test_l1_dimension_prompt_contract.py -q -o addopts=''`

- [ ] **Step 3: Add the bounded prompt section and object-shaped instruction handling**

Do not add Jintian-specific row names; the prompt must operate on the source-row index and the configured dimension focus.

- [ ] **Step 4: Run focused tests**

Run: `python -m pytest backend/tests/core/test_l1_dimension_prompt_contract.py backend/tests/core/test_l1_typed_fact_contract.py -q -o addopts=''`

### Task 4: Add revision stability and coverage diagnostics

**Files:**
- Modify: `backend/app/domain/assessment/aggregate.py`
- Modify: `backend/app/contracts/domain/l1_contracts.py`
- Test: `backend/tests/core/test_l1_dimension_register_revision.py`

**Interfaces:**
- Add deterministic coverage diagnostics for source rows not confirmed by any L1 dimension.
- Persist every pass result and validation outcome so resume never reruns completed dimensions or loses the repair queue.
- Merge repeated confirmations by `row_id`; identical confirmations deduplicate, conflicting ledger kind or canonical fields become an L1 issue.
- Preserve row status across revisions and make silent deletion observable.

- [ ] **Step 1: Write failing revision tests**

Cover same row confirmed by two dimensions, a v2 response omitting a v1 row, and a mismatched ledger kind.

- [ ] **Step 2: Run tests to verify missing behavior**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_revision.py -q -o addopts=''`

- [ ] **Step 3: Implement merge/coverage diagnostics**

- [ ] **Step 4: Run the focused suite**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_revision.py backend/tests/core/test_l1_dimension_register_producer.py -q -o addopts=''`

### Task 5: Update the authoritative design and status documentation

**Files:**
- Modify: `docs/design/00_SYSTEM_DESIGN.md`
- Modify: `docs/design/01_CONTRACTS_AND_INVARIANTS.md`
- Modify: `docs/architecture/CURRENT_RUNTIME.md`
- Create: `docs/audits/l1-dimension-register-2026-08-24.md`

**Interfaces:**
- Document that L1 dimension outputs, not aggregate parsing, are the semantic producer of source-register rows.
- Document the bounded multi-pass loop, its budgets, resume cursor, and the distinction between schema validity and source correctness.
- Document row identity, revision behavior, diagnostics, and the distinction between source index and dimension confirmation.
- Record the live session evidence and the exact tests that do and do not prove closure.

- [ ] **Step 1: Update the normative stage-responsibility and invariant text**
- [ ] **Step 2: Add the current-state evidence ledger**
- [x] **Step 3: Review for stale claims that 25/22 are already produced**

### Task 6: Verify the L1-only vertical slice before downstream work

**Files:**
- Test: `backend/tests/core/test_l1_dimension_register_e2e.py`
- Inspect only: `backend/app/domain/program/worker.py`, `backend/app/infrastructure/rag/service.py`, `frontend/src/features/planning/components/layout/ReportViewer.tsx`

- [ ] **Step 1: Write a mocked end-to-end L1 test**

Run the real L1 aggregation path with deterministic structured dimension responses and assert:

```text
rows are available through the L1 artifact only when typed L1 drafts cite verified source segments;
each confirmed row has stable source_ref/source_span;
register_rows_by_dimension is populated;
aggregate never reads raw input;
current/demand remain distinct;
an interrupted observe/register/repair/coverage pass resumes without rerunning completed passes.
```

- [ ] **Step 2: Run the vertical slice**

Run: `python -m pytest backend/tests/core/test_l1_dimension_register_e2e.py backend/tests/core/test_l1_dimension_register_contract.py backend/tests/core/test_l1_dimension_register_producer.py backend/tests/core/test_l1_dimension_register_revision.py -q -o addopts=''`

- [ ] **Step 3: Run compileall and frontend type-check only after the artifact shape is stable**

Run: `python -m compileall backend/app/domain/assessment backend/app/data/ingestion/compiler/profiles/l1_observation.py backend/app/contracts/domain/l1_contracts.py`

Run: `npm run type-check` from `frontend`.

## Self-Review Checklist

- The plan does not claim the current parser is a completed L1 dimension producer.
- Every new row is validated against an L1-owned source index; the LLM cannot invent source IDs or overwrite canonical source values.
- Current/demand separation and revision stability have explicit tests.
- Aggregate no longer has permission to read raw input.
- Downstream Project Bank/RAG/grounding changes are intentionally deferred until the L1 vertical slice is proven.
