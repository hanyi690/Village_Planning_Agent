# Task 1 — Stabilize the global L1 union

Accept every globally legal typed fact in every dimension, while reporting a
dimension expectation mismatch as a soft diagnostic or rerouting hint. Handle
provider envelope/container variance at the shared adapter boundary and keep
single-record failures isolated. Verify a fresh run completes all 12 L1
dimensions and reaches L2/L3 before starting Task 2.

## Binding constraints

- Preserve unrelated dirty-worktree changes; do not reset, checkout, or
  overwrite existing user edits.
- Do not restore CurrentAsset, DemandRegisterRow, CoverageDecision, or any
  retired compatibility/register path.
- Keep a global typed L1 fact union. Dimension-specific expected types are
  soft diagnostics/routing hints, not a hard rejection of globally valid facts.
- Deterministic code owns IDs, units, CRS, geometry, topology, lineage, solver
  certificates; LLMs own semantic proposals and explanations.
- Add focused tests and record a fresh runtime checkpoint.

## Acceptance evidence

- A valid globally legal fact emitted under a non-preferred dimension is
  accepted and carries a soft mismatch diagnostic or rerouting marker.
- Provider JSON-string containers and one malformed record do not discard the
  entire dimension when the shared adapter can recover the other records.
- Focused L1 tests pass.
- A new real session completes all 12 L1 dimensions and reaches L2/L3. Do not
  start Task 2 until this evidence exists.
