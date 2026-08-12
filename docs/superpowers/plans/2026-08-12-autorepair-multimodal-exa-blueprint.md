# Auto-Repair, Multimodal and Exa Blueprint Integration Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend blueprint freeze migration-time interfaces for bounded auto-repair, multimodal evidence, and Exa-backed external exploration without allowing external search or LLM output to become planning authority.

**Architecture:** Treat auto-repair and multimodal processing as typed workflow/evidence capabilities with immutable artifacts and explicit provenance. Treat Exa as one adapter behind `ExternalSearchPort` under EXPLORE; local KG, reports, Bundle, and typed artifacts remain the first evidence sources, while external results are untrusted evidence that may trigger typed claim review, retry, or HUMAN review but may not create geometry, BSM, classification, or site decisions.

**Tech Stack:** Markdown architecture blueprint, Python/Pydantic contracts, LangGraph workflow stages, CAS artifact descriptors, KG/spatial evidence ports, Exa Search API adapter.

## Global Constraints

- Freeze ports and typed artifacts during migration before switching production callers; do not create long-lived dual-write compatibility paths.
- `ValidationAdjustment` must identify responsible stage, target refs, input/evidence refs, bounded parameters, parent digests, and idempotency/fingerprint data.
- `ImageArtifact`, `ImageEvidence`, `VisualFact`, and `VisualReview` are immutable evidence artifacts; root checkpoint state stores refs and checksums only.
- Exa results must preserve request ID, result URL/ID, source metadata, excerpts or content refs, retrieval policy, latency/cost, and provenance.
- External search cannot directly create entity refs, BSMs, coordinates, classifications, `ParcelChange`, `SiteSelectionDecision`, or `ExecutionPlan` tasks.
- Exa unavailability, empty results, stale/conflicting sources, or failed content retrieval must yield typed unresolved evidence and local/HUMAN routing; never guessed facts.

---

### Task 1: Freeze migration-time interfaces

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

**Interfaces:**
- `ValidationAdjustmentExecutor.apply(state, report) -> AdjustmentExecutionResult`
- `MediaEvidencePort.ingest(request) -> ImageArtifact`
- `VisualEvidencePort.analyze(artifact_ref, request) -> ImageEvidence`
- `ExternalSearchPort.search(request) -> ExternalSearchResult`
- `ExploreService.retrieve(request) -> EvidenceBundle`

- [ ] State that interface contracts are frozen before each migration cutover, with adapters first and stage callers switched only after contract/integration tests pass.
- [ ] Require every port to return typed success, empty, unavailable, and unresolved outcomes with provenance rather than raising untyped fallback behavior into the workflow.
- [ ] Keep provider-specific fields behind infrastructure adapters; workflow and domain depend only on contracts and ports.

### Task 2: Add bounded auto-repair contracts and loop

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

**Interfaces:**
- `ValidationReport.adjustments -> list[ValidationAdjustment]`
- `ValidationAdjustmentExecutor.apply(state, report) -> AdjustmentExecutionResult`
- `IterationRecord` records iteration, issue fingerprint, parent checksum, adjustments, affected targets, before/after checks, and output checksum.

- [ ] Define the loop `EXECUTE -> VALIDATE -> diagnose -> apply adjustments -> earliest affected stage -> VALIDATE`, followed by `RECONCILE/DELIVER` only after validation passes or an explicit partial/HUMAN terminal.
- [ ] Bound repair to declared parameters and responsible targets; reject guessed coordinates, unsupported candidate expansion, source-layer mutation, free-form LLM state overwrite, and any direct EXECUTE trigger.
- [ ] Require max-round, duplicate-fingerprint, oscillation rollback, idempotency, and iteration-audit rules.

### Task 3: Add multimodal evidence contracts and stage ownership

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

**Interfaces:**
- `ImageArtifact` owns stored media metadata and checksum.
- `ImageEvidence` owns OCR/layout/legend/visual extraction with page/region refs.
- `VisualFact` owns typed subject/predicate/object observations and evidence refs.
- `VisualReview` owns post-execute visual findings and links to `ValidationAdjustment`.

- [ ] Define the media chain `upload -> ImageArtifact -> OCR/layout/legend/vision -> ImageEvidence/VisualFact -> L1/L2/L3 or GROUND evidence -> post-EXECUTE VisualReview -> VALIDATE`.
- [ ] Specify that reliable CRS/bbox/map references may assist GROUND, while vision remains evidence/scoring only and deterministic GIS remains authoritative.
- [ ] Require exact, ambiguous, and unresolved visual outputs to remain distinct; image/vision failure must use OCR/text/local evidence or route to HUMAN.
- [ ] Keep provider requests behind a media adapter with bounded crop/resize/detail/token budgets and audit only refs/hash/metadata, never full base64 in events.

### Task 4: Integrate Exa as an EXPLORE provider

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

**Interfaces:**
- `ExternalSearchRequest` includes query intent, normalized entities/aliases, source policy, allowed domains/categories, freshness, search mode, result limit, content mode, budget, parent refs, and idempotency key.
- `ExternalSearchResult` includes provider/request ID, resolved search mode, result records, source metadata, highlights/text refs, retrieval status, cost/latency, and provenance.
- `ExternalSearchPort` is the only domain-facing boundary; `ExaSearchAdapter` is infrastructure.

- [ ] Route external search only from `EXPLORE` after local KG, Bundle, reports, typed artifacts, and prior evidence have been queried or explicitly ruled out.
- [ ] Use Exa highlights for bounded agentic retrieval, request full text only when a typed evidence gap requires it, and preserve source URL/ID and grounding metadata.
- [ ] Permit structured Exa output only as an untrusted extraction draft; require source-backed claim normalization/conflict checks before a result enters `EvidenceBundle`.
- [ ] Make `DispatchPolicy` validate the external-search capability, source allowlist, freshness, cost/latency budget, parent refs, and retry/idempotency before emitting `DispatchCommand`.
- [ ] Define failure behavior as local evidence reuse, unresolved gap, or HUMAN review; do not silently substitute a general web result for missing spatial evidence.

### Task 5: Add migration, tests, and completion gates

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

- [ ] Add migration steps for contract freeze, adapter contract tests, auto-repair executor, media evidence chain, and Exa adapter before production caller cutover.
- [ ] Add tests for repair convergence/rollback, visual evidence target binding, image failure fallback, Exa provenance/caching/budget/idempotency, and external evidence rejection at GROUND/SELECT/EXECUTE boundaries.
- [ ] Update module completion to require real integration evidence for each enabled capability, immutable artifact lineage, replay idempotency, and explicit `GAP/PARTIAL/TARGET` status alignment with `10_IMPLEMENTATION_STATUS.md`.

### Task 6: Review the blueprint edit

**Files:**
- Review: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

- [ ] Re-read inserted sections and verify all new interface names have matching contract, migration, and acceptance references.
- [ ] Check balanced code fences, LF line endings, no accidental broad worktree edits, and keyword coverage for `ValidationAdjustment`, `ImageArtifact`, `VisualReview`, `ExternalSearchPort`, `ExaSearchAdapter`, and failure routing.
