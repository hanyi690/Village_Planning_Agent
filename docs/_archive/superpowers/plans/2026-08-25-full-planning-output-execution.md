# Full Planning Output Execution Plan

## Goal

Make a fresh run produce complete, source-backed planning layers through the
frontend. LLM drafts may be semantically incomplete, but no valid intent may
silently disappear; GROUND, SELECT, EXECUTE, VALIDATE, RECONCILE, and DELIVER
must remain evidence- and certificate-bound.

## Global Constraints

- Preserve unrelated dirty-worktree changes; do not reset, checkout, or
  overwrite existing user edits.
- Do not restore CurrentAsset, DemandRegisterRow, CoverageDecision, or any
  retired compatibility/register path.
- Keep a global typed L1 fact union. Dimension-specific expected types are
  soft diagnostics/routing hints, not a hard rejection of globally valid facts.
- L3 may emit semantic intent and typed prerequisites, never coordinates, WKT,
  GeoJSON, BSM identities, final candidates, or solver certificates.
- Missing demand, network, entity, geometry, or evidence inputs are explicit
  pending/blocked states, never fabricated values and never silent omissions.
- `infeasible` is reserved for a complete model with a solver proof. Missing
  prerequisites use `blocked` or `unknown`.
- Deterministic code owns IDs, units, CRS, geometry, topology, lineage, solver
  certificates, approval, and atomic execution. LLMs own semantic proposals,
  explanations, and alternatives.
- Every task adds focused tests and a fresh runtime verification checkpoint.

## Tasks

### Task 1: Stabilize the global L1 union

Accept every globally legal typed fact in every dimension, while reporting a
dimension expectation mismatch as a soft diagnostic or rerouting hint. Handle
provider envelope/container variance at the shared adapter boundary and keep
single-record failures isolated. Verify a fresh run completes all 12 L1
dimensions and reaches L2/L3 before starting Task 2.

### Task 2: Execute PlanningTaskGraph prerequisites in GROUND

Make the task graph an executable DAG with lifecycle states and typed artifact
bindings. Compile every relation template into the necessary endpoint/entity,
demand, network, constraint-geometry, candidate, solver, and validation
prerequisites. GROUND must schedule and resolve/defer tasks instead of merely
turning them into generic evidence requirements. Verify a fresh run reaches
SELECT with task states beyond `planned`.

### Task 3: Enforce solver readiness and certificate semantics

Do not call a solver for incomplete subproblems. Preserve feasible child sets
when other children are blocked, distinguish blocked/unknown from proven
infeasible, and attach interpretable constraint/assumption conflict groups to
true infeasibility. Verify a fresh run produces a complete feasible Scenario or
an evidence-backed unsat explanation.

### Task 4: Complete mandatory output accounting and frontend delivery

Add a dynamic mandatory output-family manifest and make delivery classify every
family as materialized, approved_not_applicable, deferred_with_evidence, or
blocked. Preserve approval, atomic execution, validation, reconciliation, CAS
lineage, and frontend visibility. Verify three new sessions: current village,
data-sparse village, and a mixed road/facility/shared-parcel/protection case.

