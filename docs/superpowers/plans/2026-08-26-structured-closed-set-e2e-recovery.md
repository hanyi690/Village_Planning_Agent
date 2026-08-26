# Structured and Closed-Set E2E Recovery Plan

## Goal

Repair the live E2E contract mismatches around structured candidate selection, raw spatial-role aliases, and Layer 2 source-fact references; then run a fresh real-provider E2E and classify the result from persisted state rather than approval status alone.

## Tasks

### 1. Add shared spatial-role and candidate-selection contracts

Files:
- `backend/app/contracts/spatial/spatial_reference_contracts.py`
- `backend/tests/core/test_spatial_reference_selection_contract.py`

Implement a shared role normalizer for observed aliases such as `transportation_facility`, `water_body`, `river`, `water_facility`, `road_segment`, and `geological_hazard_point`, while preserving canonical roles.

Implement a shared prompt renderer that explicitly requires one JSON object, the exact status enum, an exact allowed candidate-ID set, an empty selected ID for non-selected statuses, the exact input digest, and no Markdown, explanation, or newly invented IDs.

Add unit tests for alias normalization and the rendered closed-set contract.

### 2. Apply the shared contract at every candidate-selection boundary

Files:
- `backend/app/infrastructure/kg/enrichment/name_backfill.py`
- `backend/app/domain/ground/anchors.py`
- `backend/app/spatial/grounding/resolver.py`
- `backend/app/evidence/retrieval/evidence_graph.py`
- `backend/tests/core/test_name_backfill.py`
- `backend/tests/core/test_grounding_llm_reason_alignment.py`
- `backend/tests/core/test_l1_spatial_anchor_work_items.py`

Use the shared renderer in name backfill, ground-anchor selection, and resolver selection. Normalize raw roles before strict grounding-role logic and L1 evidence classification, so live provider values do not fall through to `unknown` merely because they use a repository-supported alias.

Keep the existing digest separators and typed response model unchanged. Extend focused tests to prove the prompt contains the closed-set rules and raw aliases become the expected canonical roles.

### 3. Add a final Layer 2 source-fact closed-set guardrail

Files:
- `backend/app/domain/objectives/worker.py`
- `backend/tests/core/test_l2_prompt_boundary.py`

Append a compact provider-facing rule at the final L2 prompt boundary stating that `source_fact_refs` may contain only exact canonical IDs from the current dynamic L1 fact catalog. Explicitly reject EXPLORE, lineage, `re-*`, report, provenance, and invented IDs. Add a prompt-boundary regression test.

### 4. Run focused verification and restart real E2E

Run the focused contract, grounding, name-backfill, L1, and L2 tests first. Then start a fresh real-provider run with `python -u backend/_e2e_resume.py --force-new --deadline-seconds 7200`.

Inspect the new session artifacts, LangGraph state, CAS artifacts, and SQLite rows. Confirm whether L2 reaches completion, whether `source_fact_refs` use only dynamic L1 IDs, whether grounding produces auditable exact-feature evidence, and whether any remaining failure is a provider-contract issue, a local budget issue, or a workflow retry. Do not label an auto-approved `diagnostic_only` run as a successful E2E.

## Verification evidence

The final report will include the focused-test result, fresh E2E session ID, completed layer/stage, retry counters, provider failures, closed-set violations if any, and the persisted grounding/L2 evidence quality.

## Rollback / scope

Only the listed source and test files are in scope. Existing user changes and intentionally removed or regenerated `graphify-out` artifacts must remain untouched.
