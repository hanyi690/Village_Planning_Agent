# L1/L2/L3 Contract and Report Boundary Convergence Implementation Plan

> **For agentic workers:** Execute the tasks in order, keeping each change reviewable and running the named tests after every task. The current repository is already dirty; preserve unrelated user changes.

**Goal:** 收拢 L1/L2/L3 的模型事务边界，禁止 L3 provider 生成可执行空间规划细节，并把详细规划报告延迟到空间链路形成 `ScenarioSet` 之后、把最终交付报告延迟到验证与 reconcile 之后，从而让规划产出稳定、可追溯、可增量修复。

**Architecture:** Provider 只负责小而单一的语义事务；应用层负责投影、去重、ID/分组/参数槽位、逐项隔离、重试和报告装配。主链路为 `L1 page observation → L2 abstract decision → L3 rough PlanningClaimSet → deterministic admission → TARGET_PROJECTION → GROUND → SELECT/ScenarioSet → DetailedPlanningReport → APPROVED/EXECUTE/VALIDATE/RECONCILE → DeliveryReport`。报告是由已落盘工件和 lineage/digest 生成的派生记录，不回流为 L2/L3 语义输入。

**Tech Stack:** Python 3, Pydantic v2, existing LLM manager/context projections, pytest, YAML phase configuration.

## Global Constraints

- Provider wire schemas must be smaller than their internal domain models and must not expose package IDs, typed spatial parameter blocks, relation catalogs, candidate geometry, or execution commands.
- `L3RoughClaim` is non-executable. IDs, grouping, target family, requirement slots, and source-backed parameter values are application-owned.
- A malformed claim is quarantined as an item-level rejection; valid sibling claims remain usable. A single rejected item must never trigger a whole-dimension regeneration.
- Retry classes are explicit (`schema`, `semantic`, `transport`, `item_repair`, `workflow`); `max_retries=0` remains zero.
- L3 may emit an optional `L3IntentSummary` for display, but no detailed spatial report. Detailed and delivery reports must carry artifact references, run root, source/evidence digests, and stage lineage.
- Semantic prompts never contain report bodies, display summaries, raw prompts, RAG text, dependency metadata, relation catalogs, or duplicated fact/location projections unless an explicit contract says otherwise.

## Task 1: Introduce the narrow L3 rough-claim wire contract

**Files:**

- Modify `backend/app/domain/program/claim_draft.py`.
- Add `backend/tests/core/test_l3_rough_claim_contract.py`.

**Interfaces:**

- Add `L3RoughClaimDraft` with only `statement`, `claim_family`, `planning_role`, `objective_refs`, `source_fact_refs`, `evidence_refs`, `location_hints`, `grounding_requirements`, and `uncertainty`.
- Add `L3RoughClaimOutput` as the provider envelope containing status, accepted rough claims, and item-level rejection metadata.
- Keep `PlanningClaimSet` and admitted-target models internal; application code creates claim IDs, target identity, family normalization, grouping, and package/lineage fields.

**Tests:**

- Assert the provider JSON schema does not contain package, component, relation, geometry, candidate, or typed spatial parameter fields.
- Validate a minimal multi-item fixture and verify a malformed item is represented as a rejection without invalidating its valid sibling.
- Assert the optional intent summary is display-only and is not accepted by the semantic dependency projection.

## Task 2: Make dependency projection and L3 prompts explicit and bounded

**Files:**

- Modify `backend/app/infrastructure/llm/context_manager.py`.
- Modify `backend/app/infrastructure/llm/dependency_context.py`.
- Modify `backend/app/domain/program/worker.py`.
- Modify `backend/app/infrastructure/llm/prompts/detailed.py`.
- Extend `backend/tests/core/test_l3_prompt_boundary.py` and the existing dependency/context tests.

**Interfaces:**

- Add named projection functions such as `render_l2_abstract_projection(...)` and `render_l3_rough_claim_projection(...)` with explicit item and character budgets.
- The L2→L3 projection may contain deduplicated abstract decisions, cited canonical facts, direct L1 facts required by the task, and task-level evidence references only.
- Remove summary/report/raw prompt/RAG/dependency metadata/relation-catalog/component-template input from the L3 semantic prompt; retain grounding requirements as text, not executable relation data.
- Record projection counts, omitted sections, deduplication counts, and input/output digests in the call record.

**Tests:**

- Build a dependency fixture containing every forbidden section and assert none appears in the rendered L3 prompt.
- Assert the same fact is serialized once, arrays are bounded, and the projection reports omissions deterministically.
- Assert the L3 prompt budget is enforced before provider invocation and that no hidden cumulative same-layer summary is added.

## Task 3: Implement item-level normalization, repair, and retry accounting

**Files:**

- Modify `backend/app/domain/program/worker.py`.
- Modify `backend/app/domain/program/planning_claims.py`.
- Modify `backend/app/infrastructure/llm/manager.py`.
- Add or extend `backend/tests/core/test_l3_item_repair.py` and manager retry tests.

**Interfaces:**

- Replace the all-or-nothing component list conversion with `L3ClaimBatchResult`, containing accepted items, `L3ItemRejection` records, and repair class/error codes.
- Add a bounded item-repair call that receives only the rejected item and its validation error, never the full batch or full dimension context.
- Preserve caller retry budgets exactly; remove the manager-side floor that converts zero retries into one.
- Extend `LLMCallRecord` with schema/projection digest, retry class, attempt index, accepted/rejected item counts, and report lineage fields.

