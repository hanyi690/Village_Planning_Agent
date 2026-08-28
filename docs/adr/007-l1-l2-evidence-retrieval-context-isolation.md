# ADR 007: L1/L2 证据检索与上下文隔离的早期统一方案

> Status: SUPERSEDED
> Authority: Historical decision record only. Current normative LLM/context boundary is ADR 008; current retrieval design is `docs/design/04_EVIDENCE.md`.

## 1. Historical role

This ADR captured an earlier convergence attempt for retrieval preflight, shared evidence retrieval, context separation, and unified LLM call management.

## 2. Why it is superseded

ADR 007 mixed target design, implementation guidance, and transitional compatibility details in one place. The active authority is now split more clearly:

- retrieval and grounding design: [`../design/04_EVIDENCE.md`](../design/04_EVIDENCE.md)
- planning/execution ownership: [`../design/06_SELECT_EXECUTE_AND_CODE.md`](../design/06_SELECT_EXECUTE_AND_CODE.md)
- migration status: [`../design/05_MIGRATION.md`](../design/05_MIGRATION.md)
- observed runtime evidence: [`../architecture/CURRENT_RUNTIME.md`](../architecture/CURRENT_RUNTIME.md)
- accepted LLM/context boundary: [`008-final-llm-context-evidence-boundary.md`](008-final-llm-context-evidence-boundary.md)

## 3. Historical concepts that are no longer active contracts

The following ADR 007 concepts remain historically informative but are not current implementation contracts by themselves:

- `FactRegistry` as a named active authority surface
- `ProjectCognitionView` as the active top-level retrieval document
- `FactProjection` as a separately named public contract
- old report-body compatibility or dual-read paths
- legacy `GroundedAnchor` and related anchor-style authority proposals

## 4. What still survives from this ADR

The problem statement survived: retrieval context should stay separate from analysis prompts, report text should stay a display projection, and production LLM calls should stay behind a managed boundary.

## 5. Use this ADR correctly

Use ADR 007 only to understand how the current design evolved or why old names still appear in code, reports, or tests. Do not use it as the source of truth for current retrieval behavior, current contracts, or completion status.
