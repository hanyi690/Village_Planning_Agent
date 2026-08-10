# Task 1 Report: Target contracts and unresolved-reference preservation

## Status

DONE_WITH_CONCERNS

## Implementation details

- Added v2 L3 target semantics to `PlanningIntervention`: stable `target_id`, `execution_mode`, and `expected_output_kind`. Target semantics normalize category defaults (`facility` -> `point`, `road` -> `line`, zone-like targets -> `polygon`) and force non-spatial targets to `action` output.
- Added the shared PARSE `TargetExecutionContract` to project, facility, road, axis, and zone targets. It carries stable target identity, target output semantics, and derives `requires_spatial` solely from `execution_mode`.
- Updated the deterministic compiler so it copies L3 target semantics directly into PARSE targets. It no longer derives `requires_spatial` from whether a spatial-reference spec happened to be generated.
- Spatial targets without location evidence now receive a linked unresolved `SpatialReferenceSpec` (`spec_id`, `target_id`, `unresolved_reason="missing_location_evidence"`) and an `UNRESOLVED_SPATIAL_REFERENCE` diagnostic. Non-spatial interventions receive no spatial spec and remain typed `action` targets.
- Extended GROUND evidence and unresolved issues with target/spec linkage. An unresolved spec is deliberately not resolved through candidate lookup and is retained in the immutable grounding artifact.
- Added frozen v2 `DeferralLedger`, `TargetDeferral`, and `HumanDeferralDecision` contracts. Deferrals require explicit target IDs, must reference currently unresolved GROUND targets, and persist source references plus human decision metadata.
- Removed the acknowledgement path that cleared `GroundingResult.unresolved`. Human deferral now records only the explicit requested target IDs; it cannot infer targets from facility names, ordering, or all unplaced projects.
- Upgraded the affected root artifacts (`PlanningProgram`, `IntentCompilationResult`, `GroundingResult`, and `DeferralLedger`) to `schema_version="2.0"`.

## Changed files

- `backend/app/modules/schema/contracts/l3_contracts.py`
- `backend/app/modules/schema/contracts/parse_contracts.py`
- `backend/app/modules/schema/contracts/parse_result_contracts.py`
- `backend/app/modules/schema/contracts/spatial_reference_contracts.py`
- `backend/app/modules/schema/contracts/grounding_contracts.py`
- `backend/app/modules/schema/contracts/deferral_contracts.py`
- `backend/app/modules/parsing/compiler/spec_mapper.py`
- `backend/app/agent/parse/compile_node.py`
- `backend/app/agent/parse/review.py`
- `backend/app/agent/ground/aggregate.py`
- `backend/app/agent/bootstrap/post_l3_main_nodes.py`
- `backend/app/agent/bootstrap/graph.py`
- `backend/app/agent/bootstrap/artifact_runtime.py`
- `backend/tests/e2e/test_target_contracts_e2e.py`
- `backend/tests/e2e/test_unified_graph_replay_e2e.py`

## TDD evidence

### RED

Command:

```powershell
pytest tests/e2e/test_target_contracts_e2e.py -m e2e -q
```

Result: failed during collection with `ModuleNotFoundError: No module named 'app.modules.schema.contracts.deferral_contracts'`. This captured the absent deferral contract before implementation.

### GREEN

Command:

```powershell
pytest tests/e2e/test_target_contracts_e2e.py tests/e2e/test_unified_graph_replay_e2e.py -m e2e -q
```

Result: `31 passed in 10.23s`.

The focused coverage proves physical targets remain spatial without location evidence, non-spatial targets compile as actions, v2 root schema versions, unresolved GROUND target/spec linkage, immutable ledger data, acknowledgement preservation, explicit target-ID enforcement, and ledger persistence.

## Backend suite

Command:

```powershell
pytest -q
```

Result: `100 passed, 1 skipped, 1 deselected in 33.80s`.

The skipped test is the pre-existing `tests/e2e/test_kg_jintian_e2e.py:1119` skip for an already-removed `_add_parcels` helper; it is outside Task 1.

## Self-review

- Confirmed all joins and review mappings changed by this task use `target_id`, not facility type names or list positions.
- Confirmed non-spatial targets do not emit spatial specs and never depend on `ParcelChange` compatibility paths.
- Confirmed unresolved spatial targets retain their spec linkage through PARSE diagnostics and GROUND issues/evidence.
- Confirmed a deferral cannot proceed without explicit target IDs and cannot name a target that is not currently unresolved.
- Confirmed the original `backend/.pytest-tmp-run/` untracked directory remains untouched.
- Ran `git diff --check` and `python -m compileall` for the changed backend modules successfully.

## Concerns

- The full backend suite retains one unrelated, explicitly skipped KG provenance test. Task 1-specific and unified graph replay coverage are fully passing.
