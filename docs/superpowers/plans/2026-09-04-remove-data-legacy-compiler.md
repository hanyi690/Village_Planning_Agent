# Remove Legacy DATA Compiler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the obsolete DATA ingestion compiler package without breaking the active typed target-projection path.

**Architecture:** The spatial reference mapper remains owned by `target_projection`, where it consumes typed L3 interventions and emits closed spatial-reference specs. DATA ingestion keeps only source parsing, admission, normalization, and product publication. No import alias or fallback to the deleted compiler package is retained.

**Tech Stack:** Python 3, Pydantic, pytest, `apply_patch`, `rg`.

## Global Constraints

- Do not restore Bundle/BSM/DLBM or filename-based semantic inference.
- Do not delete the active document upload parsers under `data/ingestion/documents`.
- Keep the mapper's public functions and behavior unchanged during the ownership move.
- Verify no runtime import references the deleted package before physical deletion.

---

### Task 1: Move the active mapper to target projection

**Files:**
- Create: `backend/app/modules/target_projection/spatial_reference_mapper.py`
- Modify: `backend/app/modules/target_projection/requirement_compilation.py`
- Delete: `backend/app/data/ingestion/compiler/spec_mapper.py`

**Interfaces:**
- Consumes: typed `PlanningIntervention`, `EvidenceObservation`, `GroundedEntityBinding`, and source-feature bindings.
- Produces: the existing `map_intervention_to_spec()` and `map_interventions_to_specs()` functions with unchanged signatures and outputs.

- [x] Copy the implementation, change only its module ownership documentation, and update the sole production import.
- [x] Run target-projection/DATA tests and confirm no behavior change.

### Task 2: Physically delete unreferenced compiler history

**Files:**
- Delete: `backend/app/data/ingestion/compiler/__init__.py`
- Delete: `backend/app/data/ingestion/compiler/diagnostics.py`
- Delete: `backend/app/data/ingestion/compiler/provenance.py`
- Delete: `backend/app/data/ingestion/compiler/profiles/__init__.py`

**Interfaces:**
- Consumes: no active runtime callers, confirmed by repository-wide `rg`.
- Produces: no importable legacy compiler package or compatibility re-export.

- [x] Re-run the reference scan after the ownership move.
- [x] Delete only the exact unreferenced files; do not add a shim.

### Task 3: Align documentation and verify the repository

**Files:**
- Modify: `docs/design/DATA_EXECUTABLE_DESIGN.md`
- Modify: `docs/design/DATA_PRODUCTION_RUNBOOK.md`
- Test: `tests/test_data_p1_p2_docs.py`

**Interfaces:**
- Consumes: the new module path and deletion evidence.
- Produces: documentation that states target projection owns the mapper and DATA no longer exposes the compiler package.

- [x] Replace active implementation references to the deleted package while leaving historical plans as historical records.
- [x] Run `rg`, the full `python -m pytest tests -q` suite, `python -m compileall -q backend/app scripts tests`, `git diff --check`, and the production static gate.
