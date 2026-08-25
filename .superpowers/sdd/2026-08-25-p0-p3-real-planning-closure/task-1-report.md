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

## Fix Round 1 — Reviewer Closure

Date: 2026-08-25

### Changed Files

- `backend/app/spatial/grounding/resolver.py`
- `backend/app/domain/ground/aggregate.py`
- `backend/app/domain/ground/candidate_domain_builder.py`
- `backend/app/contracts/spatial/grounding_contracts.py`
- `backend/tests/core/test_grounding_search_scope_boundary.py`
- `backend/tests/characterization/test_multi_source_geometry_contract.py`

### Reviewer Fixes

1. Search-scope fallback invariant

   Added an aggregate invariant that treats a `SearchScopeRef` with
   `candidate_materialization_allowed=False` as immutable retrieval-only state.
   The invariant is applied immediately after resolver output, before legacy L1
   anchor fallbacks, and again after those fallbacks.  Both anchor fallback paths
   are skipped for a blocked scope, and any regressed materializable fields are
   cleared before candidate processing.  The aggregate routes the result to the
   existing `search_scope_not_materialized` issue, so matching village-scope
   anchors cannot create a `CandidateSite` or candidate domain.

2. Exact KG-topology parcel preservation

   Removed the broad `final_bsms + parcel-derived bbox` conversion to
   `directional_bbox_scope`.  Bboxes derived from identifiable final BSMs remain
   refinement/provenance data; the final result retains `parcel_extent` or
   `parcel_set` semantics, preserving single-parcel and multi-parcel behavior.
   Bbox semantics are selected only when no final BSMs remain.

3. Reference-geometry authority gate

   `_authoritative_geometry_refs()` now rejects syntactically valid WKT unless
   the record has stable feature identity (`source_ref`, `source_feature_id`,
   `source_refs`, or `feature_bsms`) and a source snapshot from the explicit
   source snapshot or bundle snapshot.  Rejected records carry a diagnostic with
   the missing requirements, while legitimate source-backed fixtures retain
   their exact geometry through bundle snapshot metadata.

4. Downstream materialization guard

   `CandidateSite` now carries a backward-compatible
   `candidate_materialization_allowed` flag.  GROUND propagates the flag and
   the existing candidate-domain boundary rejects blocked candidates both from
   the typed field and from the serialized metrics fallback.  This keeps a
   future upstream fallback regression from entering `GroundedCandidateDomain`.

### Behavior Decisions

- A blocked search scope wins over legacy anchor BSMs, valid-looking anchor WKT,
  evidence geometry promotion, and any accidentally retained final fields.
- Exact parcel BSMs and exact multi-parcel resolutions remain materializable as
  parcel candidates; a derived bbox does not downgrade them to a directional
  search scope.
- Untrusted WKT is dropped with an auditable diagnostic rather than repaired or
  converted into executable geometry.
- No user-owned dirty files were modified or removed.

### Fix-Round Verification

Bounded focused command run from `backend/`:

```text
python -m pytest -o addopts='' tests/core/test_grounding_search_scope_boundary.py tests/core/test_evidence_graph_join.py::test_ground_resolver_uses_kg_topology_result_before_anchor_bundle_associations tests/characterization/test_multi_source_geometry_contract.py tests/core/test_ground_evidence_packet_bridge.py tests/core/test_evidence_packet_ground_selection.py::test_hazard_address_can_seed_natural_village_scope_from_related_parcel tests/core/test_evidence_packet_ground_selection.py::test_llm_selects_one_spatial_cluster_without_merging_distant_parcels tests/test_ground_parcel_alternatives.py::test_precise_multi_parcel_resolution_exposes_independent_parcel_alternatives tests/acceptance/test_real_spatial_stage_chain.py::test_real_spatial_stage_chain_preserves_subgeometry_lineage tests/characterization/test_real_source_line_grounding.py::test_real_source_road_line_reaches_ground_without_parcel_union -q --maxfail=1
```

Result: `24 passed`.