**Tests:**

- Feed one invalid and two valid items; assert both valid items survive and only the invalid item is repaired or quarantined.
- Assert `max_retries=0` makes no retry and that a semantic error does not regenerate an entire batch.
- Assert telemetry distinguishes provider/schema failure, item repair, and workflow retry.

## Task 4: Move executable planning concerns into deterministic admission and GROUND

**Files:**

- Modify `backend/app/contracts/program.py`.
- Modify `backend/app/domain/program/claim_adapter.py`.
- Modify `backend/app/domain/program/target_projection/compile.py`.
- Modify the existing GROUND compilation modules under `backend/app/domain/ground/`.
- Extend `backend/tests/core/test_l3_executable_target_admission.py`, `test_target_projection_semantic_contract.py`, and add a pending-requirement-gap case.

**Interfaces:**

- Admission validates objective/fact/evidence references, creates application-owned IDs and target families, and derives typed requirement slots only from source-backed facts and deterministic rules.
- Missing execution parameters become explicit `pending`/`deferred` slots with gap records; they are never invented by L3.
- `TARGET_PROJECTION` emits the minimal `GroundedPlanningProblem` input. `GROUND` resolves evidence and records provenance; `SELECT` creates `ScenarioSet` and candidate geometry only after the rough claims have been admitted.

**Tests:**

- Assert a rough claim cannot carry an executable package or parameter block through admission.
- Assert missing source-backed values produce a pending gap and do not silently become defaults.
- Assert every grounded field has a source/evidence reference and that `ScenarioSet` is the first owner of candidate/geometry artifacts.

## Task 5: Establish post-ScenarioSet detailed-report and post-validation delivery-report owners

**Files:**

- Modify `backend/app/domain/program/worker.py` to remove the immediate claim-driven detailed-report call.
- Add `backend/app/contracts/artifacts/planning_report_contracts.py` for `L3IntentSummary`, `DetailedPlanningReport`, and `DeliveryReport` envelopes.
- Add `backend/app/domain/delivery/planning_report.py` to render deterministic reports from persisted artifacts and lineage.
- Modify the workflow stage that persists `ScenarioSet` and the delivery aggregate/renderer under `backend/app/domain/delivery/`.
- Add `backend/tests/core/test_report_timing_authority.py`, `test_summary_report_projection.py`, and extend complete-delivery-output tests.

**Interfaces:**

- `L3IntentSummary` is optional, short, display-only, and may contain only claim references, uncertainty, and unresolved-gap counts.
- `DetailedPlanningReport` can be created only after `ScenarioSet` and must reference the selected scenario, grounded problem digest, claim/admission lineage, and report run root.
- `DeliveryReport` can be created only after approval/materialization, `PlannedState`, `ValidationCertificate`, and `RECONCILE` lineage are present.
- Reports are persisted as read models/artifacts and are excluded from future L2/L3 semantic prompts by default.

**Tests:**

- Assert no detailed report exists immediately after `l3.claims` unless it is explicitly named and typed as `L3IntentSummary`.
- Assert report construction fails closed before `ScenarioSet`, before validation, or when lineage/digests are missing.
- Assert the final delivery report contains selected scenario, planned state, validation, reconcile, source/evidence, and run-root references.

## Task 6: Add convergence gates, documentation checks, and rollout verification

**Files:**

- Modify `backend/app/infrastructure/llm/stats_collector.py` or the existing telemetry owner used by `LLMCallRecord`.
- Update `docs/design/04_EVALUATION_AND_ACCEPTANCE.md` metrics when implementation names settle.
- Extend `backend/tests/contracts/test_documentation_convergence.py` and add runtime contract fixtures under `backend/tests/contracts/`.

**Interfaces and gates:**

- Track forbidden provider fields, prompt section counts, projection digest, item acceptance/rejection, retry class, report timing, and lineage completeness.
- Add negative gates for premature reports, claim-driven spatial assertions, implicit retries, whole-batch reasks, and report bodies entering semantic prompts.
- Roll out behind the existing phase/config mechanism: first shadow projection and telemetry, then narrow L3 wire output, then disable the old detailed-report path after parity evidence.

**Verification commands:**

```powershell
python -m pytest backend/tests/core/test_l3_rough_claim_contract.py backend/tests/core/test_l3_prompt_boundary.py backend/tests/core/test_l3_item_repair.py backend/tests/core/test_report_timing_authority.py backend/tests/contracts/test_documentation_convergence.py -q -o addopts=
python -m pytest backend/tests/core/test_structured_output_runner.py backend/tests/core/test_context_manager.py backend/tests/core/test_dependency_context.py backend/tests/core/test_l1_typed_output_recovery.py backend/tests/core/test_l2_prompt_boundary.py backend/tests/core/test_planning_claim_provider_adapter.py backend/tests/core/test_portable_structured_output.py -q -o addopts=
git diff --check
```

Before merging, compare one representative run at the same input: L2/L3 prompt sizes, accepted/rejected item counts, retry classes, `ScenarioSet` creation, detailed-report timing, and final delivery lineage must all be present in the audit record. The old claim-driven `l3.report` path is removed only after these gates pass.
