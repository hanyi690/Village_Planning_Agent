# GROUND

GROUND owns two related but independent entry points.  L1 does not pass
through `TARGET_PROJECTION` just to resolve a place name.

```text
L1Snapshot.LocationMention
        -> GROUND location resolution
        -> l1_observations + l1_bindings

PlanningProgram
        -> TARGET_PROJECTION -> GroundingRequest
        -> GROUND planning-target grounding
        -> GroundedPlanningProblem
```

The first entry point is exposed by
`GroundApplication.materialize_l1_locations()`.  Each mention first becomes a
typed spatial requirement and is retrieved through the unified
`modules.evidence.EvidenceFacade`; GROUND then performs current-context
scope/relationship expansion, bounded candidate pagination, closed-set
reasoning and deterministic source validation.  It may return exact, feature-set,
inferred-scope, ambiguous or unresolved bindings.  Only an existing source
entity/feature can receive a canonical identity; an LLM alias is never an ID.
Unresolved work items are persisted with their query trace and remain eligible
for later GROUND iterations without blocking L2/L3 progression.

`backend/app/modules/ground/` owns spatial grounding. It turns the typed
TARGET_PROJECTION result into resolved references, evidence bindings,
validated candidate sites, constraints, and a `GroundedPlanningProblem`.

## Public boundary

- `application.GroundApplication.run(state) -> GroundRunResult`
- `application.GroundApplication.materialize_l1_locations(state) -> refs`
- `application.GroundApplication.load(state) -> GroundingResult`
- `application.run_ground(state) -> GroundRunResult`
- `projections` contains the bounded input/output projection for callers.
- `ports` defines the provider-facing spatial capabilities.

The planning-target input must contain the canonical
`artifact_refs.target_projection` and a frozen context version. The result
carries `grounding_result` and `ground_gate` references. The independent L1
location input requires the current `l1_snapshot`; it produces the
`l1_observations` and `l1_bindings` sidecars instead of a planning problem.
For either entry point, a missing source, invalid reference, unresolved target,
or unverified geometry remains an explicit pending/deferred/unresolved finding;
it is never converted into a successful candidate. The planning ground gate
may still pass a partial result with `passed_with_unresolved_grounding` so
SELECT can consume the typed problem and produce a diagnostic or deferral.
Only trusted candidates are eligible for selection; a gate pass never promotes
an unresolved target or geometry into an executable candidate.

## Evidence-driven reasoning loop

GROUND does not make a single LLM call and then freeze the answer. For each
entry point it runs a bounded target/observation-scoped loop:

```text
current source snapshot
  -> EvidenceFacade retrieval + complete candidate pages
  -> deterministic scope/relationship/geometry validation
  -> closed-set LLM semantic selection or abstention
  -> unresolved/ambiguous targets only
  -> supplemental EvidenceFacade wave
  -> rebuild candidates and ask the LLM again
```

The default upper bound is `GROUND_MAX_RECOVERY_ROUNDS` (capped by the
application at three). A wave stops early when every target is closed or when
the candidate/relationship/source packet is unchanged. Thus a newly returned
source feature, KG relation, GIS locator or L1 binding can change a target from
unresolved/ambiguous to resolvable, and that transition is recorded in the
`ground_resolution_iteration` trace. The L1 sidecar records the analogous
rounds in `l1_spatial_resolution.iterations`.

The model's reasoning is deliberately semantic and closed-set: it can compare
names, aliases, roles, source spans, L1 facts, KG topology and spatial evidence
already present in the candidate cards, then select an existing candidate or
abstain. It cannot create an ID, BSM, coordinate, WKT, geometry, parcel
membership or execution parameter. Deterministic source and geometry checks
remain authoritative after every model decision.

Each iteration also persists target/mention status transitions, the items that
became resolvable, candidate-set/input digests, and the typed
selected/ambiguous/abstain decision. The reason is audit context only; the
authoritative transition is accepted only after the current source and spatial
constraints validate the selected candidate.

## Implementation ownership

`stage.py` contains the production stage orchestration. The neighboring files
own reference resolution, iterative resolution, evidence binding, candidate
construction, constraint checks, problem construction, reasoning, and gate
validation. `GroundedPlanningProblem` is the SELECT input and is the only
place where candidate membership and spatial constraints become solver input.

GROUND requests evidence through `modules.evidence.EvidenceFacade`; it may
not import a Bundle/KG/Report retriever or choose a provider directly. Pending
claim intake may be resolved against the current L1 snapshot to produce
candidate-only or unresolved records, but it cannot fill L3's complex
intervention parameters or become an executable target. LLM reasoning can
select from retrieved candidates, but deterministic spatial validation owns
identity, membership, and geometry validity.

## Recovery and verification

The stage persists its result and gate through the CAS artifact runtime. The
iterative resolver records bounded progress and can resume from the current
state without rebuilding an untrusted geometry. Verify the boundary without
the retired test suite with:

```text
python -B -m py_compile backend/app/modules/ground/reference_resolution.py
git diff --check
```

The full runtime probe must use a fresh current session and a real
`GroundingRequest`; historical sessions and test fixtures are not valid
evidence of this boundary.
