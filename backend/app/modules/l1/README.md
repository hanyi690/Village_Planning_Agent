# L1 OBSERVE

## Ownership

`backend/app/modules/l1/` is the canonical application boundary for building
the current-state fact artifact. It answers what the village has, what is
observed, what is derived from typed inputs, and what remains uncertain. It
does not create planning objectives, targets, candidate geometry, scenarios,
approval input, or execution tasks.

## Public API

- `application.L1Application.run(state) -> L1RunResult`
- `application.L1Application.load(state) -> L1ObservationSnapshot | None`
- `application.run_l1(state) -> L1RunResult`
- `projections.L1ProjectionBuilder.build_context(...) -> L1InputContext`
- `projections.L1ProjectionBuilder.build_dimension_input(...) -> L1DimensionInput`

`state` is the workflow control-plane mapping. The result is typed: it carries
the validated `L1ObservationSnapshot` and immutable `ArtifactRef` values for
`l1_snapshot` and `l1_gate`. The workflow may receive only
`L1RunResult.to_state_patch()` as a state update.

## Input and output

The input identity requires `run_id`, `session_id`, `branch_id`, and a frozen
`context_version`/`context_ref`. The aggregate reads the session-owned source
index, report inputs, Bundle/GIS/KG evidence, and bounded observation outputs.
The authoritative output is `app.contracts.l1.l1_contracts.L1ObservationSnapshot`:

- `fact_records` are typed facts with `source_refs`, `source_span`, semantic
  type, value, and derivation metadata;
- `location_mentions` are semantic work items only and contain no geometry;
- the provider may emit bounded `spatial_mentions` with names, roles, scopes,
  relations, and source ids so each location becomes an independent GROUND
  input; these fields never include coordinates, BSMs, candidates, or geometry;
- `evidence_gaps`, diagnostics, conflicts, and provenance remain explicit;
- `evidence_requirements` are generated for downstream evidence completion.

KG/Bundle-derived facts must retain an inferred/derived classification and may
not be promoted to direct document observations.

## Persistence and recovery

The facade requires the existing CAS artifact runtime to commit `l1_snapshot`
and `l1_gate`. It immediately reloads `l1_snapshot` through
`load_artifact` before returning. The L1 observation loop persists bounded
source-page cursors in its step records; recovery resumes from those cursors
and keeps input digests stable. A missing or invalid artifact reference is a
hard boundary error, not an empty successful result.

## Internal implementation boundary

The observation aggregate, bounded extraction loop, source index, fact
projection, validation, and gate logic now live in this directory. The
workflow only calls `application.run_l1()` and receives the compact state
patch; it does not call the former assessment package. Shared retrieval and
context construction are supplied by the centralized runtimes.

## Forbidden dependencies and behavior

- Do not import L2/L3/target projection/GROUND/SELECT/EXECUTE modules.
- Do not create geometry, candidate membership, formal scenarios, approval,
  execution plans, or planned state.
- Do not use report prose as a substitute for typed source-backed facts.
- Do not persist an empty object or a mock-only result as `L1ObservationSnapshot`.
- Do not expose raw report bodies in downstream semantic projections.

## Verification

The focused verification path is a runtime probe using a real local
`SessionDataSnapshot` and temporary CAS root:

1. bootstrap a session and run the L1 workflow aggregate;
2. assert the returned `L1RunResult.snapshot` has typed source-backed facts;
3. reload it from `artifact_refs.l1_snapshot` and compare its semantic digest;
4. pass the reloaded artifact into the L2 input projection;
5. inspect the persisted step cursor for bounded recovery metadata.

Use `python -m compileall -q backend/app` and `git diff --check` for the
lightweight repository gate. The removed historical test tree is not a gate.