The exact KG-topology regression was included explicitly and passed.  A separate
bounded compatibility selection reached 9 passes before the unrelated
`test_real_source_road_id_survives_target_projection_before_ground` assertion
failed at TARGET_PROJECTION, before GROUND ran, with the existing admission
diagnostics `INTERVENTION_NOT_ADMITTED`,
`INTERVENTION_ADMISSION_LINEAGE_MISSING`, and
`INTERVENTION_ADMISSION_RECOMPUTE_FAILED`.  That target-projection issue was
not changed in this P0-A fix round.

The focused runs also emitted the existing pytest cache warning (`WinError 5`
when writing `backend/.pytest_cache`); it did not affect test execution.

## Fix Round 2 — GroundedAnchor Authority Closure

Date: 2026-08-25

### Changed Files

- `backend/app/domain/ground/aggregate.py`
- `backend/tests/core/test_grounding_search_scope_boundary.py`
- `.superpowers/sdd/2026-08-25-p0-p3-real-planning-closure/task-1-report.md`

### Remaining Reviewer Finding

The two legacy `GroundedAnchor` promotion paths in the aggregate could accept
syntactically valid WKT directly, even when the anchor had no stable identity
or source snapshot.  This allowed a resolver result with no authoritative
geometry to become executable through the anchor fallback.

### Fix and Behavior Decisions

- Added one shared `_grounded_anchor_authority` predicate/diagnostic used by
  both legacy promotion paths.  Acceptance requires stable anchor identity
  from `entity_ref`, `source_feature_id`, or `feature_bsm`, and an anchor-owned
  source snapshot from `l1_snapshot_ref`, `bundle_snapshot_digest`, or an
  available explicit `source_snapshot_ref`.  `source_layer` and optional
  source-binding fields are retained in the audit record but do not substitute
  for feature identity or a snapshot.
- An anchor with valid WKT, BSM evidence, or both but missing authority is
  fail-closed: neither fallback promotes its geometry/BSMs.  The diagnostic is
  retained in resolved provenance, `SpatialQueryEvidence.query_params`, and
  the unresolved issue detail, including the missing requirements and supplied
  identity/snapshot/source-binding values.
- Accepted exact anchors carry their existing feature BSM, source feature ID,
  entity, relation/fact references, L1 snapshot, bundle digest, and optional
  source-binding fields into `ResolvedSpatialRef` and `CandidateGeometry`.
- Search-scope blocking and the exact KG-topology parcel behavior from Fix
  Round 1 remain unchanged.  User-owned dirty files were preserved.

### Fix-Round Verification

Focused boundary command:

```text
python -m pytest -o addopts='' tests/core/test_grounding_search_scope_boundary.py -q --maxfail=1
```

Result: `8 passed`.

The new negative regression verifies that an unresolved, unblocked resolver
result plus valid WKT with empty identity/snapshot creates no candidate
geometry or candidate domain.  The companion compatibility regression verifies
that a sourced exact anchor remains executable and preserves its lineage.

Exact KG-topology regression:

```text
python -m pytest -o addopts='' tests/core/test_evidence_graph_join.py::test_ground_resolver_uses_kg_topology_result_before_anchor_bundle_associations -q --maxfail=1
```

Result: `1 passed`.

Combined bounded P0-A selection (including the boundary file and exact KG
regression): `26 passed` in `23.44s`.

### Concerns

- The existing pytest cache warning (`WinError 5` while writing
  `backend/.pytest_cache`) remains environmental and did not affect results.
- The unrelated TARGET_PROJECTION admission failure recorded in Fix Round 1
  remains outside P0-A scope; no new failure was observed in this fix round.

## Fix Round 3 — Feature-Level Anchor Authority and Resolver Lineage

Date: 2026-08-25

### Changed Files

- `backend/app/domain/ground/aggregate.py`
- `backend/tests/core/test_grounding_search_scope_boundary.py`
- `.superpowers/sdd/2026-08-25-p0-p3-real-planning-closure/task-1-report.md`

### Reviewer Finding and Fix

The Fix Round 2 authority predicate still treated a generic `entity_ref` as
feature identity.  That allowed a coarse village anchor with a snapshot and
valid WKT to pass even though its geometry granularity was `village_scope`.

