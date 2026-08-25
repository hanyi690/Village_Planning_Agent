# P1 Fix Round 1 Narrow Review

Date: 2026-08-25
Reviewed commit: `a65f5990`
Base: `e9f2a0be`
Scope: the five Round 1 closure claims from the commit's P1 report; no full-repository rescan.

## Verdict

**NEEDS_FIX** — the production implementation is consistent with the five requested contracts, and all bounded verification commands passed. However, the focused regression suite does not fully prove the two runtime boundary claims: it does not execute `ground_node` against a pending/authority-mismatched request and assert that `ground_aggregate` is not called, and it does not test a missing typed decision record when a current typed fingerprint is present. These are P2 test-coverage findings, not observed implementation failures.

## Findings

### P2 — Missing production-boundary regression for pending/authority-mismatched GROUND admission

Status: implementation review passes; test coverage is incomplete.

Evidence:

- `backend/app/domain/program/target_projection/compile.py:561-597` builds `GroundingRequest` values, retains only `status == "ready"` in formal `spatial_reference_specs`/`grounding_requests`, and places pending pairs into `pending_grounding_requests`.
- `backend/app/workflow/stages/ground.py:425-458` independently requires a matching request with `status == "ready"` and equality for `source_snapshot_ref`, `source_snapshot_digest`, `source_binding_ref`, and `source_feature_digest` before adding a spec to `grounding_specs`.
- `backend/app/workflow/stages/ground.py:509-521` calls `ground_aggregate` only when `grounding_specs` is non-empty; otherwise it returns an empty `GroundingResult`. The later enhancement call is also guarded by `grounding_specs`.
- `backend/tests/core/test_p1_closure_contracts.py:112-149` verifies request readiness/pending state and unsupported-reference parking, but does not invoke `ground_node` or `ground_aggregate`.

Impact: a future wiring regression at the actual GROUND stage could re-admit pending or mismatched requests while the current contract tests still pass.

Recommended closure test: invoke `ground_node` with a compilation containing a pending request and with a ready request whose authority differs from its spec; monkeypatch `ground_aggregate` to fail if called, then assert zero candidates and preserved pending/audit lineage.

### P2 — Missing typed-decision regression for the “missing record” branch

Status: implementation review passes; one explicit branch lacks focused coverage.

Evidence:

- `backend/app/workflow/root_graph.py:1698-1739` enters typed validation whenever a `decision_record` is supplied or the current review item contains `context.decision_fingerprint`; if the record is absent, validation raises and returns a fresh `stale_human_decision` interrupt with `HUMAN_DECISION_STALE`, clears decisions, and sets `human_review_resume_consumed` to `False`.
- `backend/tests/core/test_p1_closure_contracts.py:245-270` verifies stale typed records return HUMAN pending, but does not verify a missing record with a present current fingerprint.
- The same code intentionally permits legacy generic approval when neither a typed record nor a typed current fingerprint is present; this is compatible with the conditional typed-decision boundary and was not treated as a finding.

Recommended closure test: submit `action=approve` with a current `decision_fingerprint` in the review item but without `decision_record`; assert `HUMAN_DECISION_STALE`, a live HUMAN interrupt, empty decisions, and `human_review_resume_consumed == False`.

## Contract-by-contract assessment

### 1. TARGET_PROJECTION and GROUND formal admission

**Implementation: PASS.** Formal admission is `ready`-only in TARGET_PROJECTION, and GROUND rechecks both status and all four authority fields before resolution. Pending requests are retained as pending lineage and cannot reach the `ground_aggregate` call under the reviewed path. The direct runtime assertion is the P2 coverage gap above.

### 2. Refined CandidateGeometry reference preservation

**PASS.** `backend/app/domain/allocation/refined_candidate_catalog.py:251-255` copies `physical_project_ref`, `component_claim_refs`, and `component_fact_refs` from the source geometry into every refined geometry. `test_select_refinement_preserves_project_and_component_refs` exercises the actual catalog builder and asserts all three fields.

### 3. Solver subproblem project boundary and target maps

**PASS.** `backend/app/domain/allocation/subproblem_compiler.py:355-427` groups target subproblems with the same non-empty physical project into one `project:<digest>` solver unit, unions target/relation/component refs, and merges `candidate_ids_by_target` without collapsing target identity. `test_same_physical_project_two_targets_share_one_solver_boundary` asserts one unit, both target refs, and the exact target-keyed candidate map. Existing decomposition tests also cover deterministic target routing and shared-resource composition.

### 4. Solver readiness defaults and relation evidence

**PASS.** `backend/app/domain/allocation/solver_readiness.py:276-307` calls `build_relation_readiness` for every factor and converts its reasons to hard blockers for hard factors and advisories for soft factors. `test_default_hard_satisfied_relation_without_evidence` proves an otherwise satisfied hard relation without evidence blocks; the soft evaluator/input tests prove advisory behavior and backend resolution. The bounded suite also verifies missing hard demand/network inputs block and soft gaps remain advisory.

### 5. HUMAN stale/missing typed decision handling

**Implementation: PASS; coverage: P2 gap above.** `apply_human_review_decision` validates typed records before approval routing. A stale or malformed/missing record in a typed review context returns a fresh HUMAN interrupt and prevents generic approve. The stale-record test is present and passed; the missing-record sibling case should be added.

## Verification performed

Commands run within the requested bounded scope:

```text
python -m pytest -c pytest.ini -o addopts='' \
  tests/core/test_p1_closure_contracts.py \
  tests/core/test_solver_readiness.py \
  tests/core/test_solver_subproblem_decomposition.py \
  tests/core/test_select_gate_deferred_targets.py \
  tests/core/test_human_interrupt_contract.py \
  tests/core/test_hitl_route_after_resume.py \
  tests/core/test_application_boundary.py \
  -q --maxfail=1
60 passed, 1 PytestCacheWarning (environment permission only)
```

Changed production/test modules compiled with:

```text
python -m compileall -q <changed modules>
passed
```

Whitespace validation:

```text
git diff --check e9f2a0be a65f5990
passed
```

No implementation files or pre-existing user dirty files were modified. Existing dirty paths remain outside this review, including `.codex/config.toml`, `.analysis/`, the recorded replay/support files, and the planning document.
