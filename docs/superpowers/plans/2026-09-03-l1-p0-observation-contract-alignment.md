# L1 P0 Observation Contract Alignment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make L1 OBSERVE a canonical DATA/Evidence/WM observation boundary before any real LLM vertical test, with no retired L1 compiler or location aliases.

**Architecture:** DATA and Evidence provide frozen, source-addressable inputs. L1 accepts bounded structured observations, validates source spans deterministically, quarantines invalid rows, emits typed facts/mentions/requirements/conflict groups, and persists one `L1ObservationSnapshot`. L1-GROUND remains the only binding boundary; WM remains the only current-assertion writer.

**Tech Stack:** Python 3, Pydantic v2, LangGraph workflow state, CAS artifacts, pytest.

## Global Constraints

- Follow `docs/design/01_CONTRACTS_AND_INVARIANTS.md`: `L1FactRow`, `L1LocationMention`, `L1RelationMention`, source-span validation, conflict groups, and explicit gaps are separate contracts.
- Follow `docs/design/acceptance/04_l1_acceptance.md`: observation may be persisted before grounding; ambiguous/provider failure must remain a gap; L2/L3 must not consume raw unvalidated rows.
- Follow `docs/design/L1_GROUND_EXECUTABLE_DESIGN.md`: L1 emits observation and grounding work items; L1-GROUND emits proposals only; neither stage directly writes current WM.
- Remove retired L1 report compiler and compatibility aliases instead of preserving historical persisted shapes.
- Do not implement `L1ProductManifest`, post-commit finalization, or real external LLM execution in this P0 task; those remain later stages.

---

### Task 1: Canonicalize the L1 observation contracts

**Files:**
- Modify: `backend/app/contracts/l1/l1_contracts.py`
- Modify: `backend/app/infrastructure/context_runtime/runtime.py`
- Modify: `backend/app/workflow/layers/context_bootstrap.py`
- Modify: `backend/app/modules/ground/application.py`
- Modify: L1/L2/L3 consumers that import or name `L1Snapshot`/`location_facts`
- Test: `tests/test_llm_table_protocol.py` and relevant L1 contract tests

**Interfaces:**
- Produces: `L1ObservationSnapshot`, `L1Fact`, `LocationMention`, `LocationMentionDraft`, and `L1ConflictGroup` as canonical observation contracts.
- Removes: `L1Snapshot`, `location_facts`, flat `village_scopes`/`place_scopes` translation, and `L1LocationFact`/`L1SpatialMention` aliases.

- [x] **Step 1: Write failing canonical-name and alias-rejection tests**
- [x] **Step 2: Rename the observation product and migrate consumers**
- [x] **Step 3: Remove old field/property/type compatibility paths**
- [x] **Step 4: Run L1/GROUND/L2/L3 contract tests**

### Task 2: Persist source-span validation and quarantine decisions

**Files:**
- Create: `backend/app/contracts/l1/validation_contracts.py`
- Create: `backend/app/modules/l1/source_span_validation.py`
- Modify: `backend/app/modules/l1/context.py`
- Modify: `backend/app/contracts/l1/l1_contracts.py`
- Modify: `backend/app/modules/l1/observation_draft.py`
- Test: `tests/test_l1_observation_contracts.py`

**Interfaces:**
- Produces: `SourceSpanValidationReport` with valid/invalid status, source snapshot/ref, span ref, quote digest, and fact/observation ref; `L1QuarantineRecord` with row digest, dimension, reason, validation errors, model call ref, and page ref.
- Consumes: bounded `L1PlanningFactDraft` rows and `L1SourceIndex` segments.

- [x] **Step 1: Add status and quarantine contract tests**
- [x] **Step 2: Implement deterministic source-span report generation**
- [x] **Step 3: Attach reports and quarantine records to the dimension output and snapshot**
- [x] **Step 4: Verify invalid rows never enter authoritative facts**

### Task 3: Remove the retired report compiler and aggregate structured observations directly

**Files:**
- Modify: `backend/app/modules/l1/facts.py`
- Modify: `backend/app/modules/l1/aggregation.py`
- Delete: `backend/app/data/ingestion/compiler/core.py`
- Delete: `backend/app/data/ingestion/compiler/profiles/l1_observation.py`
- Modify: `backend/app/data/ingestion/compiler/__init__.py`
- Modify: `backend/app/data/ingestion/compiler/profiles/__init__.py`
- Modify: `backend/app/modules/l1/review.py`
- Test: `tests/test_llm_table_protocol.py`

**Interfaces:**
- Produces: a direct structured-observation-to-`L1ObservationSnapshot` projection; display report remains a projection only.
- Removes: `compile_dimension_report` and `compile_l1_observation` from the active and exported surface.

- [x] **Step 1: Add a direct typed observation projection test**
- [x] **Step 2: Implement fact/mention conversion from semantic observations**
- [x] **Step 3: Change aggregation to consume `output.semantic`, never report prose**
- [x] **Step 4: Delete the retired compiler and update documentation/tests**

### Task 4: Add minimal formal conflict groups and strict gate semantics

**Files:**
- Modify: `backend/app/contracts/l1/l1_contracts.py`
- Modify: `backend/app/modules/l1/aggregation.py`
- Modify: `backend/app/modules/l1/gate.py`
- Modify: `backend/app/modules/l1/review.py`
- Test: `tests/test_l1_observation_contracts.py` and existing gate tests

**Interfaces:**
- Produces: `L1ConflictGroup` rows with comparable identity, unit, counting basis, conflict kind, and `OPEN/RESOLVED/REQUIRES_EVIDENCE/REQUIRES_HUMAN` status.
- Gate rule: `partial` or actionable required Evidence gaps never produce `passed=True`; conflicts and source-span failures remain explicit recovery/human routes.

- [x] **Step 1: Add conflict-group construction tests**
- [x] **Step 2: Emit deterministic groups for incompatible comparable facts**
- [x] **Step 3: Correct gate documentation and enforce source-span/quarantine blockers**
- [x] **Step 4: Run complete deterministic L1 P0 verification**

### Task 5: Final audit and commit

- [x] **Step 1: Scan for retired L1 names and compiler imports**
- [x] **Step 2: Run compile/import, focused tests, and full tests**
- [x] **Step 3: Review staged diff and preserve unrelated user documentation edits**
- [x] **Step 4: Commit the completed L1 P0 alignment**

## Self-review

- `L1ObservationSnapshot` is observation-only and does not contain binding or planning geometry.
- `L1Fact`, `LocationMention`, and future binding outputs have separate identities.
- Source validation and quarantine are persisted, not reduced to log strings.
- Evidence requirements are emitted by L1; Evidence owns acquisition and sufficiency.
- Conflict groups are a minimal diagnostic/recovery product; supersedes/version graphs remain deferred.
- No direct L1/GROUND write to current WM is introduced.
