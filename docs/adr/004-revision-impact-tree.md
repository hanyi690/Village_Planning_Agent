# ADR-004: Revision Impact Tree

## Status
Proposed

## Context
The revision impact tree — the wave-ordered set of dimensions that must be
re-run when one dimension is revised — has two representations:

- `revision_impact_tree` — a TypedDict-shaped `Dict[int, List[str]]` stored in
  `AgentState` (`backend/app/workflow/plan_state/state.py`), owned by the
  plan state reducer and consumed by `completion_node.py`, the worker modules
  (`l1_observe/analysis_node.py`, `l2_strategize/worker.py`,
  `l3_plan/worker.py`), and the conversation router (`edges.py`).
- `get_impact_tree_compat(dimension_key)` — a function in
  `backend/app/config/dependency.py:149` that recomputes the same
  wave-structured tree on demand from dimension dependency config. It is
  called from `session_routes.py:593`, `edges.py:70`, and `dependency.py:365`.
  There is also a non-compat `get_impact_tree` (line 84) whose semantics differ.

No typed `RevisionImpactTree` model exists yet; the wave tree is currently
passed around as an untyped `Dict[int, List[str]]`, and the `_compat` function
duplicates the wave computation in a way that can diverge from the canonical
dependency config.

## Decision
The typed `RevisionImpactTree` is the canonical model. It is a
`Dict[int, List[str]]` mapping wave number to the list of dimension keys that
depend (transitively) on the revised dimension, computed with the
"max(dependency wave) + 1" staging rule (see `get_impact_tree_compat`).

It is owned by the plan-state module and generated once when a revision is
submitted (stored in `AgentState["revision_impact_tree"]`). It is consumed by
the completion node, the worker modules, and the conversation router.

`get_impact_tree_compat` is removed from the runtime path. Runtime consumers
read the pre-computed `RevisionImpactTree` from state instead of recomputing
it on demand. The single computation of the tree lives in one owned function;
the `_compat` variant is eliminated in favor of this one canonical
implementation.

## Required Fields
`RevisionImpactTree` (`Dict[int, List[str]]`):
| Field (key) | Type | Unit | Required |
|---|---|---|---|
| wave number | int | wave index | required (key) |
| dimensions per wave | list[str] | dimension key | required (value) |

Invariants:
- The target (revised) dimension itself is Wave 0 and excluded from the tree.
- Each downstream dimension appears in exactly one wave.
- Wave N = max(wave of its dependencies) + 1; baseline dimensions count as
  Wave 0; unresolved (cyclic) dimensions fall back to Wave 1.

## Classification
Computation intermediate. The impact tree is a derived ordering of affected
dimensions for driving revision execution — not a real-world domain fact and
not a render view.

## Migration Boundary
The single entry point for old data conversion is the revision-submission
boundary. When a revision is submitted, the canonical `RevisionImpactTree` is
computed once and stored in state. Any legacy code path that calls
`get_impact_tree_compat` in the middle of the pipeline is migrated to read the
pre-computed tree from state.

## Consequences
What breaks:
- Callers of `get_impact_tree_compat` (`session_routes.py`, `edges.py`,
  `dependency.py`) must read the pre-computed tree from state instead.
- Any consumer that mutates the tree mid-pipeline must be reconciled with the
  reducer (`_preserve_impact_tree`).

What becomes easier:
- One canonical wave computation; no risk of divergence between `_compat` and
  the owned implementation.
- Runtime consumers read a stable, pre-computed value from state.
- The impact tree is typed and testable independently.