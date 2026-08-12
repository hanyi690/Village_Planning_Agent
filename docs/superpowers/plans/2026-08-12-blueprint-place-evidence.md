# Blueprint Place Evidence Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the backend blueprint explicitly preserve L1 semantic enrichment, place evidence indexing, reverse KG relation resolution, and GROUND integration.

**Architecture:** Keep EXPLORE as a horizontal evidence service, but define its place-resolution capability explicitly. L1 emits typed location facts; the evidence layer builds a versioned `PlaceEvidenceIndex`, expands directed and inverse KG relations, and returns a traceable `PlaceResolutionResult` to GROUND. LLM assistance remains bounded to ambiguous Top-K matching and cannot create entities, BSMs, or coordinates.

**Tech Stack:** Markdown architecture blueprint, typed Python/Pydantic contracts, KG/RDF projections, spatial grounding, deterministic scoring, LangGraph workflow gates.

## Global Constraints

- Evidence must carry source, version, provenance, and query trace.
- KG may return facts and relations but may not create final planning decisions.
- Unresolved or ambiguous place references must remain explicit and route to retry or HUMAN review.
- `祠堂@社前村`-style reverse location resolution must be an explicit acceptance case.
- The blueprint edit must use LF, 2-space indentation where code blocks apply, and minimal localized changes.

---

### Task 1: Add explicit place-evidence ownership

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

- [ ] Add place-resolution model/retrieval responsibilities under the target `evidence/` directory and state that this is a required capability, not an optional legacy helper.

### Task 2: Define the L1 → KG → GROUND contract

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

- [ ] Add `L1LocationFact`, `PlaceEvidenceIndex`, `PlaceResolutionResult`, relation evidence, directed/inverse relation expansion, and the `祠堂@自然村 → 自然村 geometry/BSM` flow.
- [ ] State that GROUND consumes the resolution result and SELECT remains the only final site-allocation decision owner.

### Task 3: Define verification and migration obligations

**Files:**
- Modify: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

- [ ] Add contract/integration/acceptance cases for exact names, aliases, reverse relations, conflicts, ambiguity, and unresolved references.
- [ ] Add the capability to the migration order and module completion definition.

### Task 4: Review the blueprint edit

**Files:**
- Review: `docs/design/14_BACKEND_MODULE_BLUEPRINT.md`

- [ ] Re-read all inserted sections, confirm the old capability is named explicitly, and run a diff/keyword check.
