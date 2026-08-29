# ADR-005: Legacy Artifact Migration Boundary

## Status
Proposed

## Context
Whenever a checkpoint is loaded into the runtime, legacy artifact references
must be unified into a single canonical map. This is done by
`migrate_legacy_artifacts(state)` in
`backend/app/infrastructure/artifacts/runtime.py`, which builds a unified
`artifact_refs` map by recognizing legacy field names (`l3_program_ref`,
`grounding_result_ref`, `site_selection_ref`, `parcel_changeset_ref`,
`planned_state_ref`, `validation_report_ref`, `reconciliation_report_ref`) and
copying them into the canonical keys.

It is currently called from multiple runtime node sites:
- `backend/app/workflow/graph.py` inside
  `_load_ref_artifact`, which itself is invoked from `post_l3_main_nodes` — a
  runtime node.
- `backend/app/workflow/layers/context_bootstrap.py` inside
  `_hydrate_l1_spatial_facts`.

Calling the migration inside runtime nodes means legacy conversion logic is
scattered through the executing graph, and the boundary between "old data" and
"canonical data" is not a single, auditable point.

## Decision
`migrate_legacy_artifacts` is called only at the checkpoint-import boundary,
never inside runtime nodes. The conversion of legacy field names into the
canonical `artifact_refs` map happens exactly once when a checkpoint is
imported, before any runtime node executes.

The canonical map produced is `artifact_refs` — the single store of artifact
references. `migrate_legacy_artifacts` remains the one implementation that
recognizes legacy field names, but it is invoked solely at the import entry
point. Runtime nodes such as `post_l3_main_nodes` and `context_bootstrap`
consume the already-migrated `artifact_refs` and must not call the migration
themselves.

## Required Fields
Output `artifact_refs` map (canonical keys):
| Key | Source (legacy field) | Type | Required |
|---|---|---|---|
| `planning_program` | `l3_program_ref` | dict (artifact) | optional |
| `grounding_result` | `grounding_result_ref` | dict (artifact) | optional |
| `site_selection` | `site_selection_ref` | dict (artifact) | optional |
| `parcel_changeset` | `parcel_changeset_ref` | dict (artifact) | optional |
| `planned_state` | `planned_state_ref` | dict (artifact) | optional |
| `validation_report` | `validation_report_ref` | dict (artifact) | optional |
| `reconciliation_report` | `reconciliation_report_ref` | dict (artifact) | optional |

Each value is a reference dict carrying `artifact_id`; the migration copies a
legacy value only when the canonical key is absent and the legacy field holds a
dict with a valid `artifact_id`.

## Classification
Computation intermediate (a normalization of checkpoint references). It is not
a domain fact and not a render view — it is bookkeeping that bridges old
checkpoint layouts to the canonical artifact store.

## Migration Boundary
The single entry point for old data conversion is the checkpoint-import
boundary. `migrate_legacy_artifacts` is invoked exactly once per imported
checkpoint at import time. No runtime node performs legacy migration.

## Consequences
What breaks:
- `post_l3_main_nodes._load_ref_artifact` and
  `context_bootstrap._hydrate_l1_spatial_facts` must stop calling
  `migrate_legacy_artifacts`; they consume the pre-migrated `artifact_refs`
  from state.
- Any runtime path that relies on the migration running lazily inside a node
  must instead ensure migration happens at import.

What becomes easier:
- A single, auditable migration point for legacy checkpoints.
- Runtime nodes no longer carry legacy-conversion logic.
- The migration implementation is used in exactly one place, so it can change
  without affecting node execution.
