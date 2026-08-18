# Task 3 report — preserve delivery refs across diagnostic transitions

## Result

Implemented the runtime checkpoint fix in
`backend/app/infrastructure/runtime/planning_runtime_service.py`.

Diagnostic, resume, and state reads now use one artifact-ref merge path. It
unions valid refs from:

- the compact checkpoint `artifact_refs` channel;
- the stage-local `runtime.artifact_refs` carrier; and
- refs supplied by the current patch or its runtime patch.

Empty, falsy, and malformed ref values are discarded, so they cannot remove an
existing valid ref. When the same key appears more than once, the valid
descriptor with the newer `created_at` wins. The merge is used by
`aget_state_values()`, `aupdate_state()`, and the service resume/state-entry
command paths, so reconcile/no-progress terminalization preserves successful
`delivery_manifest`, `delivery_spatial_snapshot`, `render_artifacts`, and
`render_layers` refs even when raw checkpoint refs are split between top-level
and runtime channels.

The earlier session-KG force optimization was removed; resume again uses the
original `force=bundle_version is not None` behavior because this task does not
have a reliable bundle-version consistency proof for an existing KG.

## Deterministic regression coverage

Added focused runtime tests in
`backend/tests/core/test_runtime_channel_roundtrip.py` covering:

- raw top-level/runtime refs surviving materialization as a union;
- falsy and malformed refs being filtered;
- newer valid descriptors winning same-key conflicts; and
- an `end_diagnostic` update preserving delivery refs despite falsy patch
  values.

## Verification

- `pytest -q -o addopts= backend/tests/core/test_runtime_channel_roundtrip.py`
  — **11 passed**.
- No acceptance or real-network test was run during this review pass.
- `git diff --check` for the changed service and focused runtime test — clean.
- No commit was created, and unrelated dirty worktree changes were not reset or
  discarded.
