# Task 1 Report — P0-A Search Scope Boundary

Date: 2026-08-25

## Summary

Implemented the P0-A boundary that separates coarse search scope from executable grounding candidates in the GROUND pipeline.

## Changed Files

- `backend/app/contracts/spatial/spatial_reference_contracts.py`
- `backend/app/spatial/grounding/resolver.py`
- `backend/app/domain/ground/aggregate.py`
- `backend/tests/core/test_grounding_search_scope_boundary.py`
- `backend/tests/core/test_evidence_packet_ground_selection.py`
- `backend/tests/acceptance/test_real_spatial_stage_chain.py`
- `backend/tests/test_ground_parcel_alternatives.py`

## Implementation Details

### 1. New explicit search-scope contract

Added `SearchScopeRef` and extended `ResolvedSpatialRef` with `search_scope`.

The contract carries:

- `scope_bsms`
- `bbox`
- `scope_type`
- `source`
- `reason`
- `candidate_materialization_allowed=False`
- provenance and missing-requirement diagnostics for follow-up retrieval/materialization

This keeps serialization backward-compatible because the new field is optional and defaults to `None`.

### 2. Resolver boundary changes

Updated `backend/app/spatial/grounding/resolver.py` so coarse results now land in `search_scope` instead of `final_bsms` / `feature_bsms` / `reference_geometries`.

Moved the following paths to `search_scope`:

- village cluster / gazetteer village scope
- evidence-derived natural-village scope from anchor packets
- village coarse fallback
- directional bbox / bbox parcel query scope
- flash mention coarse parcel scope

Precise paths still materialize normally:

- authoritative source geometries
- explicit parcel BSM references
- exact parcel / parcel-set identities
- LLM-selected exact packet identities

### 3. GROUND aggregate and candidate-domain boundary

Updated `backend/app/domain/ground/aggregate.py` so search scope:

- never builds `CandidateSite`
- never builds `CandidateGeometry`
- never creates a resolved `GroundedCandidateDomain`
- instead produces:
  - `SpatialQueryEvidence.query_params["search_scope"]`
  - `StageIssue(code="search_scope_not_materialized")`
  - readable problem/provenance diagnostics describing:
    - which scope was used
    - why materialization was blocked
    - which authority/source requirements are still missing

Added an explicit guard in `build_candidate_sites()` so search-scope-only resolutions return no candidates.

## Behavior Decisions

- Kept top-level `ResolvedSpatialRef.final_bsms` empty for coarse scope results, even when scope BSMs are known, to make the materialization boundary unambiguous.
- Kept coarse scope diagnostics in both `resolved.provenance` and the new `search_scope` payload so downstream retrieval and human review can see the scope without treating it as a candidate.
- Preserved exact-feature, exact-polygon, single-parcel, and multi-identifiable-parcel candidate behavior.
- Preserved existing unresolved behavior by surfacing search-scope-only outputs as explicit unresolved grounding issues rather than silently dropping them.

## Tests Added / Updated

### Added

- `backend/tests/core/test_grounding_search_scope_boundary.py`
  - coarse village fallback only creates `search_scope`
  - exact polygon candidate behavior unchanged
  - single parcel candidate behavior unchanged
  - multiple identifiable parcels still split into alternatives

### Updated

- `backend/tests/core/test_evidence_packet_ground_selection.py`
  - natural-village evidence scope now asserts `search_scope`
  - LLM-selected spatial-cluster village scope now asserts `search_scope`
- `backend/tests/acceptance/test_real_spatial_stage_chain.py`
  - added real-bundle assertion that coarse village scope does not materialize candidates
- `backend/tests/test_ground_parcel_alternatives.py`
  - clarified the regression case to use a precise multi-parcel `parcel_set` rather than a coarse village-scope surrogate

## Verification Run

Focused verification run completed successfully:

```text
pytest -o addopts='' backend/tests/core/test_grounding_search_scope_boundary.py backend/tests/core/test_evidence_packet_ground_selection.py::test_hazard_address_can_seed_natural_village_scope_from_related_parcel backend/tests/core/test_evidence_packet_ground_selection.py::test_llm_selects_one_spatial_cluster_without_merging_distant_parcels backend/tests/test_ground_parcel_alternatives.py::test_precise_multi_parcel_resolution_exposes_independent_parcel_alternatives backend/tests/acceptance/test_real_spatial_stage_chain.py::test_real_spatial_stage_chain_preserves_subgeometry_lineage -q
```

Result: `8 passed`

## Concerns

- The repo’s default `backend/pytest.ini` filters to `e2e` tests only, so focused core-file verification must override `addopts` to avoid deselection.
- A broader run of `backend/tests/test_ground_parcel_alternatives.py` still includes an unrelated pre-existing refinement expectation outside this boundary (`test_select_refinement_only_promotes_hard_feasible_parcel_and_keeps_lineage`). I did not widen this task into SELECT refinement behavior.
- User-owned dirty files were preserved and not modified:
  - `.codex/config.toml`
  - `.analysis/`
  - `backend/tests/acceptance/test_recorded_real_root_graph_replay.py`
  - `backend/tests/support/recorded_planning_provider.py`
