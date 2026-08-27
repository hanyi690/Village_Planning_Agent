# L1/L3 Planning-Structured Output Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make L1 the authoritative producer of typed, evidence-located current-state facts and L3 the authoritative producer of typed planning claims that GROUND can admit or defer, while preserving the human-readable report body at both layers.

**Architecture:** Raw session inputs are indexed into addressable source segments, but semantic interpretation is performed by the L1 model inside dimension-specific contracts. L1 emits a dual channel: `report_body` for people and typed observations/facts/register decisions for downstream code. L3 consumes the typed L1 snapshot plus L2 strategy and emits a second dual channel: `report_body` plus typed claims, parameters, relation requirements, objective/constraint refs, and explicit grounding requirements. Deterministic compilers validate lineage and route the claim to GROUND; neither layer fabricates GIS geometry.

**Tech Stack:** Python 3, Pydantic v2, existing structured LLM adapter, existing unified evidence retrieval, LangGraph state, pytest.

## Global Constraints

- `report_body` is mandatory for every successful L1/L3 dimension result and is persisted independently of structured extraction success.
- Only session-persisted input fields and explicit uploads enter L1; repository documents are never implicitly scanned or promoted.
- L1 may record current assets, demands, metrics, constraints, risks, relations, and places; it must not emit a future planning target or GIS candidate.
- L3 may emit planning semantics and typed relation/grounding requirements; it must not emit coordinates, BSMs, candidate geometries, or final parcel bindings.
- `source_fact_refs` and evidence locators are exact identities; unknown references fail closed and remain diagnostics.
- Dimension-specific scope controls which observation kinds and planning output families are valid; the loop is only a bounded delivery mechanism.

---

### Task 1: Add dimension-specific semantic contracts

**Files:**
- Create: `backend/app/domain/assessment/dimension_contracts.py`
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Modify: `backend/app/domain/program/worker.py`
- Test: `backend/tests/core/test_dimension_semantic_contracts.py`

**Interfaces:**
- `get_dimension_semantic_contract(dimension_key, layer) -> dict[str, object]`
- `render_dimension_semantic_contract(dimension_key, layer) -> str`
- Contracts identify allowed L1 observation kinds, required evidence fields, and L3 claim families/grounding inputs for each configured dimension.

- [x] Add the contract catalog for all configured L1 and L3 dimensions.
- [x] Include the rendered contract in both L1 and L3 system prompts.
- [x] Test that traffic requires network/endpoint evidence, public service requires facility/service evidence, ecology requires protection/restoration/overlay evidence, and socio-economic/wishes can remain non-spatial when no location is present.

### Task 2: Make L1 typed observations planning-consumable

**Files:**
- Modify: `backend/app/domain/assessment/observation_draft.py`
- Modify: `backend/app/data/ingestion/compiler/profiles/l1_observation.py`
- Modify: `backend/app/contracts/domain/l1_contracts.py`
- Test: `backend/tests/core/test_l1_planning_observation_contract.py`

**Interfaces:**
- Extend `L1ObservationDraft` with `observation_kind`, `semantic_type`, `attributes`, `value`, `unit`, `counting_basis`, `related_observation_ids`, and `constraint_refs`.
- Compile confirmed observations into provenance-rich `L1Fact` records, preserving source quote/segment refs and distinguishing spatial, demand, metric, constraint, and document facts.
- Keep `L1LocationFact` as the place-resolution projection; it is not the only fact producer.

- [x] Add schema tests for current asset, demand, quantitative metric, hard constraint, and relation observations.
- [x] Add deterministic fact compilation tests asserting stable fact IDs, typed attributes, values/units, and source lineage.
- [x] Ensure unverified observations remain out of authoritative fact records while their report body remains persisted.

### Task 3: Keep generic source handling and explicit register confirmation separate

**Files:**
- Modify: `backend/app/domain/assessment/input_register.py`
- Modify: `backend/app/domain/assessment/l1_extraction_loop.py`
- Modify: `backend/tests/core/test_l1_input_register.py`
- Modify: `backend/tests/core/test_l1_dimension_register_producer.py`

**Interfaces:**
- `build_l1_source_index` always creates generic segments and never emits semantic rows.  `current_assets`/`demands` are materialized only from an L1 typed draft that cites and quotes verified source segments.
- The L1 model confirms/registers rows against source segments; no fixed HTML/Markdown parser is the semantic authority.
- Segment text and character/line offsets must cover exactly the returned evidence; hard chunks cannot truncate their own quoted text.

- [x] Fix segment chunking/offset invariants.
- [x] Replace fixed explicit-ledger parsing tests with typed-draft/materialization tests and add arbitrary narrative/OCR/mixed-source tests.
- [x] Preserve exact duplicate-source diagnostics without counting aliases twice.

### Task 4: Extend L3 claim output with relation and grounding requirements

**Files:**
- Modify: `backend/app/domain/program/claim_draft.py`
- Modify: `backend/app/contracts/program.py`
- Modify: `backend/app/domain/program/claim_adapter.py`
- Modify: `backend/app/infrastructure/llm/prompts/detailed.py`
- Test: `backend/tests/core/test_l3_planning_output_contract.py`

**Interfaces:**
- Add provider-facing `spatial_requirements` containing semantic `relations`, `shared_resource_refs`, `network_refs`, and `required_input_refs`.
- Preserve it on `PlanningClaim` and project it into `PlanningIntervention.spatial_requirements`.
- Add `grounding_requirements` to identify candidate geometry, demand points, parcel membership, network snapshot, or topology evidence required before admission.

- [x] Test road connect/access relations, facility service/demand requirements, shared parcel coupling, and overlay/topology requirements.
- [x] Reject coordinate/BSM/geometry payloads at the L3 contract boundary.
- [x] Ensure claim admission still requires typed parameters, package identity, locator/evidence lineage, and role `spatial_intervention`.

### Task 5: Verify dual-channel persistence and downstream handoff

**Files:**
- Modify: `backend/app/domain/assessment/analysis_node.py`
- Modify: `backend/app/domain/program/worker.py`
- Modify: `backend/app/domain/program/aggregate.py`
- Test: `backend/tests/core/test_l1_l3_dual_channel_persistence.py`

**Interfaces:**
- L1 step reports, `ReportStore`, SSE, and L3 step reports retain `report_body` even when observations/claims are empty or diagnostic.
- L3 prompt receives typed L1 facts and dimension contract; L3 aggregate retains report provenance plus strict `PlanningClaimSet` output.
- Target projection receives relation and grounding requirement metadata without raw document parsing.

- [x] Add regression tests for valid structured output, empty structured output with valid report, and malformed structured output with diagnostic report.
- [x] Run focused L1/L3 suites and compile/import checks; the legacy simulated L3→GROUND fixture still needs migration to the strict project-package/source-binding contract.
- [x] Update the current design/status document with the resulting evidence and remaining GROUND gaps.

Implementation note: the loop is bounded delivery machinery only. The remaining
gap is provider/fixture coverage of complete typed facts and claims in a real
session, not another loop abstraction.
