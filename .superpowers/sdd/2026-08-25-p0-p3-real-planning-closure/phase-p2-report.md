# Phase P2 Report — Demand/network products, deterministic evaluators, and master coordination

Date: 2026-08-25

## STATUS

Implemented the bounded P2-A/P2-B closure slice. The change is limited to
typed demand/network snapshot products, deterministic relation evaluation
coverage, an independent bounded master coordinator, SELECT completeness
handling, and focused tests.

## IMPLEMENTED

- `DemandSnapshot` now carries source binding, CRS, time slice, version,
  declared/derived total demand, availability, diagnostics, and stable digest.
  Missing source binding/version is pending; inconsistent declared totals are
  rejected.
- Added typed `NetworkRef`/`NetworkSnapshot` plus node/edge refs and a
  deterministic builder. Missing source binding, version/digest, nodes, or
  edges produces blocked readiness rather than an empty successful network.
- `RelationEvaluationContext` now exposes typed demand and network refs while
  retaining compatibility with the existing immutable network graph adapter.
- The default relation registry covers `near`, `within`, `adjacent`,
  `intersects`, `overlaps`, `contains`, `connect`, `access`, and `serve`.
  Topology/distance results retain typed measurement, trace, evaluator version,
  source snapshot refs, and input status; unsupported inputs remain deferred or
  not evaluable.
- Added `master_coordinator.py` with deterministic bounded enumeration across
  stable target/candidate/project IDs and parcel/network/demand capacity. It
  returns `feasible`, `bounded_infeasible`, or `deferred` certificates and
  never merges local choices into a recommendation by itself.
- SELECT now requires a complete `feasible` solver certificate for a
  recommendation; bounded/non-complete certificates are not recommendation
  authority.
- Preserved P1 target/project lineage fields and existing subproblem contracts.

## TESTS

Passed:

```text
python -m pytest -c backend/pytest.ini -o addopts='' \
  backend/tests/core/test_p2_closure_contracts.py \
  backend/tests/core/test_relation_geometry_evaluators.py \
  backend/tests/core/test_select_gate_deferred_targets.py \
  backend/tests/core/test_solver_subproblem_decomposition.py -q --maxfail=1

32 passed, 1 pre-existing PytestCacheWarning

python -m compileall -q \
  backend/app/domain/demand/facility_demand_model.py \
  backend/app/domain/network \
  backend/app/domain/relations \
  backend/app/domain/allocation/master_coordinator.py \
  backend/app/domain/allocation/select_gate.py \
  backend/tests/core/test_p2_closure_contracts.py

passed

git diff --check
passed
```

## CONCERNS

- The existing typed-road single-target regression
  `backend/tests/core/test_network_connectivity_relations.py::test_typed_road_claim_reaches_network_backend_without_choice_fallback`
  still produces an `unresolved`/empty scenario in the current working tree,
  so it was not claimed as passed and no broad solver-gate relaxation was
  introduced in P2. This remains a follow-up concern for the existing
  network-path fixture.
- The environment cannot write `backend/.pytest_cache`; this only emits the
  known PytestCacheWarning.
- Full repository compile was not run because P1 documents pre-existing
  syntax-invalid recorded scripts under `.run-tmp/logs/`; changed boundaries
  compiled successfully.
- User-owned dirty files were not staged or modified: `.codex/config.toml`,
  `.analysis/`, recorded replay/support files, the planning document, and
  `phase-p1-review-round-1.md`.

## Fix Round 1 — 2026-08-25

### STATUS

Implemented the minimum hard fixes requested by the P2 review. SELECT now
compiles the typed `SolverSubproblemPlan` through the production
`coordinate_master_plan` boundary, binds its `MasterCertificate` into the
`SolverCertificate`, and clears formal feasible/Pareto/recommended IDs when
master coordination is not feasible. Bounded solver products and parent
subproblem merges retain only provisional partial scenarios and cannot expose
formal recommendation IDs.

### FIXES

- Fail-closed demand/network readiness: empty demand remains pending and never
  ready; typed network snapshots validate source binding, CRS, digest, node
  references, and edge endpoints. Typed evaluators reject incomplete network or
  demand inputs; legacy adapters are accepted only when they expose an
  explicit routing callable.
- Runtime and solver-readiness relation registries now share one default
  registry covering `contains`, `within`, `intersects`, `overlaps`, and
  `access`/`serve` aliases.
- Hard relation factors with missing/pending input status cannot return
  `satisfied`.
- Typed-road single-target selection now reaches the explicit
  `network_relation_bounded` backend for the existing line/road-corridor
  fixture; no generic fallback was added.
- Bounded certificates are contract-incompatible with formal scenario IDs;
  bounded child alternatives are retained for parent materialization only.

### TESTS

```text
P2 focused: 33 passed, 1 pre-existing PytestCacheWarning
typed-road regression: 1 passed, 1 pre-existing PytestCacheWarning
```

### CONCERNS / NOT COVERED

- No full-repository scan or full test suite was run by design. The production
  SELECT integration was covered by the code boundary and contract behavior,
  but no new end-to-end workflow fixture was added beyond the focused unit
  coverage.
- Existing user dirty files remain untouched and are not part of this Fix
  Round 1 commit.
