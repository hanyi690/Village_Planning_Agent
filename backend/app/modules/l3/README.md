# L3 PLAN

This module owns claim meaning, normalization, validation, and deterministic
`PlanningProgram` aggregation.  It consumes L1/L2 artifact references and
publishes a reloaded `PlanningProgram` for `TARGET_PROJECTION`.

Retriever choice, context assembly, schema parsing, and artifact storage remain
owned by the shared infrastructure runtimes.

## Output contract

`PlanningProgram` is the authoritative L3 artifact. Claims are normalized into
the closed planning vocabulary and retain fact/evidence references, lineage,
uncertainty, dependencies, and pending/deferred dispositions. L3 may describe
what should be planned, but it cannot emit final geometry, candidate ids,
scenarios, approval input, or execution tasks.

`L3Application.run()` requires a reloaded, persisted `l2_gate` with
`passed=true` in addition to the `l1_snapshot` and `l2_strategy` refs. It then
persists the program and gate and reloads the program before returning. The
TARGET_PROJECTION facade consumes only this typed artifact and its reference.
The L2 pass may be partial: unresolved evidence remains in the upstream
artifact and pending recovery requests, and is never treated as a confirmed
fact. A program containing claims but no typed interventions is also a valid
partial L3 output; it advances as pending claim input so
`TARGET_PROJECTION` can produce non-executable grounding work instead of
forcing L3 to invent complex parameters or geometry.

## Internal implementation map

- `claim_generation.py`: bounded rough claim schema and generation.
- `claim_normalization.py`: closed-set normalization and unit handling.
- `claim_validation.py`: lineage, vocabulary, and failure validation.
- `reasoning.py`: bounded L3 semantic transactions.
- `aggregation.py` and `assembler.py`: deterministic program assembly.
- `classification.py`: explicit HUMAN classification decision boundary for
  unresolved polygon/parcel targets; it is not an automatic LLM producer.

Evidence gaps remain explicit on the program. Resolvable gaps are routed to
the shared Evidence/context runtime or a bounded L3 revision; they are not
silently filled with spatial assumptions.

## LLM output boundary

The L3 provider call uses `L3RoughClaimOutput`, not `PlanningClaim` or
`PlanningProgram`. One call may return a bounded list of rough semantic
claims, but each item contains only claim family, statement, role, human
location hints, closed-set lineage references, grounding requirements, and
uncertainty. The provider wire schema has no quantity, area, capacity,
category-specific parameter block, project package, target identity, source
binding, candidate, BSM, coordinate, geometry, scenario, or execution field.

The output model is closed (`extra="forbid"`). An item containing an unknown
or complex field is quarantined with a diagnostic; it is never copied into the
authoritative claim. `rough_claim_to_planning_claim_draft()` only adapts the
accepted rough semantics into the existing deterministic normalizer. Missing
complex values remain missing and therefore produce a pending/deferred L3
disposition or a later structured-input requirement. They are not invented by
L3 or by the LLM.

The aggregation boundary repeats this check when reloading the persisted
`PlanningClaimSet`. A stale or manually substituted report containing a
quantity, parameter block, target/parcel binding, project package, or geometry
surrogate is quarantined before it can become a `PlanningProgram` input.

The L3 aggregate has no post-assembly LLM rewrite. Classification is an
explicit HUMAN decision boundary after the program gate, and typed values are
applied only through the workflow's closed-set decision handler. The
human-facing summary is deterministic display text assembled from validated
claims; L3 makes no second provider call to paraphrase, repair, or classify the
authoritative program.