- `_grounded_anchor_authority` now requires a genuine feature-level identity
  from `source_feature_id` or `feature_bsm`, explicit `exact_feature`
  granularity, and an anchor-owned source snapshot.  `entity_ref` remains part
  of the audit/lineage and does not get rejected when it is accompanied by
  feature identity and exact granularity; it is simply not sufficient by
  itself.  `source_layer` and optional source-binding fields remain auditable
  but cannot substitute for feature identity or exact granularity.
- Both legacy promotion paths continue to use the same fail-closed predicate.
  Accepted promotions now store the incoming resolver provenance path as
  `resolver_path` before setting `path="grounded_anchor"`, preserving lineage
  for both fallback branches.
- Search-scope blocking, downstream candidate-domain guards, exact sourced
  anchors, and exact KG-topology parcel behavior from prior rounds remain
  unchanged.

### Regression Coverage

- Retained the WKT-only negative and sourced exact-anchor positive tests.
- Added a critical middle-case regression: a valid WKT anchor with
  `entity_ref="entity:village:coarse"`, an L1 snapshot, no feature BSM/source
  feature ID, and `geometry_granularity="village_scope"` produces no
  executable candidate geometry or candidate domain and emits the missing
  identity/granularity diagnostic.
- Added a second-promotion-path regression asserting
  `provenance["path"] == "grounded_anchor"` and
  `provenance["resolver_path"] == "resolver:second-path"`.

### Fix-Round Verification

Focused boundary command:

```text
python -m pytest -o addopts='' tests/core/test_grounding_search_scope_boundary.py -q --maxfail=1
```

Result: `10 passed`.

Combined bounded P0-A selection, including the exact KG-topology regression,
search-scope and parcel safeguards, and the village-anchor contract test:
`29 passed` in `23.61s`.

### Concerns

- The existing pytest cache warning (`WinError 5` while writing
  `backend/.pytest_cache`) remains environmental and did not affect results.
- The unrelated TARGET_PROJECTION admission failure recorded in Fix Round 1
  remains outside P0-A scope.  User-owned dirty files were preserved.

## Fix Round 4 — Resolver Provenance Idempotence

Date: 2026-08-25

### Changed Files

- `backend/app/domain/ground/aggregate.py`
- `backend/tests/core/test_grounding_search_scope_boundary.py`
- `.superpowers/sdd/2026-08-25-p0-p3-real-planning-closure/task-1-report.md`

### Reviewer Finding and Fix

When an authoritative exact anchor had BSM evidence but no WKT, the first
legacy promotion branch ran and set `path="grounded_anchor"` while retaining
the original resolver path.  Because the second branch also runs for BSM-only
anchors, the next provenance merge derived `resolver_path` from the already
rewritten `path`, losing the original resolver lineage.

- `_grounded_anchor_provenance` now preserves an existing non-empty
  `provenance["resolver_path"]` and only falls back to the incoming
  `provenance["path"]` when no resolver path is already present.
- The final provenance can therefore retain
  `resolver_path="resolver:bsm-only"` while the materialization path remains
  `path="grounded_anchor"` after both promotion branches.
- Coarse-anchor authority checks, sourced exact-anchor acceptance,
  search-scope invariants, downstream materialization guards, and exact
  KG-topology parcel behavior remain unchanged.

### Regression Coverage

Added a BSM-only exact-anchor regression with `feature_bsm`,
`source_feature_id`, `exact_feature` granularity, source snapshots, no WKT,
and resolver provenance `path="resolver:bsm-only"`.  The test captures the
resolved object at candidate construction, confirms both promotion branches
produce a candidate, and asserts that the final path is `grounded_anchor`
while `resolver_path` remains `resolver:bsm-only`.

### Fix-Round Verification

Focused boundary command:

```text
python -m pytest -o addopts='' tests/core/test_grounding_search_scope_boundary.py -q --maxfail=1
```

Result: `11 passed`.

Combined bounded P0-A selection, including the exact KG-topology regression,
search-scope and parcel safeguards, the village-anchor contract test, and the
new BSM-only provenance regression: `30 passed` in `25.20s`.

### Concerns

- The existing pytest cache warning (`WinError 5` while writing
  `backend/.pytest_cache`) remains environmental and did not affect results.
- The unrelated TARGET_PROJECTION admission failure recorded in Fix Round 1
  remains outside P0-A scope.  User-owned dirty files were preserved.
